#!/usr/bin/env python3
"""Refresh OpenAlex metadata and generate a self-contained static homepage."""
import argparse
import copy
from datetime import datetime, timezone
from html import escape, unescape
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {'agents', 'recommendation', 'graphs', 'other'}
FIELDS = 'id,title,doi,publication_year,publication_date,type,authorships,primary_location,locations'


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


def short_id(value):
    return (value or '').rstrip('/').rsplit('/', 1)[-1]


def safe_url(value):
    if not isinstance(value, str):
        return ''
    parsed = urlparse(value)
    return value if parsed.scheme in ('http', 'https') and parsed.netloc else ''


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def get_json(url):
    for attempt in range(3):
        try:
            request = Request(url, headers={'User-Agent': 'KounianhuaDu-PersonalPage/1.0', 'Accept': 'application/json'})
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            retryable = not isinstance(error, HTTPError) or error.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == 2:
                # Do not include the request URL: it can contain an API key.
                code = f' HTTP {error.code}' if isinstance(error, HTTPError) else ''
                raise RuntimeError(f'OpenAlex request failed:{code} {type(error).__name__}') from None
            time.sleep(2 ** attempt)


def validate_works(works, author_id, minimum=1):
    if not isinstance(works, list) or len(works) < minimum:
        raise ValueError('Empty or unexpectedly small OpenAlex response')
    seen = set()
    for work in works:
        if not isinstance(work, dict) or not re.fullmatch(r'W\d+', short_id(work.get('id'))):
            raise ValueError('Invalid work identifier')
        if work['id'] in seen:
            raise ValueError('Duplicate work identifier in API response')
        seen.add(work['id'])
        if not isinstance(work.get('title'), str) or not work['title'].strip():
            raise ValueError('Missing work title')
        if not isinstance(work.get('publication_year'), int):
            raise ValueError('Missing publication year')
        authors = work.get('authorships')
        if not isinstance(authors, list) or not any(short_id((a.get('author') or {}).get('id')) == author_id for a in authors):
            raise ValueError('Unexpected author record; refusing to update')


def fetch_works(config):
    works, page, expected = [], 1, None
    while True:
        params = {'filter': f"author.id:{config['author_id']}", 'per-page': 100,
                  'page': page, 'select': FIELDS, 'sort': 'publication_date:desc'}
        if os.environ.get('OPENALEX_API_KEY'):
            params['api_key'] = os.environ['OPENALEX_API_KEY']
        data = get_json('https://api.openalex.org/works?' + urlencode(params))
        batch = data.get('results')
        count = data.get('meta', {}).get('count')
        if not isinstance(batch, list) or not isinstance(count, int):
            raise ValueError('Malformed API response')
        if expected is None:
            expected = count
        if count != expected:
            raise ValueError('API result count changed during pagination; retry next run')
        works.extend(batch)
        if len(works) >= expected:
            break
        if not batch or page >= 100:
            raise ValueError('Incomplete API pagination')
        page += 1
    if len(works) != expected:
        raise ValueError('Incomplete API result count')
    validate_works(works, config['author_id'], config.get('minimum_result_count', 1))
    # Do not keep affiliations or other unnecessary author metadata in the repository.
    for work in works:
        work['authorships'] = [{'author': a['author'], 'raw_author_name': a.get('raw_author_name')} for a in work['authorships']]
    return works


def identities(work):
    result = {'id:' + short_id(work.get('id')), 'title:' + norm(work['title'])}
    links = [work.get('doi')]
    for location in [work.get('primary_location') or {}] + (work.get('locations') or []):
        links.extend([location.get('doi'), location.get('landing_page_url'), location.get('pdf_url')])
    for link in filter(None, links):
        if 'doi.org/' in link:
            result.add('doi:' + link.split('doi.org/', 1)[1].lower())
        match = re.search(r'(?:arxiv\.(?:org/(?:abs|pdf)/)|arxiv\.)(\d{4}\.\d{4,5})', link, re.I)
        if match:
            result.add('arxiv:' + match[1])
    return result


def is_published(work):
    location = work.get('primary_location') or {}
    source = location.get('source') or {}
    return source.get('type') in ('journal', 'conference', 'book series') and (
        location.get('is_published') is True or work.get('type') in ('article', 'conference-paper', 'book-chapter'))


