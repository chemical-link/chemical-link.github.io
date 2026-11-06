# Chemical Evidence Atlas

A static, GitHub Pages-ready library of the references in `queries_updated.xlsx` → `Sheet1`. The first link on a chemical's row and every following link until the next chemical belong to that chemical. The site preserves all 59 spreadsheet references across 19 chemicals.

Live site: https://chemical-link.github.io/

## View locally

From this directory, run:

```sh
python -m http.server 8000
```

Then open `http://localhost:8000`. The site uses plain HTML, CSS, and JavaScript, with no build step or runtime API keys. Opening `index.html` directly as a file will not load `data/papers.json` in most browsers.

## Publish with GitHub Pages

Push this directory to a GitHub repository. In the repository's **Settings → Pages**, choose **Deploy from a branch**, select the branch you pushed (usually `main`), and choose **/(root)** as the folder. GitHub will publish `index.html` and the `data` directory together.

## Update the references

After editing the workbook, run:

```sh
python -m pip install requests
python scripts/build_data.py
```

The script reads `Sheet1`, retrieves public metadata from Crossref, OpenAlex, Europe PMC, publishers, and other source records, then writes `data/papers.json`. `scripts/overrides.json` holds verified fixes for sources that do not expose usable metadata. Review that file if you rearrange spreadsheet rows. `scripts/metadata-cache.json` is a local retrieval cache and is ignored by Git.

Some workbook links are reports, books, a preprint, or a subscription database record. Their source type is shown on the site. When a source does not publish a verifiable abstract, the page says so instead of inventing one. The chemical groupings come from the workbook and do not imply that every source specifically studies that chemical.
