#!/usr/bin/env python3
"""Build the static site data from Sheet1 and public article metadata."""

from __future__ import annotations

import concurrent.futures
import difflib
import html
import json
import re
import urllib.parse
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import requests


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "queries_updated.xlsx"
OUTPUT = ROOT / "data" / "papers.json"
CACHE = ROOT / "scripts" / "metadata-cache.json"
OVERRIDES = ROOT / "scripts" / "overrides.json"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s?#&]+", re.I)
PII_RE = re.compile(r"/pii/(S[0-9A-Z]+)", re.I)
USER_AGENT = "ChemicalEvidenceAtlas/1.0 (academic bibliography; metadata contact: research@example.org)"


def load_groups():
    with zipfile.ZipFile(WORKBOOK) as book:
        shared_root = ET.fromstring(book.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.findall(".//m:t", NS)) for si in shared_root]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet2.xml"))
    groups = []
    for row in sheet.findall(".//m:sheetData/m:row", NS):
        values = {}
        for cell in row.findall("m:c", NS):
            value = cell.find("m:v", NS)
            inline = cell.find("m:is", NS)
            raw = value.text if value is not None else "".join(t.text or "" for t in inline.findall(".//m:t", NS)) if inline is not None else ""
            if cell.get("t") == "s" and raw:
                raw = shared[int(raw)]
            values[re.sub(r"\d", "", cell.get("r", ""))] = raw or ""
        chemical = values.get("A", "").strip()
        link = values.get("C", "").strip()
        if chemical and chemical.lower() != "chemical":
            groups.append({"chemical": chemical, "papers": []})
        if link and link.lower() != "links":
            groups[-1]["papers"].append({"sourceRow": int(row.get("r")), "sourceUrl": link})
    return groups


def clean_text(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", str(value))
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def get_json(url, params=None):
    try:
        response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=20)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def get_html(url):
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=16)
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", ""):
            return ""
        return response.text[:1000000]
    except requests.RequestException:
        return ""


def meta_tags(page):
    from html.parser import HTMLParser

    class Meta(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = {}

        def handle_starttag(self, tag, attrs):
            if tag == "meta":
                props = dict(attrs)
                key = props.get("name") or props.get("property") or ""
                value = props.get("content") or ""
                if key and value:
                    self.values.setdefault(key.lower(), value)

    parser = Meta()
    parser.feed(page)
    return parser.values


def abstract_from_openalex(work):
    index = work.get("abstract_inverted_index") or {}
    if not index:
        return ""
    positions = [(i, word) for word, places in index.items() for i in places]
    return clean_text(" ".join(word for _, word in sorted(positions)))


def extract_doi(url):
    decoded = urllib.parse.unquote(url)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url if "://" in url else "https://" + url).query)
    for candidate in query.get("id", []):
        if candidate.lower().startswith("doi:") and len(candidate) > 4:
            decoded = candidate[4:]
            break
    match = DOI_RE.search(decoded)
    if not match:
        return ""
    doi = match.group(0).rstrip(".,;)")
    doi = re.sub(r"/(?:full|abstract|pdf|epdf)$", "", doi, flags=re.I)
    return doi.lower()


def canonical_url(source, doi):
    if doi:
        return "https://doi.org/" + doi
    parsed = urllib.parse.urlsplit(source if "://" in source else "https://" + source)
    host = parsed.netloc.lower()
    if host == "books.google.com":
        book_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
        return "https://books.google.com/books?id=" + urllib.parse.quote(book_id)
    if host == "upcommons.upc.edu":
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if host.endswith("sciencedirect.com") or host.endswith("tandfonline.com"):
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return source if source.startswith("http") else "https://" + source


def from_doi(doi):
    encoded = urllib.parse.quote(doi, safe="/")
    oa = get_json("https://api.openalex.org/works/https://doi.org/" + encoded)
    cr = get_json("https://api.crossref.org/works/" + encoded)
    cr = (cr or {}).get("message") or {}
    oa = oa or {}
    location = oa.get("primary_location") or {}
    source = location.get("source") or {}
    abstract = abstract_from_openalex(oa) or clean_text(cr.get("abstract"))
    if not abstract:
        europe = get_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search", {"query": "DOI:" + doi, "format": "json", "resultType": "core"}) or {}
        records = (europe.get("resultList") or {}).get("result") or []
        if records:
            abstract = clean_text(records[0].get("abstractText"))
    journal = clean_text(cr.get("container-title")) or clean_text(source.get("display_name"))
    title = clean_text(cr.get("title")) or clean_text(oa.get("title"))
    published = (cr.get("published") or cr.get("issued") or {}).get("date-parts") or []
    year = published[0][0] if published and published[0] else oa.get("publication_year")
    kind = cr.get("type") or oa.get("type") or "article"
    return {"title": title, "journal": journal, "abstract": abstract, "year": year, "type": kind, "doi": doi}


