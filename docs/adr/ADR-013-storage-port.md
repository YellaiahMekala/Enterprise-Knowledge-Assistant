# ADR-013: Storage port with local disk and S3 adapters

| | |
|---|---|
| Status | Accepted |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | A real S3-compatible container is chosen and verified (open decision in the plan). |
| Related | FR-19 |

## Context
S3 needs cloud credentials everywhere; local runs need a filesystem. The MinIO Docker Hub repository returned no data when checked on 2026-10-31.

## Decision
`FileStore` with `LocalFileStore` (default) and `S3FileStore`. S3 tested in-process with `moto`; an S3-compatible container is chosen and verified in P9.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Port + two adapters (chosen) | Works offline; S3 by configuration. |
| S3 only | Needs cloud credentials in every environment. Rejected. |

## Consequences
Shared contract tests run against both adapters.
