# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Source URL and fetch time for pages stored by the web fallback (ADR-030).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11

Both columns stay empty for uploaded files. Existing grants and policies cover them: the API role
already inserts and reads ``documents`` rows of its own owner only.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents ADD COLUMN source_url text, ADD COLUMN fetched_at timestamptz"
    )
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT documents_web_source_check "
        "CHECK ((source_url IS NULL) = (fetched_at IS NULL) AND (source_url IS NULL "
        "OR source_url LIKE 'https://%'))"
    )
    op.execute(
        "CREATE INDEX documents_owner_source_url ON documents (owner_id, source_url) "
        "WHERE source_url IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX documents_owner_source_url")
    op.execute(
        "ALTER TABLE documents DROP CONSTRAINT documents_web_source_check, "
        "DROP COLUMN source_url, DROP COLUMN fetched_at"
    )
