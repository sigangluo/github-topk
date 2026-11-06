"""Offline checks for current exclusions and future historical inclusions."""
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import catalog
from common import read_json, write_json


class CatalogLifecycleTests(unittest.TestCase):
    def test_website_uses_repository_homepage_only(self):
        self.assertEqual(catalog.project_website('https://example.org/docs'), 'https://example.org/docs')
        self.assertEqual(catalog.project_website('https://github.com/owner/repo'), '')
        self.assertEqual(catalog.project_website('https://www.youtube.com/watch?v=example'), '')
        self.assertEqual(catalog.project_website('https://arxiv.org/abs/1234.5678'), '')
        self.assertEqual(catalog.project_website('javascript:alert(1)'), '')
        self.assertEqual(catalog.project_website('https://[invalid'), '')
        self.assertEqual(catalog.project_website('https://example.org:invalid'), '')

    def test_candidate_prefetch_uses_one_repository_request(self):
        class FakeGitHub:
            calls = []

            def rest(self, path):
                self.calls.append(path)
                return {'description': 'A useful tool', 'archived': False,
                        'license': {'spdx_id': 'MIT'}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ranking = root / 'ranking.json'
            excluded = root / 'excluded.json'
            candidates = root / 'candidates.json'
            write_json(ranking, {'repos': [{'name': 'owner/new', 'rank': 1, 'stars': 100}]})
            write_json(excluded, {'repos': [], 'reviews': {}})
            fake = FakeGitHub()
            with patch.object(catalog, 'RANKING_PATH', ranking), \
                 patch.object(catalog, 'EXCLUDED_PATH', excluded), \
                 patch.object(catalog, 'CANDIDATES_PATH', candidates), \
                 patch.object(catalog, 'sources', return_value={'ai': {'projects': {}},
                                                               'fullstack': {'projects': {}}}), \
                 patch.object(catalog, 'GitHub', return_value=fake):
                with redirect_stdout(StringIO()):
                    catalog.make_candidates()
            self.assertEqual(fake.calls, ['/repos/owner/new'])
            self.assertEqual(read_json(candidates)[0]['license'], 'MIT')

    def test_prune_exclusions_outside_current_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'excluded.json'
            write_json(path, {'repos': ['owner/current', 'owner/departed'],
                              'reviews': {'owner/departed': {'reason': 'old'}}})
            ranking = {'repos': [{'name': 'owner/current', 'rank': 1}]}
            with patch.object(catalog, 'EXCLUDED_PATH', path):
                with redirect_stdout(StringIO()):
                    catalog.prune_excluded(ranking)
            self.assertEqual(read_json(path), {'repos': ['owner/current'], 'reviews': {}})

    def test_newly_departed_inclusion_remains_with_fresh_metadata(self):
        ranking = {'k': 1, 'fetched_at': '2026-11-06', 'cutoff_stars': 100,
                   'repos': [{'name': 'owner/current', 'rank': 1, 'stars': 100}]}
        source = {'ai': {'taxonomy': [], 'projects': {
            'owner/current': {'category': 'example'},
            'owner/departed': {'category': 'example'}}},
                  'fullstack': {'taxonomy': [], 'projects': {}}}
        cache = {name: {'stars': stars, 'watching': 5, 'forks': 7, 'website': 'https://example.org', 'license': 'MIT', 'created': '2020-01-01', 'pushed': '2026-11-06',
                        'stack': 'Python', 'archived': False, 'fetched_at': '2026-11-06'}
                 for name, stars in [('owner/current', 100), ('owner/departed', 90)]}
        result = catalog.make_site(ranking, source, cache, generated_at='2026-11-06')
        projects = {item['name']: item for item in result['views']['ai']['projects']}
        self.assertEqual(projects['owner/current']['rank'], 1)
        self.assertIsNone(projects['owner/departed']['rank'])
        self.assertEqual(projects['owner/departed']['stars'], 90)
        self.assertEqual(projects['owner/departed']['watching'], 5)
        self.assertEqual(projects['owner/departed']['website'], 'https://example.org')
        cache['owner/departed']['website'] = 'javascript:alert(1)'
        with self.assertRaisesRegex(RuntimeError, 'invalid GitHub metadata'):
            catalog.make_site(ranking, source, cache, generated_at='2026-11-06')
        cache['owner/departed']['website'] = 'https://example.org'
        cache['owner/departed']['fetched_at'] = '2026-11-07'
        mixed = catalog.make_site(ranking, source, cache, generated_at='2026-11-07')
        self.assertEqual(mixed['metadata_as_of'], '2026-11-06')
        self.assertEqual(mixed['metadata_reference_date'], '2026-11-07')


if __name__ == '__main__':
    unittest.main()
