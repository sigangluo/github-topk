"""Render the repository's own project notes as self-contained site pages."""
import html
import re


INLINE = re.compile(r'`([^`]+)`|\[([^\]]+)\]\((https?://[^\s)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*')
LIST_ITEM = re.compile(r'^\s*(?:([-*])|(\d+)\.)\s+(.+)$')
HEADING = re.compile(r'^(#{1,6})\s+(.+)$')


def inline(text):
    """Escape raw HTML and support a small, safe set of inline Markdown."""
    parts, offset = [], 0
    for match in INLINE.finditer(text):
        parts.append(html.escape(text[offset:match.start()]))
        code, link_text, link_url, strong, emphasis = match.groups()
        if code is not None:
            parts.append('<code>' + html.escape(code) + '</code>')
        elif link_url is not None:
            parts.append('<a href="' + html.escape(link_url, quote=True) +
                         '" target="_blank" rel="noopener noreferrer">' + html.escape(link_text) + '</a>')
        elif strong is not None:
            parts.append('<strong>' + html.escape(strong) + '</strong>')
        else:
            parts.append('<em>' + html.escape(emphasis) + '</em>')
        offset = match.end()
    parts.append(html.escape(text[offset:]))
    return ''.join(parts)


def table_cells(line):
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


def table_separator(line):
    cells = table_cells(line)
    return len(cells) > 1 and all(re.fullmatch(r':?-{3,}:?', cell) for cell in cells)


def render_markdown(text):
    """Render headings, prose, tables, lists and code without accepting raw HTML."""
    lines = text.splitlines()
    output, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith('```'):
            code, i = [], i + 1
            while i < len(lines) and not lines[i].startswith('```'):
                code.append(lines[i]); i += 1
            output.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>')
            i += 1 if i < len(lines) else 0
            continue
        heading = HEADING.match(line)
        if heading:
            level = min(len(heading.group(1)) + 1, 6)
            output.append(f'<h{level}>' + inline(heading.group(2)) + f'</h{level}>')
            i += 1
            continue
        if i + 1 < len(lines) and '|' in line and table_separator(lines[i + 1]):
            headers = table_cells(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip() and '|' in lines[i]:
                rows.append(table_cells(lines[i])); i += 1
            head = ''.join('<th scope="col">' + inline(cell) + '</th>' for cell in headers)
            body = ''.join('<tr>' + ''.join('<td>' + inline(row[j] if j < len(row) else '') + '</td>'
                                            for j in range(len(headers))) + '</tr>' for row in rows)
            output.append('<div class="note-table-wrap"><table><thead><tr>' + head +
                          '</tr></thead><tbody>' + body + '</tbody></table></div>')
            continue
        item = LIST_ITEM.match(line)
        if item:
            ordered = item.group(2) is not None
            tag = 'ol' if ordered else 'ul'
            entries = []
            while i < len(lines):
                current = LIST_ITEM.match(lines[i])
                if not current or (current.group(2) is not None) != ordered:
                    break
                entries.append('<li>' + inline(current.group(3)) + '</li>')
                i += 1
            output.append(f'<{tag}>' + ''.join(entries) + f'</{tag}>')
            continue
        paragraph = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not HEADING.match(lines[i]) and \
                not LIST_ITEM.match(lines[i]) and not lines[i].startswith('```') and \
                not (i + 1 < len(lines) and '|' in lines[i] and table_separator(lines[i + 1])):
            paragraph.append(lines[i].strip()); i += 1
        output.append('<p>' + inline(' '.join(paragraph)) + '</p>')
    return '\n'.join(output)


def render_page(name, lang, kind, source):
    label = '本站笔记 · 中文' if lang == 'zh' else 'Catalog note · English'
    back = '返回项目目录' if lang == 'zh' else 'Back to catalog'
    page_lang = 'zh-CN' if lang == 'zh' else 'en'
    return ('<!doctype html>\n<html lang="' + page_lang + '">\n<head>\n'
            '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>' + html.escape(name + ' · ' + label) + '</title>\n'
            '<link rel="stylesheet" href="../../../assets/style.css">\n'
            '</head>\n<body class="note-page">\n'
            '<header class="note-header"><a href="../../../?tab=' + kind + '">' + back + '</a>'
            '<div class="note-eyebrow">' + label + '</div><h1>' + html.escape(name) + '</h1></header>\n'
            '<main class="note-content">\n' + render_markdown(source) + '\n</main>\n'
            '</body>\n</html>\n')
