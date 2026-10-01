"""Add Agent runs, tool calls, evidence, and approvals.

Revision ID: 20260924_0002
Revises: 20260924_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0002"
down_revision: str | None = "20260924_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column(
            "created_by",
            sa.String(length=128),
            nullable=False,
            server_default="demo-operator",
        ),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_runs_incident_id"), "agent_runs", ["incident_id"]
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("rollback_plan", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_tool_calls_incident_id"), "tool_calls", ["incident_id"]
    )
    op.create_index(op.f("ix_tool_calls_run_id"), "tool_calls", ["run_id"])
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("tool_call_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidence_incident_id"), "evidence", ["incident_id"])
    op.create_index(op.f("ix_evidence_tool_call_id"), "evidence", ["tool_call_id"])
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("tool_call_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_call_id"),
    )
    op.create_index(op.f("ix_approvals_decision"), "approvals", ["decision"])
    op.create_index(
        op.f("ix_approvals_incident_id"), "approvals", ["incident_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_approvals_incident_id"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_decision"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_evidence_tool_call_id"), table_name="evidence")
    op.drop_index(op.f("ix_evidence_incident_id"), table_name="evidence")
    op.drop_table("evidence")
    op.drop_index(op.f("ix_tool_calls_run_id"), table_name="tool_calls")
    op.drop_index(op.f("ix_tool_calls_incident_id"), table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index(op.f("ix_agent_runs_incident_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_column("incidents", "created_by")
