import unittest
from test_sync import work, sync


class VenueTests(unittest.TestCase):
    def test_findings_doi_overrides_publisher_name(self):
        for slug, label in [('emnlp', 'EMNLP Findings'), ('acl', 'ACL Findings'), ('naacl', 'NAACL Findings')]:
            record = work(published=True)
            record['doi'] = f'https://doi.org/10.18653/v1/2025.findings-{slug}.355'
            record['primary_location']['raw_source_name'] = 'Findings of the Association for Computational Linguistics'
            self.assertEqual(sync.venue_name(record), label)

    def test_generic_findings_not_assumed_acl(self):
        record = work(published=True)
        name = 'Findings of the Association for Computational Linguistics'
        record['primary_location']['raw_source_name'] = name
        self.assertEqual(sync.venue_name(record), name)

    def test_emnlp_name_not_assumed_acl(self):
        record = work(published=True)
        record['primary_location']['raw_source_name'] = 'Findings of the Association for Computational Linguistics: EMNLP 2025'
        self.assertEqual(sync.venue_name(record), 'EMNLP Findings')


if __name__ == '__main__':
    unittest.main()
