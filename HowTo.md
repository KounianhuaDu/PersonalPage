The published artifact contains only `index.html`, `styles.css`, `script.js`, `assets/` and `.nojekyll`. It does not publish workflow files, scripts, source templates, tests or the metadata cache.

## First deployment

1. Unzip the package and put the **contents** of `kounianhua-du-website/` at the repository root, not inside another directory. Include the hidden `.github/` directory. Keep any existing repository-specific files such as `CNAME`; do not delete unrelated files. If there is an older Pages workflow, disable it to avoid two competing deployments.
2. Commit/push the files to the default branch (`main` or `master`). If your branch has another name, add it to the `push.branches` list in `.github/workflows/publish.yml`.
3. In the GitHub repository, open **Settings → Pages → Build and deployment → Source → GitHub Actions**.
4. Open **Settings → Actions → General**, enable Actions if necessary and allow read/write workflow permissions. The workflow needs permission to commit `index.html` and the cached metadata. If branch protection prevents bot pushes, adjust the repository rules for this workflow; it intentionally stops on a failed push rather than silently publishing inconsistent state.
5. Open **Actions → Sync publications and deploy Pages → Run workflow** on the default branch. An initial automatic run may fail if Pages had not yet been enabled; rerun after step 3.
6. After deployment succeeds, the normal project URL is **https://kounianhuadu.github.io/PersonalPage/**. A configured custom domain can change this URL.

The workflow checks for updates daily at **01:23 UTC / 09:23 Beijing time**, on pushes, and when manually triggered. GitHub schedules are best-effort and may be delayed. Public repositories can have scheduled workflows automatically disabled after 60 days without repository activity; re-enable the workflow if GitHub disables it.

**This package configures automation but does not itself upload files or enable settings in your GitHub account.**

## Metadata source and API key

Google Scholar is a profile link, **not the scraped data source**. Publications are fetched server-side in GitHub Actions from OpenAlex author **A5074618552**. Visitors load only static HTML, CSS and JavaScript: there are no browser API calls, CORS requirements or exposed API keys.

The included snapshot was fetched during preparation. Author name, affiliation and known works were checked, but any scholarly database can contain missing papers or attribution errors. OpenAlex and Scholar counts and updates can differ. Citation counts are intentionally not displayed as Scholar statistics.

Anonymous OpenAlex requests currently work but share an IP-based allowance. For reliable scheduled runs, obtain your own key at https://openalex.org/settings/api and add it to **Settings → Secrets and variables → Actions → New repository secret**, named **OPENALEX_API_KEY**. This is optional while anonymous requests remain available; it may become necessary if the service limits or requires authentication. Never put the key in JSON files, the HTML, or a public commit.

## What updates automatically

- New indexed papers; title, author list, publication year, venue and paper link.
- Existing selected-research cards linked with `data-publication="..."`: paper title, venue/status and paper URL. The project heading, description, order, model links and research narrative remain manually maintained.
- Preprint and published versions are grouped by exact normalized title, DOI, arXiv ID or explicit known version IDs. Published journal/conference versions are preferred. Different-title versions cannot always be identified automatically; add their IDs to the same curated entry when needed.
- The unlinked CacheOPD card, About, Updates, CV, experience, project descriptions and research claims are not rewritten. In-submission status is kept until a published record is available. Database indexing alone is not treated as acceptance.
- Manually listed but unindexed works remain visible. ELCoRec's equal-contribution author markers are explicitly preserved. The CodeGRAG research honor is preserved as a note.
- Previously accepted/manual venue labels are not downgraded just because only a preprint is indexed. Specific field corrections in `overrides` always win.

## Editing and corrections

**Edit `templates/index.html`, not generated `index.html`, for design and narrative changes.** `index.html` is regenerated on the next workflow run. Keep `{{PUBLICATIONS}}`, `{{SCHOLAR_URL}}` and `{{SYNC_STATUS}}` placeholders in the template.

`data/manual-publications.json` stores the original curated entries and known version mappings. Each entry has a stable `id`, `openalex_ids`, fallback metadata and an `overrides` dictionary. Fallback fields apply when the paper is absent from OpenAlex; ordinary indexed fields update automatically. To force a correction, add only the fields that must be locked to `overrides`, for example:

```json
"overrides": {
  "title": "A manually corrected title",
  "venue": "ACL Main",
  "year": 2026
}
```

You can also override `authors` (an array of names), `url` or `category`. Allowed categories are `agents`, `recommendation`, `graphs`, `other`. Existing curated classifications remain fixed; classification for new papers is a keyword heuristic, not an authoritative research taxonomy.

For a new manually listed paper, add a complete entry following existing entries. Use an empty `openalex_ids` list if it is not indexed. Later add its OpenAlex `W...` ID. All known preprint/published versions of one paper belong in the same list. For a research card, use the same entry `id` in its `data-publication` attribute. Add unwanted/misattributed work IDs to `excluded_openalex_ids` in `data/config.json`; this excludes fetched records but does not delete intentionally curated entries.

`data/openalex-cache.json` is the last successful source snapshot. `data/publications.json` and `index.html` are generated. Do not edit these to make permanent corrections. The cache is committed so a future failed request does not remove previous results.

## Reliability and failure behavior

Every fetched work must contain the configured author ID. Requests use timeouts, three attempts for transient errors, pagination checks, non-empty result validation and a minimum-result threshold. An unexpected result-count drop of more than 30% is rejected. API failure/invalid response keeps the last successful snapshot and curated papers; the page continues to show its actual last successful sync time. GitHub Actions emits a warning and records fallback status in its run summary. This fallback run can still deploy successfully: inspect the summary to tell fresh data from a cached build.

Invalid local JSON, ambiguous aliases, broken templates or failed integrity checks fail the workflow instead of publishing. If a legitimate database merge causes the count-drop guard to trigger, inspect the source data before deliberately replacing the saved snapshot or adjusting the guard.

For detailed authorship errors or title-changing versions, human review remains necessary. There is no promise of exact Scholar synchronization.

## Local use and tests

Requires **Python 3.11+**, using only the standard library; no packages need installing.

```bash
python -m unittest discover -s tests -v
python scripts/sync_publications.py --offline
python scripts/validate_site.py
python scripts/sync_publications.py --refresh
```

Run commands from the website directory. The default mode is offline. Open `index.html` directly in a browser; all shipped assets use relative paths and work under `/PersonalPage/`. For a local static server, run `python -m http.server 8000` and visit http://localhost:8000. No Node build or backend is needed.