def venue_name(work):
    location = work.get('primary_location') or {}
    source = location.get('source') or {}
    if not is_published(work):
        return 'Preprint' if work.get('type') == 'preprint' or source.get('type') == 'repository' else 'Publication'
    name = unescape(location.get('raw_source_name') or source.get('display_name') or 'Publication')
    low = name.casefold()
    doi = (work.get('doi') or '').casefold()
    for token, label in [('findings-emnlp', 'EMNLP Findings'), ('findings-naacl', 'NAACL Findings'),
                         ('findings-acl', 'ACL Findings'), ('.emnlp-main.', 'EMNLP'),
                         ('.acl-long.', 'ACL Main')]:
        if token in doi:
            return label
    if 'findings' in low:
        if 'emnlp' in low or 'empirical methods' in low:
            return 'EMNLP Findings'
        if 'naacl' in low or 'north american' in low:
            return 'NAACL Findings'
        if re.search(r'\bacl\b', low):
            return 'ACL Findings'
        return name
    if 'empirical methods in natural language processing' in low:
        return 'EMNLP'
    if 'annual meeting of the association for computational linguistics' in low:
        return 'ACL Main'
    for term, label in [('neural information processing', 'NeurIPS'), ('neurips', 'NeurIPS'),
                        ('sigkdd', 'KDD'), ('knowledge discovery', 'KDD'),
                        ('information and knowledge management', 'CIKM'),
                        ('web conference', 'WWW'), ('world wide web', 'WWW'),
                        ('transactions on information systems', 'TOIS')]:
        if term in low:
            return label
    return source.get('display_name') or name


def category_for(title):
    title = title.casefold()
    if any(word in title for word in ('recommendation', 'recommender', 'knowledge tracing', 'cognitive diagnosis')):
        return 'recommendation'
    if any(word in title for word in ('agent', 'code', 'tool', 'reasoning', 'personalization', 'language model', 'skill')):
        return 'agents'
    if any(word in title for word in ('graph', 'tabular', 'relational database')):
        return 'graphs'
    return 'other'


def normalize_work(work):
    location = work.get('primary_location') or {}
    authors = [a.get('raw_author_name') or (a.get('author') or {}).get('display_name') or 'Unknown author'
               for a in work['authorships']]
    url = safe_url(work.get('doi')) or safe_url(location.get('landing_page_url')) or safe_url(work['id'])
    return {'id': short_id(work['id']), 'title': unescape(work['title']), 'authors': authors,
            'year': work['publication_year'], 'date': work.get('publication_date') or '',
            'venue': venue_name(work), 'url': url, 'published': is_published(work),
            'category': category_for(work['title']), 'openalex_ids': [short_id(work['id'])]}


def merge_publications(works, manual, config):
    ids = [entry['id'] for entry in manual]
    if len(set(ids)) != len(ids):
        raise ValueError('Curated IDs must be unique')
    alias_owner = {}
    for item in manual:
        for identifier in item.get('openalex_ids', []):
            if identifier in alias_owner:
                raise ValueError('An OpenAlex ID belongs to multiple curated entries')
            alias_owner[identifier] = item['id']
    excluded = set(config.get('excluded_openalex_ids', []))
    groups = []
    for work in works:
        if short_id(work['id']) in excluded:
            continue
        keys = identities(work)
        owner = alias_owner.get(short_id(work['id']))
        if owner:
            keys.add('manual:' + owner)
        matching = [group for group in groups if group['keys'] & keys]
        merged = {'keys': set(keys), 'works': [work]}
        for group in matching:
            merged['keys'].update(group['keys'])
            merged['works'].extend(group['works'])
            groups.remove(group)
        groups.append(merged)
    publications = []
    used = set()
    for group in groups:
        versions = sorted(group['works'], key=lambda w: (is_published(w), w.get('publication_date') or '', w['id']), reverse=True)
        record = normalize_work(versions[0])
        record['openalex_ids'] = sorted(short_id(w['id']) for w in versions)
        matches = [m for m in manual if ('manual:' + m['id']) in group['keys'] or ('title:' + norm(m['title'])) in group['keys']]
        if len(matches) > 1:
            raise ValueError('Ambiguous curated mapping; fix aliases before publishing')
        if matches:
            item = matches[0]
            used.add(item['id'])
            record.update(id=item['id'], category=item.get('category', record['category']))
            if item.get('note'):
                record['note'] = item['note']
            if not record['published'] and item.get('venue'):
                # A preprint index must not downgrade a curated acceptance/status.
                record['venue'] = item['venue']
                record['year'] = item.get('year', record['year']) if str(item.get('year', '')).isdigit() else record['year']
            record.update(item.get('overrides', {}))
        publications.append(record)
    for item in manual:
        if item['id'] not in used:
            record = copy.deepcopy(item)
            record.update(record.pop('overrides', {}))
            publications.append(record)
    for record in publications:
        if record.get('category') not in CATEGORIES:
            raise ValueError('Invalid publication category')
        if not record.get('title') or not isinstance(record.get('authors'), list):
            raise ValueError('Invalid curated publication')
        record['url'] = safe_url(record.get('url'))
    return sorted(publications, key=lambda p: (int(p['year']) if str(p.get('year', '')).isdigit() else 9999,
                                              p.get('date', ''), p['title'].casefold()), reverse=True)


def paper_link(url):
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noreferrer">Paper</a>' if safe_url(url) else ''