def from_book(url):
    book_id = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("id", [""])[0]
    info = (get_json("https://www.googleapis.com/books/v1/volumes/" + book_id) or {}).get("volumeInfo") or {}
    tags = meta_tags(get_html("https://books.google.com/books?id=" + book_id))
    return {"title": clean_text(info.get("title") or tags.get("og:title") or tags.get("title")), "journal": clean_text(info.get("publisher")) or "Google Books", "abstract": clean_text(info.get("description") or tags.get("description")), "year": (info.get("publishedDate") or "")[:4], "type": "book"}


def exact_openalex(title):
    works = (get_json("https://api.openalex.org/works", {"search": title, "per-page": 3}) or {}).get("results") or []
    target = re.sub(r"\W", "", title).lower()
    for work in works:
        candidate = re.sub(r"\W", "", work.get("title") or "").lower()
        if difflib.SequenceMatcher(None, target, candidate).ratio() >= .94:
            return work
    return {}


def from_library(url):
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    title = clean_text(params.get("atitle"))
    work = exact_openalex(title) if title else {}
    return {"title": title, "journal": clean_text(params.get("title")), "abstract": abstract_from_openalex(work), "year": clean_text(params.get("date")), "type": "journal-article", "doi": (work.get("doi") or "").removeprefix("https://doi.org/")}


def from_escholarship(url):
    item = url.rstrip("/").split("/")[-1]
    query = '{ item(id: "ark:/13030/qt' + item + '") { title journal abstract published type permalink } }'
    try:
        response = requests.post("https://escholarship.org/graphql", json={"query": query}, timeout=15)
        response.raise_for_status()
        data = (response.json().get("data") or {}).get("item") or {}
    except (requests.RequestException, ValueError):
        data = {}
    return {"title": clean_text(data.get("title")), "journal": clean_text(data.get("journal")) or "eScholarship", "abstract": clean_text(data.get("abstract")), "year": (data.get("published") or "")[:4], "type": data.get("type") or "resource"}


def from_page(url):
    page = get_html(url)
    tags = meta_tags(page) if page else {}
    doi = tags.get("citation_doi") or tags.get("dc.identifier.doi") or ""
    if doi:
        rich = from_doi(doi)
    else:
        rich = {}
    title = rich.get("title") or tags.get("citation_title") or tags.get("dc.title") or tags.get("og:title") or ""
    journal = rich.get("journal") or tags.get("citation_journal_title") or tags.get("dc.source") or ""
    abstract = rich.get("abstract") or tags.get("citation_abstract") or tags.get("dc.description") or tags.get("description") or tags.get("og:description") or ""
    year = rich.get("year") or (tags.get("citation_date") or tags.get("citation_publication_date") or "")[:4]
    return {"title": clean_text(title), "journal": clean_text(journal), "abstract": clean_text(abstract), "year": year, "type": rich.get("type") or "resource", "doi": doi}


def from_pii(url):
    match = PII_RE.search(url)
    if not match:
        return {}
    record = get_json("https://api.elsevier.com/content/article/pii/" + match.group(1)) or {}
    core = (record.get("full-text-retrieval-response") or {}).get("coredata") or {}
    doi = core.get("prism:doi") or ""
    rich = from_doi(doi) if doi else {}
    return {
        "title": rich.get("title") or clean_text(core.get("dc:title")),
        "journal": rich.get("journal") or clean_text(core.get("prism:publicationName")),
        "abstract": rich.get("abstract") or "",
        "year": rich.get("year") or (core.get("prism:coverDate") or "")[:4],
        "type": rich.get("type") or "journal-article",
        "doi": doi,
    }


def enrich(url):
    doi = extract_doi(url)
    if doi:
        result = from_doi(doi)
    elif PII_RE.search(url):
        result = from_pii(url)
    elif "catalyst.library.jhu.edu" in url:
        result = from_library(url)
    elif "books.google.com" in url:
        result = from_book(url)
    elif "escholarship.org/uc/item/" in url:
        result = from_escholarship(url)
    else:
        result = from_page(url)
    result["url"] = canonical_url(url, result.get("doi") or doi)
    return result


def main():
    groups = load_groups()
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    links = list(dict.fromkeys(p["sourceUrl"] for g in groups for p in g["papers"]))
    missing = [url for url in links if url not in cache]
    print(f"{len(groups)} chemicals, {sum(len(g['papers']) for g in groups)} links, {len(missing)} to fetch", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(enrich, url): url for url in missing}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            try:
                cache[url] = future.result()
            except Exception as error:
                cache[url] = {"title": "", "journal": "", "abstract": "", "year": "", "type": "resource", "url": canonical_url(url, ""), "error": str(error)}
            print(f"{len(cache)}/{len(links)} {cache[url].get('title','')[:80] or '[title missing]'}", flush=True)
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    for group in groups:
        for paper in group["papers"]:
            paper.update(cache[paper.pop("sourceUrl")])
            override = overrides.get(str(paper["sourceRow"])) or {}
            if override.get("doi"):
                paper.update(from_doi(override["doi"]))
                paper["url"] = canonical_url(paper["url"], override["doi"])
            paper.update(override)
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps({"groups": groups}, ensure_ascii=False, indent=2))
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
