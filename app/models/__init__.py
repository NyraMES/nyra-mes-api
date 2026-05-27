"""SQLAlchemy ORM models for the Manufacturing Workflow Intelligence Platform.

Importing this package eagerly registers every model class with the shared
``Base.metadata`` so that:

  * cross-schema ForeignKey targets resolve at import time
  * ``Base.metadata`` is fully populated for tests / Alembic / RDF export

DB layout (post-realignment)
----------------------------
Every entity uses a surrogate ``id`` (BIGINT) as the PK and an opaque
``<entity>_code`` (VARCHAR) as the business identifier exposed by the API.
Foreign keys join on the bigint ``id`` columns; services translate
business codes <-> bigint ids at service boundaries.

Manufacturing ontology hint (see ``app.core.ontology``)::

    ProductionLot     --requires-->        Machine
    RoutingOperation  --consumes-->        Material (via BOM + OperationResourceRequirement)
    Routing           --hasOperation-->    RoutingOperation
    InspectionResult  --creates-->         NCR
    ProductionLot     --dispatchedThrough--> Dispatch
"""

from app.models.bom import BOM, BOMItem
from app.models.customer import Customer
from app.models.dispatch import Dispatch, DispatchLine
from app.models.feasibility import FeasibilityGate
from app.models.maintenance import MachineDowntime, MaintenanceEvent
from app.models.oee import OEEDailySummary
from app.models.ontology_db import (
    EntityOntologyMapping,
    OntologyClass,
    OntologyRelationship,
    RDFTripleStaging,
)
from app.models.order import CustomerOrder, CustomerOrderLine
from app.models.part import Part
from app.models.process import ProcessLibrary
from app.models.data_capture import (
    DataCaptureField,
    DataCaptureTemplate,
    OperationDataCapture,
    OperationDataCaptureValue,
)
from app.models.production import ProductionLot, ProductionOrder
from app.models.quality import (
    Defect,
    InspectionParameter,
    InspectionPlan,
    InspectionResult,
    InspectionResultParameter,
    NCR,
)
from app.models.resource import (
    Machine,
    Material,
    Tool,
    WorkCenter,
    WorkforceRole,
)
from app.models.routing import OperationResourceRequirement, Routing, RoutingOperation
from app.models.schedule import ProductionSchedule
from app.models.traceability import TraceabilityClosure
from app.models.work_order import WorkOrder, WorkOrderEvent

__all__ = [
    "BOM",
    "BOMItem",
    "DataCaptureField",
    "DataCaptureTemplate",
    "Customer",
    "CustomerOrder",
    "CustomerOrderLine",
    "Defect",
    "Dispatch",
    "DispatchLine",
    "EntityOntologyMapping",
    "FeasibilityGate",
    "InspectionParameter",
    "InspectionPlan",
    "InspectionResult",
    "InspectionResultParameter",
    "Machine",
    "MachineDowntime",
    "MaintenanceEvent",
    "Material",
    "NCR",
    "OEEDailySummary",
    "OntologyClass",
    "OntologyRelationship",
    "OperationDataCapture",
    "OperationDataCaptureValue",
    "OperationResourceRequirement",
    "Part",
    "ProcessLibrary",
    "ProductionLot",
    "ProductionOrder",
    "ProductionSchedule",
    "RDFTripleStaging",
    "Routing",
    "RoutingOperation",
    "Tool",
    "TraceabilityClosure",
    "WorkCenter",
    "WorkOrder",
    "WorkOrderEvent",
    "WorkforceRole",
]
