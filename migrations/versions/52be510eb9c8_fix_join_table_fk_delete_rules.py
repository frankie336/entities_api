"""fix_join_table_fk_delete_rules

Revision ID: fix_join_table_fk_delete_rules
Revises: 9351530d20ab
Create Date: 2026-03-08

Summary
-------
Fixes the two remaining NO ACTION FK delete rules on the many-to-many
join tables not covered by 222cafa3baac_fix_fk_delete_rules_for_gdpr.

Changes
-------
Table                  Column        Before      After
──────────────────────────────────────────────────────
thread_participants    thread_id     NO ACTION   CASCADE
user_assistants        assistant_id  NO ACTION   CASCADE

Design notes
------------
* thread_participants.thread_id → CASCADE
  When a thread is hard-deleted, its participation records are cleaned up
  automatically. Without this, deleting a thread leaves ghost rows in
  thread_participants referencing a non-existent thread.

* user_assistants.assistant_id → CASCADE
  When an assistant is permanently deleted, its association rows are cleaned
  up automatically. Soft-deleted assistants (deleted_at set) are not
  hard-deleted, so their user_assistants rows are intentionally preserved
  until permanent deletion is confirmed.

Idempotency
-----------
Uses safe_ddl.replace_fk which checks constraint existence before
dropping or creating. Safe to re-run.
"""

from migrations.utils.safe_ddl import replace_fk

# ── Revision identifiers ────────────────────────────────────────────────────
revision = "52be510eb9c8"
down_revision = "9351530d20ab"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── thread_participants.thread_id → CASCADE ───────────────────────────────
    replace_fk(
        "thread_participants_ibfk_1",
        "thread_participants",
        "threads",
        ["thread_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── user_assistants.assistant_id → CASCADE ────────────────────────────────
    replace_fk(
        "user_assistants_ibfk_2",
        "user_assistants",
        "assistants",
        ["assistant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:

    # Restore to NO ACTION (pre-migration state)
    replace_fk(
        "user_assistants_ibfk_2",
        "user_assistants",
        "assistants",
        ["assistant_id"],
        ["id"],
        ondelete=None,
    )

    replace_fk(
        "thread_participants_ibfk_1",
        "thread_participants",
        "threads",
        ["thread_id"],
        ["id"],
        ondelete=None,
    )
