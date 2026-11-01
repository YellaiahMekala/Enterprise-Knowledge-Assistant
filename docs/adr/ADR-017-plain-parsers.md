# ADR-017: Plain parsers, not Unstructured or LlamaParse

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Table-heavy or scanned documents become a requirement. |
| Related | FR-12, FR-18 |

## Context
Parsers run on untrusted files; dependency size and data egress matter.

## Decision
`pypdf`, `python-docx` and the standard-library `csv` module.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| pypdf + python-docx + csv (chosen) | Small, permissive licences. PDF tables extract as flowing text; image-only PDFs fail. |
| Unstructured | Richer extraction; large dependency tree and system packages. Rejected. |
| LlamaParse | Hosted service that would receive the documents. Rejected. |

## Consequences
Limitations are listed in the README and the test strategy. Code and text files use a plain-read loader ([ADR-029](ADR-029-code-aware-chunking.md)).
