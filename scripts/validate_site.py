#!/usr/bin/env python3
"""Check generated static assets without requiring a browser or web server."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.publication_ids = []
        self.categories = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if 'data-publication-id' in attrs:
            self.publication_ids.append(attrs['data-publication-id'])
            self.categories.append(attrs.get('data-category'))
        for attr in ('src', 'href'):
            if attrs.get(attr):
                self.links.append(attrs[attr])


def validate(root=ROOT):
    html = (root / 'index.html').read_text(encoding='utf-8')
    template = (root / 'templates/index.html').read_text(encoding='utf-8')
    assert '{{' not in html, 'Unresolved template placeholder'
    page = PageParser()
    page.feed(html)
    assert len(page.ids) == len(set(page.ids)), 'Duplicate DOM IDs'
    assert len(page.publication_ids) == len(set(page.publication_ids)), 'Duplicate publication IDs'
    assert set(page.categories) <= {'agents', 'recommendation', 'graphs', 'other'}
    manual = json.loads((root / 'data/manual-publications.json').read_text())
    assert {p['id'] for p in manual} <= set(page.publication_ids), 'A curated entry was lost'
    data = json.loads((root / 'data/publications.json').read_text())
    assert len(data['publications']) == len(page.publication_ids)
    for link in page.links:
        parsed = urlparse(link)
        if parsed.scheme:
            assert parsed.scheme in {'http', 'https', 'mailto'}, f'Unsafe scheme: {parsed.scheme}'
        elif link.startswith('#'):
            assert link[1:] in page.ids, f'Missing anchor: {link}'
        elif parsed.path:
            path = (root / unquote(parsed.path)).resolve()
            assert path.is_relative_to(root.resolve()), f'Asset outside root: {link}'
            assert path.is_file(), f'Missing asset: {link}'
    cache_card = r'<article class="project-card reveal" id="cacheopd">.*?</article>'
    assert re.search(cache_card, html, re.S)[0] == re.search(cache_card, template, re.S)[0]
    original_cards = re.findall(r'<article\b[^>]*data-publication="[^"]+"[^>]*>.*?</article>', template, re.S)
    for card in original_cards:
        key = re.search(r'data-publication="([^"]+)"', card)[1]
        generated = re.search(r'<article\b[^>]*data-publication="' + re.escape(key) + r'"[^>]*>.*?</article>', html, re.S)[0]
        paragraphs = re.findall(r'<p>(.*?)</p>', card, re.S)
        assert all(f'<p>{paragraph}</p>' in generated for paragraph in paragraphs), f'Changed research narrative: {key}'
    assert '3iWnom0AAAAJ' in html
    print(f'Static-site checks passed: {len(page.publication_ids)} publications, {len(page.links)} links/assets; research narratives preserved.')


if __name__ == '__main__':
    validate()
