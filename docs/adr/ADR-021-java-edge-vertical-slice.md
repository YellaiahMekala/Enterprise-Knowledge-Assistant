# ADR-021: Spring Boot edge service delivered as a vertical slice

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | The slice is not complete by the end of P5 and the cut line is applied, or a customer environment supplies its own gateway. |
| Related | FR-60 to FR-67, ADR-001, ADR-022, ADR-023 |

## Context
v0.1 treated the Spring Boot gateway as design only. An external assessment found this the largest mismatch with the project's Java-AI-integration positioning: Java appeared only as a plan. The slice is also where identity, authorization, audit, rate limits and resilience are demonstrated rather than described.

## Decision
Build a small Spring Boot edge service (Java 21) in `gateway/` and ship it in the Compose stack. Chain: Angular → edge → FastAPI core → PostgreSQL. The edge owns identity, role authorization, rate limits and quotas, audit, resilience, API lifecycle and edge observability. The core owns parsing, retrieval, answering and data-level authorization, and is never published in edge mode. **Boundaries (to keep the slice small):** no document processing or retrieval logic in the edge; its only datastore is an audit schema; one route family (`/api/v1/**`).

**Decided 2026-10-31 (D-1): Java 21, Spring Boot 4.1.x, Spring Cloud 2025.1.x** (Spring maps Cloud 2025.1.x to Boot 4.0.x and 4.1.x; 2025.0.x to 3.5.x). A **thin edge** (token validation, `GET /api/v1/me`, internal JWT, private core, one end-to-end contract test) is built first as P3b so Java appears in the first demonstrable slice; the rest stays in P5. Original text follows. **Spring Boot version (was open decision D-1):** Spring Boot 3.5.x was the stated production target, but its last release on Maven Central is dated 2026-06-25 and Spring Boot 4.1.x is the current GA line (checked 2026-10-31). Recommendation: use 4.1.x (Spring Cloud 2025.1.x), consistent with the maintainer's other Spring project; verify the 3.5 support window on spring.io before choosing 3.5.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Deliver the slice in v1 (chosen) | Demonstrates the Java-to-AI integration for real. Cost: roughly 4 to 7 working days and a second CI pipeline. Risk: schedule (BRD R9) - mitigated by a spike, strict boundaries and the cut line. |
| Design only (v0.1) | Zero cost. Java is absent from the shipped artefact; the identity story is unproven. Superseded. |
| Leave Java out | Pure Python project. Does not meet the stated goals. Rejected. |

## Consequences
The plan grows (see Implementation Plan), the Python core gains an edge-mode authentication path, and Compose gains `gateway` and a development identity provider.
