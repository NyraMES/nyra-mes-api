"""Master-data resource listings (machines, tools, materials, workforce).

Read-only for now - the routing master uses these to populate the
"required resource" pickers when authoring operation requirements.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.models.resource import (
    Machine,
    Material,
    Tool,
    WorkCenter,
    WorkforceRole,
)
from app.schemas.resource import (
    MachineOut,
    MaterialOut,
    ToolOut,
    WorkCenterOut,
    WorkforceRoleOut,
)
from app.services import resolver


def list_work_centers(db: Session) -> List[WorkCenterOut]:
    rows = db.query(WorkCenter).order_by(WorkCenter.id).all()
    return [
        WorkCenterOut(
            id=r.id,
            work_center_id=r.work_center_code,
            work_center_name=r.work_center_name,
            process_type=r.process_type,
            location=r.location,
            is_active=r.is_active,
        )
        for r in rows
    ]


def list_machines(db: Session) -> List[MachineOut]:
    rows = db.query(Machine).order_by(Machine.id).all()
    return [
        MachineOut(
            id=r.id,
            machine_id=r.machine_code,
            machine_name=r.machine_name,
            work_center_id=(
                resolver.work_center_code(db, r.work_center_id)
                if r.work_center_id
                else None
            ),
            machine_type=r.machine_type,
            machine_status=r.machine_status,
        )
        for r in rows
    ]


def list_tools(db: Session) -> List[ToolOut]:
    rows = db.query(Tool).order_by(Tool.id).all()
    return [
        ToolOut(
            id=r.id,
            tool_id=r.tool_code,
            tool_name=r.tool_name,
            tool_type=r.tool_type,
            tool_status=r.tool_status,
        )
        for r in rows
    ]


def list_materials(db: Session) -> List[MaterialOut]:
    rows = db.query(Material).order_by(Material.id).all()
    return [
        MaterialOut(
            id=r.id,
            material_id=r.material_code,
            material_name=r.material_name,
            material_type=r.material_type,
            unit_of_measure=r.unit_of_measure,
            available_quantity=r.available_quantity,
        )
        for r in rows
    ]


def list_workforce_roles(db: Session) -> List[WorkforceRoleOut]:
    rows = db.query(WorkforceRole).order_by(WorkforceRole.id).all()
    return [
        WorkforceRoleOut(
            id=r.id,
            role_id=r.role_code,
            role_name=r.role_name,
            skill_level=r.skill_level,
            available_count=r.available_count,
            created_at=r.created_at,
        )
        for r in rows
    ]
