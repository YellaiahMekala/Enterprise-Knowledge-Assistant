# ADR-029: Code and text loaders with code-aware chunking and a line-range locator

| | |
|---|---|
| Status | Proposed |
| Date | 2026-10-31 |
| Decision owner | Maintainer |
| Review trigger | The evaluation (E1) shows code-aware chunking gives no gain over plain line blocks, or a parser dependency becomes worth its cost. |
| Related | FR-36, AC-21, ADR-007, ADR-017 |

## Context
The owner's private corpus (a Java full-stack learning library) contains code, Markdown notes and PDFs. The v0.2 loaders cover PDF, DOCX and CSV. Code differs from prose: splitting inside a method gives chunks that embed poorly and cite badly, and a page number means nothing for a source file.

## Decision
1. Add a plain-read loader for allow-listed text and code extensions (`.java`, `.md`, `.txt`, `.xml`, `.sql`, `.properties`, `.yml`, `.json`): UTF-8 only, size-capped, NUL bytes and other binary content rejected (so a renamed binary fails).
2. The locator is typed: `{"type":"lines","path":"...","start":N,"end":M}` (1-based, inclusive), consistent with ADR-007.
3. Chunking is **code-aware** for these types: prefer whole classes and methods that fit the token budget, split at method boundaries when they do not, then at lines. Boundaries come from small, tested heuristics (brace depth and signature patterns for Java, headings for Markdown), with a fallback to line blocks. No parser dependency in v1.
4. The experiment E1 reports code-aware against plain line blocks on the Java questions of the challenge set; the default is chosen from the evidence.
5. The corpus is private: it lives in a git-ignored `data/` folder and is never committed; public demos and CI use a synthetic or openly licensed corpus.

## Options considered
| Option | Assessment (benefit, cost, risk) |
|---|---|
| Heuristic code-aware chunking, no parser (chosen) | Small, dependency-free, explainable. Heuristics can misjudge unusual formatting; fallback to line blocks bounds the damage. |
| Tree-sitter or a Java parser | Exact boundaries for many languages. Adds native dependencies and image size; deferred until E1 shows a gain. |
| Treat code as plain prose | Simplest. Splits methods arbitrarily; citations are less useful. Rejected as the default, kept as the E1 baseline. |

## Consequences
P2 grows by about 0.5 day. A new loader, a new locator type and property tests (a chunk never splits a method that fits). Citations for code read as file and line range. Copyright of the private corpus is handled by never publishing it.
