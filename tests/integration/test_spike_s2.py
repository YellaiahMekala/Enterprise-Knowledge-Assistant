# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Spike S-2: filtered approximate search on a skewed corpus (Implementation Plan, P3).

Measures, with a seeded random corpus (run with ``-s`` to see the numbers):
* exact path, small owner: returns min(k, n) rows for every query;
* approximate path, small owner: how many rows it returns;
* approximate path, large owner: recall@10 against exact, swept over ef_search.
"""

import time
import uuid

import numpy as np
from sqlalchemy import Engine, text

from eka.adapters.db.engine import Database
from eka.adapters.db.search import SqlChunkSearch
from eka.domain.models import Role
from tests.integration.helpers import admin_engine, run_async

DIM = 384
BIG_ROWS = 8_000
SMALL_ROWS = 50
QUERIES = 30
K = 10
EF_SEARCH = 400


def _random_unit(rng: np.random.Generator, n: int) -> np.ndarray:
    vectors = rng.standard_normal((n, DIM)).astype(np.float32)
    unit: np.ndarray = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    return unit


def _literal(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vector) + "]"


def _seed(engine: Engine, owner: str, rows: int, rng: np.random.Generator) -> uuid.UUID:
    document_id = uuid.uuid4()
    vectors = _random_unit(rng, rows)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO documents (id, owner_id, filename, content_type, size_bytes, sha256, "
                "storage_key, status) VALUES (:id, :owner, 'bulk.txt', 'text/plain', 1, :sha, :key, 'ready')"  # noqa: E501
            ),
            {
                "id": document_id,
                "owner": owner,
                "sha": uuid.uuid4().hex * 2,
                "key": f"{owner}/{document_id}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO chunks (id, document_id, owner_id, ordinal, text, locator, char_start, "  # noqa: E501
                "char_end, token_count, embedding, embedding_model, chunk_config) VALUES (:id, :doc, "  # noqa: E501
                ":owner, :ordinal, :body, CAST(:locator AS jsonb), 0, 1, 1, CAST(:vector AS vector), "  # noqa: E501
                "'spike', 's2')"
            ),
            [
                {
                    "id": uuid.uuid4(),
                    "doc": document_id,
                    "owner": owner,
                    "ordinal": i,
                    "body": f"synthetic passage {i}",
                    "locator": '{"type": "page", "page": 1}',
                    "vector": _literal(vectors[i]),
                }
                for i in range(rows)
            ],
        )
    return document_id


def _search(
    url: str, owner: str, queries: np.ndarray, *, exact: bool, k: int, ef: int = EF_SEARCH
) -> list[list[uuid.UUID]]:
    async def scenario() -> list[list[uuid.UUID]]:
        database = Database(url)
        results: list[list[uuid.UUID]] = []
        try:
            for query in queries:
                async with database.session_for(owner, Role.USER) as session:
                    candidates = await SqlChunkSearch(session).dense(
                        owner,
                        query.tolist(),
                        k,
                        document_ids=None,
                        exact=exact,
                        ef_search=ef,
                    )
                results.append([c.chunk_id for c in candidates])
        finally:
            await database.dispose()
        return results

    return run_async(scenario)


def test_spike_s2_filtered_search_on_a_skewed_corpus(isolated_url: str) -> None:
    engine = admin_engine(isolated_url)
    rng = np.random.default_rng(20261103)
    big, small = f"big-{uuid.uuid4().hex[:6]}", f"small-{uuid.uuid4().hex[:6]}"
    _seed(engine, big, BIG_ROWS, rng)
    _seed(engine, small, SMALL_ROWS, rng)
    with engine.begin() as connection:
        # Statistics, as autovacuum would have them in a running system. Without them the planner
        # assumes the owner filter is very selective and prefers the owner index to HNSW.
        connection.execute(text("ANALYZE chunks"))
    queries = _random_unit(rng, QUERIES)

    # Small owner, exact path.
    small_exact = _search(isolated_url, small, queries, exact=True, k=K)
    assert all(len(row) == min(K, SMALL_ROWS) for row in small_exact)

    # Small owner, approximate path.
    small_approx = _search(isolated_url, small, queries, exact=False, k=K)
    short = sum(1 for row in small_approx if len(row) < min(K, SMALL_ROWS))
    small_recall = np.mean(
        [
            len(set(a) & set(e)) / max(1, len(e))
            for a, e in zip(small_approx, small_exact, strict=True)
        ]
    )
    print(
        f"\nS-2 small owner ({SMALL_ROWS} rows): approximate path short on {short}/{QUERIES} queries; "  # noqa: E501
        f"recall@{K} {small_recall:.3f}"
    )

    # Large owner, approximate against exact: recall must be at least 0.95.
    big_exact = _search(isolated_url, big, queries, exact=True, k=K)
    sweep: dict[int, float] = {}
    for ef in (100, 200, 400, 800):
        started = time.perf_counter()
        big_approx = _search(isolated_url, big, queries, exact=False, k=K, ef=ef)
        per_query_ms = (time.perf_counter() - started) * 1000 / QUERIES
        recall = float(
            np.mean([len(set(a) & set(e)) / K for a, e in zip(big_approx, big_exact, strict=True)])
        )
        sweep[ef] = recall
        print(
            f"S-2 ef_search={ef:>4}: recall@{K} {recall:.3f}, about {per_query_ms:.0f} ms per query "  # noqa: E501
            f"(includes connection setup)"
        )
    assert sweep[EF_SEARCH] >= 0.95, sweep

    hnsw_scans, owner_scans = _index_scans(engine)
    print(
        f"S-2 index scans during the approximate sweeps: HNSW {hnsw_scans}, owner b-tree "
        f"{owner_scans} (the planner chose between HNSW and an exact sort per execution)"
    )
    assert hnsw_scans > 0, "the HNSW index was never used by the approximate path"


def _index_scans(engine: Engine) -> tuple[int, int]:
    """Scan counts of the HNSW and owner indexes. Statistics reach the view after a short delay."""
    deadline = time.monotonic() + 10
    while True:
        with engine.begin() as connection:
            rows = connection.execute(
                text(
                    "SELECT indexrelname, idx_scan FROM pg_stat_user_indexes "
                    "WHERE relname = 'chunks'"
                )
            ).all()
            counts: dict[str, int] = {row[0]: int(row[1]) for row in rows}
        if counts.get("chunks_embedding_hnsw", 0) > 0 or time.monotonic() > deadline:
            return counts.get("chunks_embedding_hnsw", 0), counts.get("chunks_owner", 0)
        time.sleep(0.5)
