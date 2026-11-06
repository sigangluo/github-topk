#!/usr/bin/env python3
"""Refresh, review, build and validate the standalone GitHub Top-K catalog.

  python3 scripts/catalog.py refresh [--k 2000]
  # Review data/candidates.json, then edit data/ai|fullstack/projects.json or data/excluded.json.
  python3 scripts/catalog.py candidates       # Regenerate pending decisions after editing
  python3 scripts/catalog.py finish           # Fetch metadata and build both catalog views
  python3 scripts/catalog.py finish --offline # Reuse cached metadata for editorial edits
  python3 scripts/catalog.py check            # No network or source mutation
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import urllib.parse

from common import DATA, ROOT, RANKING_PATH, GitHub, read_json, write_json
import rank
from note_pages import render_page

KINDS = ('ai', 'fullstack')
NOTE_LANGS = ('zh', 'en')
SITE_PATH = ROOT / 'site/data/catalog.json'
SITE_NOTES = ROOT / 'site/notes'
CACHE_PATH = DATA / 'cache.json'
CANDIDATES_PATH = DATA / 'candidates.json'
EXCLUDED_PATH = DATA / 'excluded.json'
META_FIELDS = ('stars', 'watching', 'forks', 'website', 'license', 'created', 'pushed', 'stack', 'archived')
REQUIRED = ('category', 'official', 'officialOrg', 'summary', 'summary_en', 'added')
BATCH = 80
WORKERS = 6
REVIEW_FROM = dt.date(2026, 11, 4)


def sources():
    return {kind: {'projects': read_json(DATA / kind / 'projects.json'),
                   'taxonomy': read_json(DATA / kind / 'taxonomy.json')}
            for kind in KINDS}


def ranked_names(ranking):
    return {item['name'].lower(): item['rank'] for item in ranking['repos']}


def pending(ranking, source, excluded):
    decided = {name.lower() for kind in KINDS for name in source[kind]['projects']}
    decided |= {name.lower() for name in excluded['repos']}
    return [item for item in ranking['repos'] if item['name'].lower() not in decided]


def prune_excluded(ranking):
    """Keep exclusion decisions only for repositories in the current snapshot."""
    excluded = read_json(EXCLUDED_PATH)
    current = set(ranked_names(ranking))
    old = excluded['repos']
    excluded['repos'] = [name for name in old if name.lower() in current]
    excluded['reviews'] = {name: review for name, review in excluded.get('reviews', {}).items()
                           if name.lower() in current}
    if len(excluded['repos']) != len(old):
        write_json(EXCLUDED_PATH, excluded)
        print(f'Pruned {len(old) - len(excluded["repos"])} exclusions outside the current Top-K.')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def valid_date(value):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def project_website(value):
    """Use only a repository-declared web address, never a GitHub repository link."""
    if not isinstance(value, str):
        return ''
    value = value.strip()
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname.lower() if parsed.hostname else ''
        _ = parsed.port  # Reject malformed ports before publishing the link.
    except ValueError:
        return ''
    if parsed.scheme not in ('http', 'https') or not host or parsed.username or parsed.password:
        return ''
    # Repository homepages may point to social profiles, papers, or package registries.
    # These are useful references but are not an official project website.
    non_sites = ('githubusercontent.com', 'youtube.com', 'youtu.be',
                 'discord.gg', 'discord.com', 't.me', 'telegram.me', 'medium.com',
                 'linkedin.com', 'twitter.com', 'x.com', 'facebook.com',
                 'instagram.com', 'reddit.com', 'patreon.com', 'arxiv.org',
                 'pypi.org', 'npmjs.com', 'crates.io', 'bit.ly', 'git.io',
                 'dsc.gg', 'tinyurl.com')
    if host in ('github.com', 'www.github.com') or any(host == blocked or host.endswith('.' + blocked) for blocked in non_sites):
        return ''
    return value


def validate_source(ranking, source, excluded):
    repos = ranking['repos']
    k = ranking['k']
    require(type(k) is int and k > 0 and len(repos) == k, 'Ranking length differs from K')
    require([r['rank'] for r in repos] == list(range(1, k + 1)), 'Ranking positions are not continuous')
    require(all(repos[i]['stars'] >= repos[i+1]['stars'] for i in range(k-1)), 'Ranking stars not descending')
    require(ranking['cutoff_stars'] == repos[-1]['stars'], 'Ranking cutoff differs from last item')
    require(len({r['name'].lower() for r in repos}) == k, 'Duplicate ranking names')
    require(valid_date(ranking.get('fetched_at')) is not None, 'Invalid ranking snapshot date')
    require(all(isinstance(r['name'], str) and re.fullmatch(r'[\w.-]+/[\w.-]+', r['name'])
                and type(r['stars']) is int and r['stars'] >= 0 for r in repos),
            'Ranking contains invalid repository names or star counts')
    all_names = {}
    for kind in KINDS:
        taxonomy = source[kind]['taxonomy']
        projects = source[kind]['projects']
        major_keys = [m['key'] for m in taxonomy]
        subs = [s['key'] for m in taxonomy for s in m['subs']]
        require(len(major_keys) == len(set(major_keys)), f'{kind}: duplicate major key')
        require(len(subs) == len(set(subs)), f'{kind}: duplicate subcategory key')
        for major in taxonomy:
            require(major['subs'], f'{kind}/{major["key"]}: empty category')
            for node in [major] + major['subs']:
                require(all(isinstance(node.get(field), str) and node[field].strip()
                            for field in ('key', 'label', 'label_en', 'def', 'def_en')),
                        f'{kind}/{node.get("key")}: incomplete bilingual taxonomy node')
        for name, item in projects.items():
            key = name.lower()
            require(re.fullmatch(r'[\w.-]+/[\w.-]+', name), f'{name}: invalid repository name')
            require(key not in all_names, f'{name}: duplicated in {all_names.get(key)} and {kind}')
            all_names[key] = kind
            require(all(field in item for field in REQUIRED), f'{name}: missing project field')
            require(item['category'] in subs, f'{name}: unknown category')
            require(type(item['official']) is bool, f'{name}: official must be boolean')
            require(bool(item['officialOrg']) == item['official'], f'{name}: official organization mismatch')
            require(isinstance(item['summary'], str) and item['summary'].strip(), f'{name}: empty Chinese summary')
            require(isinstance(item['summary_en'], str) and item['summary_en'].strip(), f'{name}: empty English summary')
            require(bool(re.search(r'[\u4e00-\u9fff]', item['summary'])), f'{name}: Chinese summary has no Chinese text')
            require(not re.search(r'[\u4e00-\u9fff]', item['summary_en']), f'{name}: Chinese in English summary')
            added = valid_date(item['added'])
            require(added is not None, f'{name}: invalid added date')
            if added >= REVIEW_FROM or 'review' in item:
                review = item.get('review') or {}
                require(review.get('reason', '').strip(), f'{name}: missing review reason')
                require(review.get('source_url') == 'https://github.com/' + name, f'{name}: wrong review URL')
                require(valid_date(review.get('reviewed_at')) is not None, f'{name}: invalid review date')
    excluded_names = {name.lower() for name in excluded['repos']}
    require(len(excluded_names) == len(excluded['repos']), 'Duplicate exclusions')
    require(excluded_names <= set(ranked_names(ranking)), 'Excluded repositories outside current Top-K; run refresh')
    require(not (excluded_names & set(all_names)), 'Included project is also excluded')
    require(set(excluded.get('reviews', {})) <= set(excluded['repos']), 'Orphan exclusion review')
    for name, review in excluded.get('reviews', {}).items():
        require(review.get('reason', '').strip(), f'{name}: missing exclusion reason')
        require(review.get('source_url') == 'https://github.com/' + name, f'{name}: wrong exclusion URL')
        require(valid_date(review.get('reviewed_at')) is not None, f'{name}: invalid exclusion review date')
    require(not pending(ranking, source, excluded), 'Unreviewed ranked projects remain; run candidates')
    require(read_json(CANDIDATES_PATH) == [], 'Candidate list is not empty')


def make_candidates(offline=False):
    ranking = read_json(RANKING_PATH)
    source = sources()
    excluded = read_json(EXCLUDED_PATH)
    todo = pending(ranking, source, excluded)
    if not offline and todo:
        gh = GitHub()
        def details(item):
            result = dict(item)
            meta = gh.rest('/repos/' + urllib.parse.quote(item['name'])) or {}
            result.update(description=meta.get('description') or '', archived=meta.get('archived'),
                          license=(meta.get('license') or {}).get('spdx_id') or '')
            return result
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            todo = list(pool.map(details, todo))
    write_json(CANDIDATES_PATH, todo)
    print(f'Candidates: {len(todo)}. Review into AI, Full-stack or excluded, then regenerate candidates.')


def fetch_metadata(names):
    gh = GitHub()
    chunks = [names[i:i+BATCH] for i in range(0, len(names), BATCH)]
    def one(chunk):
        parts = []
        for i, name in enumerate(chunk):
            owner, repo = name.split('/', 1)
            parts.append(f'r{i}: repository(owner:{json.dumps(owner)},name:{json.dumps(repo)}) {{ nameWithOwner description homepageUrl licenseInfo {{ spdxId }} stargazerCount watchers {{ totalCount }} forkCount createdAt pushedAt isArchived languages(first:2,orderBy:{{field:SIZE,direction:DESC}}) {{ nodes {{ name }} }} }}')
        result = gh.graphql('query {\n' + '\n'.join(parts) + '\n}')
        values, missing, renamed = {}, [], []
        for i, name in enumerate(chunk):
            repo = result.get(f'r{i}')
            if not repo:
                missing.append(name)
                continue
            if repo['nameWithOwner'].lower() != name.lower():
                renamed.append((name, repo['nameWithOwner']))
            values[name] = {'description': repo.get('description') or '',
                            'license': (repo.get('licenseInfo') or {}).get('spdxId') or '',
                            'website': project_website(repo.get('homepageUrl')),
                            'stars': repo['stargazerCount'], 'watching': repo['watchers']['totalCount'],
                            'forks': repo['forkCount'], 'created': repo['createdAt'][:10],
                            'pushed': repo['pushedAt'][:10], 'stack': ' / '.join(n['name'] for n in repo['languages']['nodes']) or 'Markdown',
                            'archived': repo['isArchived'], 'fetched_at': dt.date.today().isoformat()}
        return values, missing, renamed
    found, missing, renamed = {}, [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(one, chunk) for chunk in chunks]
        for i, future in enumerate(as_completed(futures), 1):
            values, absent, changes = future.result()
            found.update(values); missing.extend(absent); renamed.extend(changes)
            print(f'Metadata batches: {i}/{len(chunks)}', flush=True)
    if missing or renamed:
        raise RuntimeError(f'Resolve missing or renamed repositories before building: missing={missing}, renamed={renamed}')
    return found


def note_files(source):
    """Map each existing language-specific source note to a stable site URL."""
    found = {}
    for kind in KINDS:
        major_for_sub = {sub['key']: major['key'] for major in source[kind]['taxonomy']
                         for sub in major['subs']}
        for name, project in source[kind]['projects'].items():
            major = major_for_sub.get(project['category'])
            if major is None:
                continue
            filename = name.replace('/', '__', 1)
            for lang in NOTE_LANGS:
                src = ROOT / 'notes' / lang / kind / major / project['category'] / (filename + '.md')
                if src.is_file() and not src.is_symlink():
                    url = Path('notes') / lang / kind / (filename + '.html')
                    found[name, lang] = (src, url)
    return found


def note_pages(source):
    pages = {}
    for (name, lang), (src, url) in note_files(source).items():
        pages[ROOT / 'site' / url] = render_page(name, lang, url.parts[2], src.read_text(encoding='utf-8'))
    return pages


def sync_note_pages(source):
    expected = note_pages(source)
    if SITE_NOTES.exists() or SITE_NOTES.is_symlink():
        require(SITE_NOTES.is_dir() and not SITE_NOTES.is_symlink(), f'Invalid generated notes: {SITE_NOTES}')
        for path in SITE_NOTES.rglob('*'):
            require(not path.is_symlink(), f'Invalid generated note path: {path}')
            if path.is_file():
                require(path.suffix == '.html', f'Unexpected generated note file: {path}')
                if path not in expected:
                    path.unlink()
        for path in sorted(SITE_NOTES.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')


def check_note_pages(source):
    expected = note_pages(source)
    actual = {path for path in SITE_NOTES.rglob('*') if path.is_file()} if SITE_NOTES.exists() else set()
    require(actual == set(expected), 'Generated note pages differ from source notes; run finish --offline')
    for path, content in expected.items():
        require(path.read_text(encoding='utf-8') == content,
                f'Generated note page is stale: {path}; run finish --offline')


def make_site(ranking, source, cache, generated_at=None):
    rank_by_name = ranked_names(ranking)
    notes = note_files(source)
    generated_at = generated_at or dt.date.today().isoformat()
    views = {}
    for kind in KINDS:
        projects = []
        for name, item in source[kind]['projects'].items():
            base = {'name': name, **item, 'origin': kind}
            note_links = {lang: notes[name, lang][1].as_posix() for lang in NOTE_LANGS if (name, lang) in notes}
            if note_links:
                base['notes'] = note_links
            record = cache.get(name, {})
            meta = {field: record.get(field) for field in META_FIELDS}
            require(type(meta['stars']) is int and meta['stars'] >= 0
                    and type(meta['watching']) is int and meta['watching'] >= 0
                    and type(meta['forks']) is int and meta['forks'] >= 0
                    and isinstance(meta['website'], str)
                    and project_website(meta['website']) == meta['website']
                    and isinstance(meta['license'], str)
                    and valid_date(meta['created']) is not None
                    and valid_date(meta['pushed']) is not None
                    and isinstance(meta['stack'], str) and bool(meta['stack'].strip())
                    and type(meta['archived']) is bool
                    and valid_date(record.get('fetched_at')) is not None,
                    f'{name}: missing or invalid GitHub metadata; run finish online')
            require(record['fetched_at'] >= ranking['fetched_at'],
                    f'{name}: GitHub metadata predates ranking snapshot; run finish online')
            if name.lower() in rank_by_name:
                base.update(meta, rank=rank_by_name[name.lower()])
            else:
                base.update(meta, rank=None)
            projects.append(base)
        projects.sort(key=lambda p: (p['rank'] is None,
                                     p['rank'] if p['rank'] is not None else 0,
                                     p['name'].lower()))
        views[kind] = {'taxonomy': source[kind]['taxonomy'], 'projects': projects}
    dates = [cache[name]['fetched_at'] for kind in KINDS for name in source[kind]['projects']]
    return {'name': 'GitHub Top-K', 'generated_at': generated_at,
            'metadata_as_of': min(dates) if dates else None,
            'metadata_reference_date': max(dates) if dates else None,
            'ranking_digest': hashlib.sha256(json.dumps(ranking, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'ranking': {key: ranking[key] for key in ('k', 'fetched_at', 'cutoff_stars')},
            'views': views}


def expected_dirs(taxonomy):
    for major in taxonomy:
        for key in [major['key']] + [sub['key'] for sub in major['subs']]:
            require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', key)),
                    f'Unsafe category directory key: {key!r}')
    return {m['key']: {s['key'] for s in m['subs']} for m in taxonomy}


def obsolete_dir(path, files, dirs):
    require(path.is_dir() and not path.is_symlink(), f'Invalid category directory: {path}')
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            obsolete_dir(child, files, dirs)
        elif child.is_file() and not child.is_symlink() and child.name in ('.gitkeep', '.DS_Store'):
            files.append(child)
        else:
            raise RuntimeError(f'Move project content out of obsolete category before syncing: {child}')
    dirs.append(path)


def plan_tree(root, expected, files, dirs):
    if not root.exists() and not root.is_symlink():
        return
    require(root.is_dir() and not root.is_symlink(), f'Invalid directory: {root}')
    for major in root.iterdir():
        if major.name == '.DS_Store' and major.is_file() and not major.is_symlink():
            continue
        require(major.is_dir() and not major.is_symlink(), f'Invalid category path: {major}')
        if major.name not in expected:
            obsolete_dir(major, files, dirs)
            continue
        for sub in major.iterdir():
            if sub.name == '.DS_Store' and sub.is_file() and not sub.is_symlink():
                continue
            require(sub.is_dir() and not sub.is_symlink(), f'Invalid subcategory path: {sub}')
            if sub.name not in expected[major.name]:
                obsolete_dir(sub, files, dirs)


def create_tree(root, expected, create_markers):
    root.mkdir(parents=True, exist_ok=True)
    for major, subs in expected.items():
        for sub in subs:
            path = root / major / sub
            path.mkdir(parents=True, exist_ok=True)
            if create_markers:
                (path / '.gitkeep').touch(exist_ok=True)


def sync_dirs(source):
    trees = []
    for kind in KINDS:
        expected = expected_dirs(source[kind]['taxonomy'])
        trees.append((ROOT / 'repos' / kind, expected, False))
        for lang in NOTE_LANGS:
            trees.append((ROOT / 'notes' / lang / kind, expected, True))
    notes_root = ROOT / 'notes'
    if notes_root.exists() or notes_root.is_symlink():
        require(notes_root.is_dir() and not notes_root.is_symlink(), f'Invalid directory: {notes_root}')
        require({p.name for p in notes_root.iterdir() if p.name != '.DS_Store'} <= set(NOTE_LANGS),
                'Move notes into notes/zh/ or notes/en/ before syncing')
    files, dirs = [], []
    for root, expected, _ in trees:
        plan_tree(root, expected, files, dirs)
    for path in files:
        path.unlink()
    for path in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        path.rmdir()
    for root, expected, markers in trees:
        create_tree(root, expected, markers)


def check_dirs(source):
    notes_root = ROOT / 'notes'
    require(notes_root.is_dir() and not notes_root.is_symlink(), f'Missing or invalid {notes_root}')
    require({p.name for p in notes_root.iterdir() if p.name != '.DS_Store'} == set(NOTE_LANGS),
            f'{notes_root}: language directories must be zh and en')
    for lang in NOTE_LANGS:
        root = notes_root / lang
        require(root.is_dir() and not root.is_symlink(), f'Missing or invalid {root}')
        require({p.name for p in root.iterdir() if p.name != '.DS_Store'} == set(KINDS),
                f'{root}: catalog directions must be ai and fullstack')
    repos_root = ROOT / 'repos'
    if repos_root.exists() or repos_root.is_symlink():
        require(repos_root.is_dir() and not repos_root.is_symlink(), f'Invalid directory: {repos_root}')
        require({p.name for p in repos_root.iterdir() if p.name != '.DS_Store'} == set(KINDS),
                f'{repos_root}: catalog directions must be ai and fullstack')
    for kind in KINDS:
        expected = expected_dirs(source[kind]['taxonomy'])
        trees = [(notes_root / lang / kind, True) for lang in NOTE_LANGS]
        if repos_root.exists():
            trees.append((repos_root / kind, False))
        for root, is_note in trees:
            require(root.is_dir() and not root.is_symlink(), f'Missing or invalid {root}')
            require({p.name for p in root.iterdir() if p.name != '.DS_Store'} == set(expected), f'{root}: category mismatch')
            for major, subs in expected.items():
                mpath = root / major
                require(mpath.is_dir() and not mpath.is_symlink(), f'Invalid {mpath}')
                require({p.name for p in mpath.iterdir() if p.name != '.DS_Store'} == subs, f'{mpath}: subcategory mismatch')
                for sub in subs:
                    path = mpath / sub
                    require(path.is_dir() and not path.is_symlink(), f'Invalid {path}')
                    if is_note:
                        require((path / '.gitkeep').is_file(), f'Missing marker in {path}')
                        for note in path.iterdir():
                            if note.name in ('.gitkeep', '.DS_Store'): continue
                            require(note.is_file() and not note.is_symlink() and note.suffix == '.md' and '__' in note.stem,
                                    f'Invalid note: {note}')
                            owner, repo = note.stem.split('__', 1)
                            name = owner + '/' + repo
                            project = source[kind]['projects'].get(name)
                            require(project is not None and project['category'] == sub,
                                    f'Note category does not match project: {note}')


def check():
    ranking = read_json(RANKING_PATH); source = sources(); excluded = read_json(EXCLUDED_PATH)
    validate_source(ranking, source, excluded)
    check_dirs(source)
    check_note_pages(source)
    cache = read_json(CACHE_PATH)
    included = {name for kind in KINDS for name in source[kind]['projects']}
    require(set(cache) == included, 'Metadata cache differs from included projects; run finish online')
    require(all(isinstance(cache[name].get('description'), str) and isinstance(cache[name].get('license'), str)
                for name in included), 'Description or license cache missing; run finish online')
    site = read_json(SITE_PATH)
    require(site == make_site(ranking, source, cache, site['generated_at']), 'Site data is out of date; run finish')
    require(set(site['views']) == set(KINDS), 'Site must have AI and full-stack views')
    names = set()
    rank_names = {item['name'].lower() for item in ranking['repos']}
    for kind, view in site['views'].items():
        keys = {sub['key'] for major in view['taxonomy'] for sub in major['subs']}
        require(len(view['projects']) == len(source[kind]['projects']), f'{kind}: missing included projects')
        for project in view['projects']:
            name = project['name']
            require(name not in names, f'{name}: appears in multiple views')
            names.add(name)
            require(name in source[kind]['projects'], f'{name}: not in {kind} source list')
            require(project['category'] in keys, f'{name}: category missing from {kind} view')
            require((project['rank'] is None) == (name.lower() not in rank_names), f'{name}: rank mismatch')
    require(len(names) == sum(len(source[kind]['projects']) for kind in KINDS),
            'Displayed project count differs from source lists')
    print('Validated: ' + ', '.join(f'{kind}={len(site["views"][kind]["projects"])}' for kind in KINDS) +
          f'; current Top-K={sum(p["rank"] is not None for view in site["views"].values() for p in view["projects"])}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    refresh = sub.add_parser('refresh'); refresh.add_argument('--k', type=int)
    candidates = sub.add_parser('candidates'); candidates.add_argument('--offline', action='store_true')
    finish = sub.add_parser('finish'); finish.add_argument('--offline', action='store_true')
    sub.add_parser('check'); sub.add_parser('sync')
    args = parser.parse_args()
    if args.command == 'refresh':
        if args.k is not None and args.k < 1: parser.error('--k must be positive')
        rank_args = ['--k', str(args.k)] if args.k else []
        import sys
        saved = sys.argv
        try: sys.argv = ['rank.py', *rank_args]; rank.main()
        finally: sys.argv = saved
        prune_excluded(read_json(RANKING_PATH))
        make_candidates()
    elif args.command == 'candidates': make_candidates(args.offline)
    elif args.command == 'finish':
        ranking = read_json(RANKING_PATH); source = sources(); excluded = read_json(EXCLUDED_PATH)
        validate_source(ranking, source, excluded)
        cache = read_json(CACHE_PATH)
        if args.offline and SITE_PATH.exists():
            previous = read_json(SITE_PATH).get('ranking_digest')
            current = hashlib.sha256(json.dumps(ranking, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            require(previous == current,
                    'Ranking changed since the last build; run finish online to refresh metadata')
        if not args.offline:
            names = [name for kind in KINDS for name in source[kind]['projects']]
            updated = fetch_metadata(names)
            changed = [name for name in names if name in cache and 'description' in cache[name]
                       and (cache[name]['description'], cache[name].get('license')) !=
                           (updated[name]['description'], updated[name]['license'])]
            if changed:
                print('Repository descriptions or licenses changed: ' + ', '.join(changed))
            cache = updated
            write_json(CACHE_PATH, cache)
        sync_dirs(source)
        check_dirs(source)
        sync_note_pages(source)
        write_json(SITE_PATH, make_site(ranking, source, cache))
        check()
    elif args.command == 'check': check()
    else: sync_dirs(sources())


if __name__ == '__main__':
    main()
