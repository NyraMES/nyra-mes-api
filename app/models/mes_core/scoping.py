"""Shared tenant/workspace scoping columns for nyra_mes_core operational tables."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID


def workspace_id_column():
    """Optional workspace scope — NULL means tenant-wide (backward compatible)."""
    return Column(
        UUID(as_uuid=True),
        ForeignKey("core.project_workspace.workspace_id"),
        nullable=True,
    )
