# ADR-028: SLOs, error budgets and alerts as code

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | Real traffic data replaces the targets, or the alert noise rate exceeds what a single maintainer can handle. |
| Related | NFR-14, NFR-15 |

## Context
Latency and cost targets alone do not say when to act. Operating ownership needs objectives, a budget and alerts tied to burn.

## Decision
Define SLIs and SLOs (Architecture §9.3), a 30-day error budget, and multi-window burn-rate alerts. Alert rules and dashboards are files in the repository (`ops/`), validated in CI (`promtool check rules`) and exercised by a synthetic fault. SLOs are **objectives for the reference deployment**, measured in load and resilience tests; there is no production traffic.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| SLO + burn-rate alerts as code (chosen) | Actionable, reviewable. Needs honest labelling because there is no production data. |
| Threshold alerts only | Noisy and unlinked to user impact. Rejected. |
| No alerting | Not operable. Rejected. |

## Consequences
Runbooks link from every alert (Operational Readiness).
