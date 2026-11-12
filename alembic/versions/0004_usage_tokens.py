"""Token counts, cost and first-token times on usage events (ADR-037).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12

All new columns are nullable: older rows and answers that never called a model have none. The
existing grants and row-level policies cover new columns, and no text is added.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE usage_events "
        "ADD COLUMN provider text, "
        "ADD COLUMN prompt_tokens integer, "
        "ADD COLUMN completion_tokens integer, "
        "ADD COLUMN token_source text, "
        "ADD COLUMN cost_usd numeric(12, 6), "
        "ADD COLUMN ttft_ms integer, "
        "ADD COLUMN answer_ttfb_ms integer"
    )
    op.execute(
        "ALTER TABLE usage_events ADD CONSTRAINT usage_events_token_source_check "
        "CHECK (token_source IS NULL OR token_source IN ('provider', 'estimated'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE usage_events "
        "DROP CONSTRAINT usage_events_token_source_check, "
        "DROP COLUMN provider, DROP COLUMN prompt_tokens, DROP COLUMN completion_tokens, "
        "DROP COLUMN token_source, DROP COLUMN cost_usd, DROP COLUMN ttft_ms, "
        "DROP COLUMN answer_ttfb_ms"
    )
