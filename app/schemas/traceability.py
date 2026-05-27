"""Traceability DTOs."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TraceabilityNode(BaseModel):
    """A node in the lot-genealogy graph (a customer, an order, a lot, ...)."""

    node_type: str
    node_id: str
    label: Optional[str] = None
    attributes: Dict[str, Any] = {}


class TraceabilityEdge(BaseModel):
    source: str  # node_id
    target: str  # node_id
    predicate: str


class TraceabilityResponse(BaseModel):
    """Response of ``GET /traceability/{lot_id}``.

    Mirrors the ontology edges captured in ``app.core.ontology`` so the
    payload can be re-serialised as RDF / JSON-LD for SPARQL export.
    """

    lot_id: str
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    production_order_id: Optional[str] = None
    part_id: Optional[str] = None
    lot_quantity: Optional[Decimal] = None
    status: Optional[str] = None
    dispatch_id: Optional[str] = None
    final_quality_status: Optional[str] = None
    closed_at: Optional[datetime] = None
    nodes: List[TraceabilityNode] = []
    edges: List[TraceabilityEdge] = []
