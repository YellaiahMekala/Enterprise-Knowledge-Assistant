# ADR-033: Incident triage agent as a separate service

| | |
|---|---|
| Status | Accepted |
| Date | 2026-11-08 |
| Decision owner | Maintainer |
| Review trigger | The agent gives a wrong cause in a way that would have misled an on-call person, or it needs a tool that can change state. |
| Related | ADR-002, ADR-026, ADR-028, NFR-14, NFR-15 |

## Context
Alerts say that something is wrong, not why. The runbooks list what a person checks first (error rate by route, health, breaker state). A model with tools can run those first checks and put the findings in the alert email, so the person starts with evidence instead of a bare alert.

## Decision
A separate Java 21 Spring Boot service, `ops-agent`, built on LangChain4j. Alertmanager posts each alert group to it; it investigates and emails a plain-text report.

- **Read-only tools only:** `promQuery` (a PromQL instant query), `serviceHealth` (GET on the core's readiness and the edge's health), `runbook` (a section of `docs/runbooks.md`), and since 2026-11-11 `searchLogs` (recent container log lines from Loki, ADR-035). The base URLs are fixed at start-up and only GET is possible, so the model chooses a query or a path but never a host or a method.
- **Guardrails:** a PromQL check (length, plain characters, only this system's metric families), a budget of 5 tool calls per alert group (further calls are refused without being sent), a 10 s timeout per call, temperature 0, and a system prompt that says tool output is data, not instructions.
- **Audit:** every tool call is logged on `eka.ops.audit` with its arguments and the size of the answer.
- **Always a report:** with no model key, or when the model call fails, the report is built from the runbook steps, and it says so.
- **Entry point:** `POST /alerts` needs a bearer token (constant-time comparison); the service does not start without one. It answers 202 at once and works in the background, so a slow model never makes Alertmanager retry.

## Options considered
| Option | Assessment |
|---|---|
| Separate service (chosen) | The edge stays a thin, deterministic gateway and the core keeps ADR-002 (no orchestration framework in the request path). The agent can fail or be switched off without touching request handling. |
| Inside the edge or the core | Puts a model and a framework in the path of every user request. Rejected. |
| Python agent next to the core | Fits the language of the core, but the portfolio goal is Java AI integration, and the edge's observability and security conventions are in Java. |
| Alertmanager email only | Reliable and simple, but the person still has to run the first checks by hand. Kept as the fallback behaviour. |
| Tools that can act (restart, roll back) | Out of scope: a wrong action from a model costs more than a slow human. Review trigger above. |

## Consequences
- Alert delivery depends on the agent being up. Second path (added 2026-11-11): Prometheus scrapes Alertmanager, `EkaAlertDeliveryFailing` fires on any failed webhook attempt in 10 minutes, and Alertmanager emails that one alert directly, never through the agent. Drill: with the agent stopped, the email reached the local mail catcher 70 s after Prometheus started. Agent failure after acceptance (added 2026-11-18): the delivery layer bounds the investigation (3 minutes, then a runbook-only report), retries the email, counts a final failure (`EkaTriageReportFailed`, emailed by Alertmanager directly) and also tries a "triage failed" notice; a journal file per accepted batch lets a restart finish interrupted work. Drill: `scripts/triage_failure_drill.sh`. Not covered: no journal on AWS, and the notice shares the report's mail server.
- The cause the model states can be wrong. The email says so, lists the evidence it used and marks runbook-only reports as such.
- Log search was added on 2026-11-11 as its own decision (ADR-035): Loki and Alloy in the monitoring profile, and a `searchLogs` tool that builds the query itself and masks credentials.
- Cost: a few thousand tokens per alert group with a small model. Not yet measured with a live model.
