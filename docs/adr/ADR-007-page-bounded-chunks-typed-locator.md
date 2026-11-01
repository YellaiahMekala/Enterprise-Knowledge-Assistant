# ADR-007: Page-bounded chunks and a typed locator

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Experiments E1/E2 show page-boundary splitting costs recall beyond the interval. |
| Related | FR-12, FR-14, BRD R4 |

## Context
The product promises page-level citations, but DOCX has no fixed pages and CSV has rows.

## Decision
Chunks never cross a segment boundary (PDF page, DOCX heading section, CSV row group). The locator is a union: page, section or rows.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Segment-bounded chunks (chosen) | Exact, honest citations. A passage straddling a page break is split. |
| Cross-page chunks with a page range | Better recall at boundaries; blurs the citation. Rejected. |
| Convert DOCX to PDF for pages | Heavy dependency and still approximate. Rejected. |

## Consequences
The UI and API show the locator kind that exists for each file type.
