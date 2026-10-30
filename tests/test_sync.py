import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_publications as sync

AUTHOR = 'A5074618552'
CONFIG = {'author_id': AUTHOR, 'author_name': 'Kounianhua Du', 'minimum_result_count': 1,
          'scholar_url': 'https://scholar.google.com/citations?user=3iWnom0AAAAJ'}


def work(identifier='W1', title='A paper', published=False, year=2025):
    return {'id': 'https://openalex.org/' + identifier, 'title': title, 'doi': None,
            'publication_year': year, 'publication_date': f'{year}-01-01',
            'type': 'conference-paper' if published else 'preprint',
            'authorships': [{'author': {'id': 'https://openalex.org/' + AUTHOR, 'display_name': 'Kounianhua Du'}, 'raw_author_name': 'Kounianhua Du'}],
            'primary_location': {'source': {'type': 'conference' if published else 'repository', 'display_name': 'ACL Main' if published else 'arXiv'},
                                 'is_published': published}, 'locations': []}


def curated(identifier='paper', ids=None):
    return {'id': identifier, 'title': 'A paper', 'authors': ['Kounianhua Du'], 'year': 2025,
            'venue': 'In submission', 'url': 'https://example.org/paper', 'category': 'agents',
            'openalex_ids': ids or [], 'overrides': {}}


class SyncTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(sync.os.environ, {'GITHUB_STEP_SUMMARY': ''})
        environment.start()
        self.addCleanup(environment.stop)

    def test_author_validation(self):
        sync.validate_works([work()], AUTHOR)
        bad = work()
        bad['authorships'][0]['author']['id'] = 'https://openalex.org/A2'
        with self.assertRaises(ValueError):
            sync.validate_works([bad], AUTHOR)

    def test_empty_and_duplicate_responses_rejected(self):
        for records in ([], [work(), work()]):
            with self.assertRaises(ValueError):
                sync.validate_works(records, AUTHOR)

    def test_published_version_beats_newer_preprint(self):
        result = sync.merge_publications([work('W1', year=2026), work('W2', published=True)], [], CONFIG)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 'W2')
        self.assertEqual(result[0]['year'], 2025)

    def test_explicit_aliases_merge_changed_titles(self):
        result = sync.merge_publications([work('W1', 'Old title'), work('W2', 'New title', True)], [curated(ids=['W1', 'W2'])], CONFIG)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], 'New title')
        self.assertEqual(result[0]['id'], 'paper')

    def test_arxiv_locations_merge_changed_titles(self):
        first, second = work('W1', 'Old'), work('W2', 'New', True)
        first['doi'] = 'https://doi.org/10.48550/arxiv.2401.12345'
        second['locations'] = [{'landing_page_url': 'https://arxiv.org/abs/2401.12345v2'}]
        self.assertEqual(len(sync.merge_publications([first, second], [], CONFIG)), 1)

    def test_curated_unindexed_entries_survive(self):
        record = curated('unindexed')
        record['title'] = 'An unindexed manuscript'
        result = sync.merge_publications([work()], [record], CONFIG)
        self.assertIn('unindexed', [p['id'] for p in result])

    def test_manual_overrides_always_win(self):
        record = curated(ids=['W1'])
        record['overrides'] = {'title': 'Correct title', 'authors': ['Kounianhua Du*'], 'year': 2026, 'venue': 'Manual venue'}
        result = sync.merge_publications([work(published=True)], [record], CONFIG)[0]
        for field, value in record['overrides'].items():
            self.assertEqual(result[field], value)

    def test_preprint_does_not_downgrade_manual_acceptance(self):
        record = curated(ids=['W1'])
        record['venue'] = 'ACL Main'
        record['year'] = 2026
        result = sync.merge_publications([work()], [record], CONFIG)[0]
        self.assertEqual((result['venue'], result['year']), ('ACL Main', 2026))

    def test_excluded_misattributed_work(self):
        config = dict(CONFIG, excluded_openalex_ids=['W1'])
        self.assertEqual(sync.merge_publications([work()], [], config), [])

    def test_ambiguous_aliases_rejected(self):
        with self.assertRaises(ValueError):
            sync.merge_publications([work()], [curated('one', ['W1']), curated('two', ['W1'])], CONFIG)

    def test_full_pagination(self):
        records = [work(f'W{i + 1}', f'Paper {i}') for i in range(101)]
        pages = [{'meta': {'count': 101}, 'results': records[:100]}, {'meta': {'count': 101}, 'results': records[100:]}]
        with patch.object(sync, 'get_json', side_effect=pages) as fetch:
            self.assertEqual(len(sync.fetch_works(CONFIG)), 101)
            self.assertEqual(fetch.call_count, 2)

    def test_incomplete_pagination_rejected(self):
        pages = [{'meta': {'count': 2}, 'results': [work()]}, {'meta': {'count': 2}, 'results': []}]
        with patch.object(sync, 'get_json', side_effect=pages):
            with self.assertRaises(ValueError):
                sync.fetch_works(CONFIG)

    def test_request_errors_do_not_leak_key(self):
        url = 'https://api.openalex.org/works?api_key=SECRET'
        error = HTTPError(url, 401, 'Denied', {}, None)
        with patch.object(sync, 'urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                sync.get_json(url)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_html_escaping_and_unsafe_url(self):
        record = curated()
        record['title'] = '<script>alert(1)</script>'
        record['url'] = 'javascript:alert(1)'
        html = sync.render_publication(record, CONFIG['author_name'])
        self.assertNotIn('<script>', html)
        self.assertNotIn('javascript:', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('<strong>Kounianhua Du</strong>', html)

    def test_linked_card_narrative_and_other_links_unchanged(self):
        record = curated()
        template = '<article data-publication="paper"><span class="tag preprint">Old</span><p class="paper-title">Old title</p><p>Keep this description.</p><div class="inline-links"><a href="https://old.example">Paper</a><a href="https://model.example">Model weights</a></div></article>{{PUBLICATIONS}}{{SCHOLAR_URL}}{{SYNC_STATUS}}'
        html = sync.render_site(template, [record], CONFIG, None)
        self.assertIn('<p>Keep this description.</p>', html)
        self.assertIn('href="https://model.example"', html)
        self.assertIn('href="https://example.org/paper"', html)
        self.assertNotIn('old.example', html)

    def prepare_root(self, root, records):
        (root / 'data').mkdir()
        (root / 'templates').mkdir()
        for name, data in [('config', CONFIG), ('manual-publications', [curated()]),
                           ('openalex-cache', {'author_id': AUTHOR, 'checked_at': '2026-01-01T00:00:00+00:00', 'works': records})]:
            (root / f'data/{name}.json').write_text(json.dumps(data))
        (root / 'templates/index.html').write_text('{{PUBLICATIONS}}{{SCHOLAR_URL}}{{SYNC_STATUS}}')

    def test_failed_refresh_keeps_cache_and_rendered_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_root(root, [work()])
            sync.build(root)
            cache = (root / 'data/openalex-cache.json').read_bytes()
            html = (root / 'index.html').read_bytes()
            with patch.object(sync, 'fetch_works', side_effect=RuntimeError('offline')):
                sync.build(root, refresh=True)
            self.assertEqual(cache, (root / 'data/openalex-cache.json').read_bytes())
            self.assertEqual(html, (root / 'index.html').read_bytes())

    def test_large_result_drop_keeps_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_root(root, [work(f'W{i}', f'Paper {i}') for i in range(10)])
            cache = (root / 'data/openalex-cache.json').read_bytes()
            with patch.object(sync, 'fetch_works', return_value=[work()]):
                sync.build(root, refresh=True)
            self.assertEqual(cache, (root / 'data/openalex-cache.json').read_bytes())

    def test_successful_refresh_and_offline_rebuild_are_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prepare_root(root, [work()])
            with patch.object(sync, 'fetch_works', return_value=[work(published=True)]):
                sync.build(root, refresh=True)
            html = (root / 'index.html').read_bytes()
            sync.build(root)
            self.assertEqual(html, (root / 'index.html').read_bytes())
            cache = json.loads((root / 'data/openalex-cache.json').read_text())
            self.assertTrue(cache['works'][0]['primary_location']['is_published'])


if __name__ == '__main__':
    unittest.main()
