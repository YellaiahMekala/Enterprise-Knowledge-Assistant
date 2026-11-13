# ADR-039: Web fallback follows links one level deep (no crawling)

| | |
|---|---|
| Status | Accepted (task P16-A, built 2026-11-13) |
| Date | 2026-11-13 |
| Decision owner | Maintainer |
| Review trigger | A need for pages more than one link away; an allowed site that serves its content from another host; a site that complains about the fetch rate; a search engine as the source of pages (a separate decision). |
| Related | ADR-030, FR-37, FR-58, NFR-04 |

## Context
ADR-030 fetches only the entry URLs the owner configured. A tutorial or reference index page usually holds a table of contents, and the answer sits on a page it links to. So a question about, say, default argument values gets the index page's text and is refused, even though the answer is one click away on an allowed host. A crawler would fix that but would also fetch an unbounded number of pages, wander off the documentation, and need its own politeness and storage rules.

## Decision
1. **One level, a fixed cap.** When an entry page is fetched, up to `EKA_WEB_MAX_LINKED_PAGES` (0 to 20, default 0, so it is off) of the pages it links to are fetched too. Links on those pages are never followed.
2. **Same directory only.** A link is kept only if, after resolving it against the entry page and dropping the fragment, it starts with the entry page's directory (`https://host/3/tutorial/` for `https://host/3/tutorial/index.html`). That rules out other hosts, parent directories, `mailto:`, `javascript:`, `tel:`, `data:` and the page itself. Links to files that are not pages (images, archives, PDFs, scripts, styles) are dropped by extension. Duplicates count once, in page order.
3. **robots.txt for linked pages.** The host's `robots.txt` is read once per refresh through the same guarded fetcher and checked with `urllib.robotparser` for the user agent `eka-web-fallback`. A 404 or 410 means there are no rules. Any other failure (timeout, 5xx, refused) means no links are followed for that host. Entry pages are not checked: the owner named them.
4. **Same guard for every fetch.** Each linked page goes through `SafeFetcher` (HTTPS, exact-host allowlist, public address check, redirects re-checked, size, time and content-type caps). Following links never widens the allowlist.
5. **Stored like entry pages.** Each linked page becomes a document owned by the asking user, with its own `source_url` and fetch time, indexed by the worker and cited as `kind: "web"`. A linked page with a fresh copy (younger than `EKA_WEB_REFRESH_HOURS`) is not fetched again.
6. **Fetched together.** The linked pages of one refresh are fetched concurrently with `asyncio.gather`, so following links costs about one fetch time, not N. The wait for indexing stays bounded by `EKA_WEB_WAIT_SECONDS`.

## Flow
```
weak or no evidence
  -> entry URLs without a fresh copy -> SafeFetcher -> store (document + source_url)
  -> max_linked_pages > 0 ?
       links on each fetched entry page -> same directory, page-like, not seen
       -> robots.txt allows (eka-web-fallback) ?  -> no fresh copy ?
       -> fetch all together (SafeFetcher) -> store each
  -> wait (bounded) until the worker marks them ready -> search again, cite kind "web"
```

## Options considered
| Option | Assessment |
|---|---|
| One level, same directory, capped (chosen) | Covers the "index page links to the answer" case with a known, small upper bound on fetches |
| A crawler (breadth-first, depth N) | Unbounded cost and storage per question; out of scope for a fallback |
| A sitemap.xml reader | Many documentation sites have one, but it lists thousands of pages; would still need a cap and a choice of pages |
| A search engine API | Picks the right page directly but is a paid external service and sends the question out; a separate decision |
| Same host instead of same directory | Simpler, but a link from a tutorial to the whole library reference pulls in unrelated pages |

## Consequences
- With the cap at 20 and two entry URLs, a refresh may make 2 + 1 + 40 requests (entry pages, robots.txt, linked pages). The default of 0 keeps ADR-030's behaviour.
- Which pages are taken depends on link order on the entry page; a page beyond the cap is not seen. The log line `web fallback fetched= linked= ready=` shows what happened.
- `robots.txt` crawl-delay is not applied; the fetches of one refresh happen together. Acceptable for at most 20 pages per entry page, and the reason the cap is low.
- Tested: 8 unit tests (`tests/test_web_links.py`), a live fetch of docs.python.org (entry page, robots.txt and 5 linked pages stored), and an end-to-end run through the API in which a question was answered with a citation to a linked page (`controlflow.html`). Only the fake chat model was used.
