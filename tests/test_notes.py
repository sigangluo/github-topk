"""Checks for safe note rendering and the published project-to-note link."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import catalog
from common import read_json
from note_pages import render_markdown


class NotePageTests(unittest.TestCase):
    def test_both_language_trees_link_to_the_same_project(self):
        source = {
            'ai': {'taxonomy': [{'key': 'learn', 'subs': [{'key': 'course'}]}],
                   'projects': {'owner/repo': {'category': 'course'}}},
            'fullstack': {'taxonomy': [], 'projects': {}},
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(catalog, 'ROOT', Path(directory)):
            catalog.sync_dirs(source)
            for lang in ('zh', 'en'):
                path = Path(directory) / 'notes' / lang / 'ai/learn/course/owner__repo.md'
                path.write_text('# Note', encoding='utf-8')
            catalog.check_dirs(source)
            links = catalog.note_files(source)
            self.assertEqual({lang for name, lang in links if name == 'owner/repo'}, {'zh', 'en'})
            self.assertEqual(links['owner/repo', 'en'][1].as_posix(),
                             'notes/en/ai/owner__repo.html')

    def test_markdown_table_and_untrusted_html(self):
        rendered = render_markdown(
            '# Course\n\n| Lesson | Topic |\n| --- | --- |\n| 01 | Introduction |\n\n'
            '<script>alert(1)</script> [bad](javascript:alert(1)) [source](https://example.org)')
        self.assertIn('<h2>Course</h2>', rendered)
        self.assertIn('<th scope="col">Lesson</th>', rendered)
        self.assertIn('<td>Introduction</td>', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertIn('href="https://example.org"', rendered)

    def test_existing_chinese_note_is_linked_to_its_generated_page(self):
        name = 'microsoft/generative-ai-for-beginners'
        site = read_json(catalog.SITE_PATH)
        project = next(project for project in site['views']['ai']['projects'] if project['name'] == name)
        self.assertEqual(project['notes'], {
            'zh': 'notes/zh/ai/microsoft__generative-ai-for-beginners.html'})
        catalog.check_note_pages(catalog.sources())


if __name__ == '__main__':
    unittest.main()
