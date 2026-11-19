# Copyright (c) 2026 the owner of this repository. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
# Canary: eka-canary-2a4a885ea917479dadc1
"""Conversations, messages and usage events, each isolated by owner.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06

Same isolation model as migration 0001: row-level security is enabled and forced, the API role
sees only rows whose ``owner_id`` equals the session setting, and a missing setting matches
nothing. Messages are append-only for the API role (no UPDATE or DELETE grant); they disappear
with their conversation through the foreign key.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNER_CHECK = "owner_id ~ '^[A-Za-z0-9_.-]{1,36}$'"
_SESSION_OWNER = "current_setting('app.owner_id', true)"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE conversations (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id    text        NOT NULL,
            title       text        NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT conversations_owner_check CHECK ({_OWNER_CHECK})
        )
        """
    )
    op.execute(
        "CREATE INDEX conversations_owner_updated ON conversations (owner_id, updated_at DESC)"
    )

    op.execute(
        f"""
        CREATE TABLE messages (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            seq              bigint GENERATED ALWAYS AS IDENTITY,
            conversation_id  uuid        NOT NULL,
            owner_id         text        NOT NULL,
            role             text        NOT NULL,
            content          text        NOT NULL,
            citations        jsonb       NOT NULL DEFAULT '[]'::jsonb,
            refused          boolean     NOT NULL DEFAULT false,
            refusal_reason   text,
            created_at       timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT messages_conversation_id_fkey
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE,
            CONSTRAINT messages_role_check CHECK (role IN ('user', 'assistant')),
            CONSTRAINT messages_owner_check CHECK ({_OWNER_CHECK})
        )
        """
    )
    # seq, not created_at, orders a conversation: both messages of a turn are inserted in one
    # transaction, so their timestamps are equal.
    op.execute("CREATE INDEX messages_conversation_seq ON messages (conversation_id, seq)")

    op.execute(
        f"""
        CREATE TABLE usage_events (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id          text             NOT NULL,
            conversation_id   uuid,
            mode              text             NOT NULL,
            model             text             NOT NULL,
            refused           boolean          NOT NULL,
            retrieved         integer          NOT NULL,
            top_cosine        double precision,
            prompt_chars      integer          NOT NULL,
            completion_chars  integer          NOT NULL,
            latency_ms        integer          NOT NULL,
            created_at        timestamptz      NOT NULL DEFAULT now(),
            CONSTRAINT usage_events_conversation_id_fkey
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE SET NULL,
            CONSTRAINT usage_events_owner_check CHECK ({_OWNER_CHECK})
        )
        """
    )
    op.execute(
        "CREATE INDEX usage_events_owner_created ON usage_events (owner_id, created_at DESC)"
    )

    for table in ("conversations", "messages", "usage_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY conversations_owner ON conversations FOR ALL TO eka_api
            USING (owner_id = {_SESSION_OWNER}) WITH CHECK (owner_id = {_SESSION_OWNER})
        """
    )
    op.execute(
        f"""
        CREATE POLICY messages_owner ON messages FOR ALL TO eka_api
            USING (owner_id = {_SESSION_OWNER}) WITH CHECK (owner_id = {_SESSION_OWNER})
        """
    )
    op.execute(
        f"""
        CREATE POLICY usage_events_owner ON usage_events FOR ALL TO eka_api
            USING (owner_id = {_SESSION_OWNER}) WITH CHECK (owner_id = {_SESSION_OWNER})
        """
    )
    # Usage events hold counts and timings, no text: admins may read them across users.
    op.execute(
        """
        CREATE POLICY usage_events_admin_read ON usage_events FOR SELECT TO eka_api
            USING (current_setting('app.role', true) = 'admin')
        """
    )

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON conversations TO eka_api")
    op.execute("GRANT SELECT, INSERT ON messages TO eka_api")
    op.execute("GRANT SELECT, INSERT ON usage_events TO eka_api")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_events")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