def render_publication(record, name):
    authors = ', '.join(f'<strong>{escape(a)}</strong>' if norm(a.rstrip('*')) == norm(name) else escape(a) for a in record['authors'])
    venue = escape(str(record.get('venue', '')))
    note = f' · {escape(record["note"])}' if record.get('note') else ''
    return (f'          <article data-category="{escape(record["category"])}" data-publication-id="{escape(record["id"])}">'
            f'<time>{escape(str(record.get("year", "")))}</time><div><h3>{escape(record["title"])}</h3>'
            f'<p>{authors}. <span>{venue}{note}</span></p>{paper_link(record["url"])}</div></article>')


def render_site(template, publications, config, checked_at):
    by_id = {p['id']: p for p in publications}

    def update_card(match):
        card = match[0]
        key = re.search(r'data-publication="([^"]+)"', card)[1]
        record = by_id.get(key)
        if not record:
            return card
        card = re.sub(r'(<p class="paper-title">).*?(</p>)', lambda m: m[1] + escape(record['title']) + m[2], card, count=1, flags=re.S)
        if record.get('venue'):
            venue = str(record['venue'])
            preliminary = venue.casefold() in ('preprint', 'in submission', 'in progress', 'publication')
            label = venue if preliminary else f'{venue} {record.get("year", "")}'.strip()
            tag = 'preprint' if preliminary else 'conference'
            card = re.sub(r'<span class="tag [^"]+">.*?</span>', lambda _: f'<span class="tag {tag}">{escape(label)}</span>', card, count=1)
        if record.get('url'):
            replacement = paper_link(record['url'])
            if re.search(r'<a [^>]*>Paper</a>', card):
                card = re.sub(r'<a [^>]*>Paper</a>', lambda _: replacement, card, count=1)
            elif '<div class="inline-links">' in card:
                card = card.replace('<div class="inline-links">', '<div class="inline-links">' + replacement, 1)
            else:
                card = card.replace('</article>', f'  <div class="inline-links">{replacement}</div>\n        </article>')
        return card

    html = re.sub(r'<article\b[^>]*data-publication="[^"]+"[^>]*>.*?</article>', update_card, template, flags=re.S)
    if checked_at:
        status = 'Last successful OpenAlex sync: ' + checked_at.replace('T', ' ').replace('+00:00', ' UTC')
    else:
        status = 'Curated publication list; awaiting first successful OpenAlex sync'
    html = html.replace('{{PUBLICATIONS}}', '\n'.join(render_publication(p, config['author_name']) for p in publications))
    html = html.replace('{{SCHOLAR_URL}}', escape(config['scholar_url'], quote=True)).replace('{{SYNC_STATUS}}', escape(status))
    if re.search(r'\{\{[A-Z_]+\}\}', html):
        raise ValueError('Unresolved template placeholder')
    return html


def build(root=ROOT, refresh=False):
    config = read_json(root / 'data/config.json')
    manual = read_json(root / 'data/manual-publications.json')
    template = (root / 'templates/index.html').read_text(encoding='utf-8')
    cache_path = root / 'data/openalex-cache.json'
    cache = read_json(cache_path, {'author_id': config['author_id'], 'checked_at': None, 'works': []})
    if cache['author_id'] != config['author_id']:
        raise ValueError('Cached author ID does not match config')
    if cache['works']:
        validate_works(cache['works'], config['author_id'])
    # Build the fallback first; malformed local edits should fail visibly.
    publications = merge_publications(cache['works'], manual, config)
    html = render_site(template, publications, config, cache.get('checked_at'))
    status = 'Using saved snapshot (offline mode)'
    if refresh:
        try:
            works = fetch_works(config)
            if cache['works'] and len(works) < len(cache['works']) * 0.7:
                raise ValueError('Result count dropped by more than 30%; retaining last good snapshot')
            candidate = {'author_id': config['author_id'], 'checked_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(), 'works': works}
            new_publications = merge_publications(works, manual, config)
            new_html = render_site(template, new_publications, config, candidate['checked_at'])
            cache, publications, html = candidate, new_publications, new_html
            atomic_write(cache_path, json_text(cache))
            status = f'OpenAlex sync succeeded: {len(works)} source records'
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            status = f'OpenAlex sync unavailable ({type(error).__name__}); kept last successful snapshot and curated entries'
            print('::warning::' + status, file=sys.stderr)
    atomic_write(root / 'index.html', html)
    atomic_write(root / 'data/publications.json', json_text({'checked_at': cache.get('checked_at'), 'publications': publications}))
    message = f'{status}. Published {len(publications)} unique/curated entries. Last successful sync: {cache.get("checked_at") or "not yet"}.'
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(message + '\n')
    return publications


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--refresh', action='store_true', help='Fetch all works; retain the cache if the API fails')
    mode.add_argument('--offline', action='store_true', help='Build from the committed snapshot without network access (default)')
    args = parser.parse_args()
    build(refresh=args.refresh)
