"""fix_fk_delete_rules_for_gdpr

Revision ID: 222cafa3baac_fix_fk_delete_rules_for_gdpr
Revises: 1c9784351972
Create Date: 2026-03-08

Summary
-------
Aligns every foreign-key DELETE_RULE with GDPR right-to-erasure requirements.

Before this migration, DELETE FROM users WHERE id = :id would be blocked by
MySQL's default NO ACTION behaviour on several child tables, making right-to-
erasure impossible without application-level workarounds.

Changes
-------
Table                  Column           Before      After
─────────────────────────────────────────────────────────
files                  user_id          NO ACTION   CASCADE
vector_stores          user_id          NO ACTION   CASCADE
sandboxes              user_id          NO ACTION   CASCADE  (ORM said delete-orphan, DB disagreed)
thread_participants    user_id          NO ACTION   CASCADE
user_assistants        user_id          NO ACTION   CASCADE
audit_logs             user_id          NO ACTION   SET NULL (preserve for compliance)
actions                run_id           NO ACTION   CASCADE  (runs already cascade; prevent orphans)
vector_store_files     vector_store_id  NO ACTION   CASCADE

Already correct (no change):
  api_keys.user_id          → CASCADE
  runs.user_id              → CASCADE
  batfish_snapshots.user_id → CASCADE
  assistants.owner_id       → SET NULL
  threads.owner_id          → SET NULL
  file_storage.file_id      → CASCADE

Design notes
------------
* audit_logs deliberately uses SET NULL so compliance records survive user
  deletion.  The user_id column is nullable in the schema to support this.
* messages.thread_id has NO FK constraint at all — orphaned messages are
  handled by the application-level erase_user() method and the
  purge_orphaned_threads daemon (separate concern).
* All FK operations follow the safe pattern:
    1. drop existing constraint by name
    2. recreate with the desired delete rule
  Constraint names are taken directly from information_schema output to
  guarantee correctness.
"""

from alembic import op

# ── Revision identifiers ────────────────────────────────────────────────────
revision = "222cafa3baac"
down_revision = "1c9784351972"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── files.user_id → CASCADE ──────────────────────────────────────────────
    op.drop_constraint("files_ibfk_1", "files", type_="foreignkey")
    op.create_foreign_key(
        "files_ibfk_1",
        "files",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── vector_stores.user_id → CASCADE ──────────────────────────────────────
    op.drop_constraint("vector_stores_ibfk_1", "vector_stores", type_="foreignkey")
    op.create_foreign_key(
        "vector_stores_ibfk_1",
        "vector_stores",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── vector_store_files.vector_store_id → CASCADE ─────────────────────────
    op.drop_constraint("vector_store_files_ibfk_1", "vector_store_files", type_="foreignkey")
    op.create_foreign_key(
        "vector_store_files_ibfk_1",
        "vector_store_files",
        "vector_stores",
        ["vector_store_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── sandboxes.user_id → CASCADE ───────────────────────────────────────────
    op.drop_constraint("sandboxes_ibfk_1", "sandboxes", type_="foreignkey")
    op.create_foreign_key(
        "sandboxes_ibfk_1",
        "sandboxes",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── thread_participants.user_id → CASCADE ─────────────────────────────────
    op.drop_constraint("thread_participants_ibfk_2", "thread_participants", type_="foreignkey")
    op.create_foreign_key(
        "thread_participants_ibfk_2",
        "thread_participants",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── user_assistants.user_id → CASCADE ─────────────────────────────────────
    op.drop_constraint("user_assistants_ibfk_1", "user_assistants", type_="foreignkey")
    op.create_foreign_key(
        "user_assistants_ibfk_1",
        "user_assistants",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ── audit_logs.user_id → SET NULL (compliance records must survive) ───────
    op.drop_constraint("audit_logs_ibfk_1", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_ibfk_1",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── actions.run_id → CASCADE ──────────────────────────────────────────────
    # runs already cascade-delete when a user is deleted; without this fix,
    # their child actions become orphans that block the run deletion.
    op.drop_constraint("actions_ibfk_1", "actions", type_="foreignkey")
    op.create_foreign_key(
        "actions_ibfk_1",
        "actions",
        "runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Restore all constraints to NO ACTION (pre-migration state)

    op.drop_constraint("actions_ibfk_1", "actions", type_="foreignkey")
    op.create_foreign_key("actions_ibfk_1", "actions", "runs", ["run_id"], ["id"])

    op.drop_constraint("audit_logs_ibfk_1", "audit_logs", type_="foreignkey")
    op.create_foreign_key("audit_logs_ibfk_1", "audit_logs", "users", ["user_id"], ["id"])

    op.drop_constraint("user_assistants_ibfk_1", "user_assistants", type_="foreignkey")
    op.create_foreign_key("user_assistants_ibfk_1", "user_assistants", "users", ["user_id"], ["id"])

    op.drop_constraint("thread_participants_ibfk_2", "thread_participants", type_="foreignkey")
    op.create_foreign_key(
        "thread_participants_ibfk_2", "thread_participants", "users", ["user_id"], ["id"]
    )

    op.drop_constraint("sandboxes_ibfk_1", "sandboxes", type_="foreignkey")
    op.create_foreign_key("sandboxes_ibfk_1", "sandboxes", "users", ["user_id"], ["id"])

    op.drop_constraint("vector_store_files_ibfk_1", "vector_store_files", type_="foreignkey")
    op.create_foreign_key(
        "vector_store_files_ibfk_1",
        "vector_store_files",
        "vector_stores",
        ["vector_store_id"],
        ["id"],
    )

    op.drop_constraint("vector_stores_ibfk_1", "vector_stores", type_="foreignkey")
    op.create_foreign_key("vector_stores_ibfk_1", "vector_stores", "users", ["user_id"], ["id"])

    op.drop_constraint("files_ibfk_1", "files", type_="foreignkey")
    op.create_foreign_key("files_ibfk_1", "files", "users", ["user_id"], ["id"])
