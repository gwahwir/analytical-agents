# News Scraper Design — US-Iran Conflict Articles

**Date:** 2026-03-24
**Status:** Draft

## Purpose

A standalone utility script that scrapes Google News RSS for articles about the US-Iran conflict and saves up to 50 full-text articles as `.txt` files in `sample_articles/`. These files are then consumed by `ingest_articles.py` to feed the Knowledge Graph agent.

## Script

`scrape_articles.py` at the repo root, alongside `ingest_articles.py`.

## Flow

1. Build the Google News RSS URL using the query and locale params:
   `https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en`
   (spaces encoded as `+`, e.g. `US+Iran+conflict`)
2. Fetch and parse the RSS feed with `feedparser` — up to ~100 entries available
3. Take the first `--max` entries from the feed (default 50); `--max` caps the number of feed entries attempted, not the number successfully saved. If the feed returns fewer entries than `--max`, process all available entries without error.
4. Create `sample_articles/` if it does not exist
5. For each entry, use `newspaper4k` to download and parse the full article text, with a 10-second per-article timeout (pass `request_timeout=10` to the `Article` constructor)
6. Add a 0.5s delay between article fetches to avoid hammering hosts
7. Save to `sample_articles/{i:03d}_{slug}.txt` (1-based index)
8. Skip and warn on fetch failures (network errors, timeout, paywall, parse error) — continue to next article

## Output File Format

Each `.txt` file is written with `encoding="utf-8"` and has a metadata header followed by the article body:

```
Title: Iran warns US over...
Source: Reuters
Published: Mon, 24 Mar 2026 12:00:00 GMT
URL: https://...
---
[full article text]
```

### Filename Slug Rules

- Start with `{i:03d}_` where `i` is 1-based (e.g. `001_`, `002_`)
- Take the article title, lowercase it
- Replace any run of non-alphanumeric characters with a single hyphen
- Strip leading and trailing hyphens
- Truncate the slug portion (excluding the `{i:03d}_` prefix and `.txt` extension) to 60 characters, then strip any trailing hyphens from the truncated slug
- Final filename: `{i:03d}_{slug}.txt`
- Example: `001_iran-us-tensions-escalate-after-strike.txt`

## CLI Interface

```
python scrape_articles.py [--query "US Iran conflict"] [--max 50]
```

| Flag | Default | Description |
|---|---|---|
| `--query` | `"US Iran conflict"` | Search query for Google News |
| `--max` | `50` | Max number of RSS entries to attempt (not a guarantee of saved count) |

## Dependencies

Add to `requirements.txt`:
- `feedparser>=6.0` — RSS feed parsing
- `newspaper4k>=0.9` — maintained fork of newspaper3k for full-text extraction

## Error Handling

- Per-article failures (network, timeout, paywall, parse error) are caught, logged as warnings, and skipped
- Script exits with code 0 if at least one article was saved; code 1 if none were saved. Partial failure (some saved, some skipped) exits with code 0 — callers should read the summary line for accurate counts.
- Summary printed at end: `Done. X saved, Y skipped.`

## Testing

Manual: run the script, verify `sample_articles/` contains `.txt` files with correct UTF-8 format, then run `ingest_articles.py` to confirm the pipeline works end-to-end.
