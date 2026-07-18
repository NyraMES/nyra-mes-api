"""OpenAPI / Swagger tag definitions.

Centralising tags here keeps Swagger UI grouped consistently and ensures
the order matches the manufacturing workflow.
"""

from __future__ import annotations

from typing import Final, List


class Tags:
    CUSTOMER:       Final[str] = "Customer"
    PART:           Final[str] = "Part"
    ORDER:          Final[str] = "Order"
    PRODUCTION:     Final[str] = "Production"
    LOT:            Final[str] = "Lot"
    ROUTING:        Final[str] = "Routing"
    FEASIBILITY:    Final[str] = "Feasibility"
    SCHEDULING:     Final[str] = "Scheduling"
    WORK_ORDER:     Final[str] = "Work Order"
    EXECUTION:      Final[str] = "Execution"
    PROCESS:        Final[str] = "Process Library"
    DATA_CAPTURE:   Final[str] = "Data Capture"
    INSPECTION:     Final[str] = "Inspection"
    NCR:            Final[str] = "NCR"
    DISPATCH:       Final[str] = "Dispatch"
    TRACEABILITY:   Final[str] = "Traceability"
    OEE:            Final[str] = "OEE"
    MAINTENANCE:    Final[str] = "Maintenance"
    DASHBOARD:      Final[str] = "Dashboard"
    INTELLIGENCE:   Final[str] = "Intelligence"
    ONTOLOGY:       Final[str] = "Ontology"
    AUTH:           Final[str] = "Auth"
    MES_CORE:       Final[str] = "MES Core (Multi-Tenant)"
    TEMPLATE:       Final[str] = "Industry Templates"
    WORKSPACE:      Final[str] = "Workspaces"
    ACTIVATED_CARBON: Final[str] = "Activated Carbon"
    CHEMICAL: Final[str] = "Chemical Processing"


OPENAPI_TAGS: List[dict] = [
    {
        "name": Tags.CUSTOMER,
        "description": "Customer master data (OEMs, Tier-1 / Tier-2 buyers).",
    },
    {
        "name": Tags.PART,
        "description": "Part master (finished goods, sub-assemblies, raw).",
    },
    {
        "name": Tags.ORDER,
        "description": "Customer orders and order lines.",
    },
    {
        "name": Tags.PRODUCTION,
        "description": "Production orders derived from customer order lines.",
    },
    {
        "name": Tags.LOT,
        "description": (
            "Production lots. SUM(lot quantities) MUST equal "
            "production order quantity."
        ),
    },
    {
        "name": Tags.ROUTING,
        "description": (
            "Manufacturing routings and operations. Auto-loaded from part."
        ),
    },
    {
        "name": Tags.FEASIBILITY,
        "description": (
            "Material / machine / tool / workforce feasibility checks. "
            "Scheduling is only allowed when feasibility = READY."
        ),
    },
    {
        "name": Tags.SCHEDULING,
        "description": (
            "Production schedule. Gates the workflow between feasibility "
            "and work-order release."
        ),
    },
    {
        "name": Tags.WORK_ORDER,
        "description": (
            "Shop-floor work orders. Auto-generated from routing operations "
            "of a scheduled lot."
        ),
    },
    {
        "name": Tags.EXECUTION,
        "description": "Operation-level execution and parameter capture.",
    },
    {
        "name": Tags.PROCESS,
        "description": (
            "Reusable process library entries linked to routing operations."
        ),
    },
    {
        "name": Tags.DATA_CAPTURE,
        "description": (
            "Dynamic data capture templates, fields, and shop-floor submissions."
        ),
    },
    {
        "name": Tags.INSPECTION,
        "description": (
            "Quality inspection results. Required after operation completion."
        ),
    },
    {
        "name": Tags.NCR,
        "description": (
            "Non-Conformance Reports. Auto-created when an inspection fails."
        ),
    },
    {
        "name": Tags.DISPATCH,
        "description": (
            "Customer dispatch. Allowed only when all operations are "
            "complete, quality is passed, and no NCR is open."
        ),
    },
    {
        "name": Tags.TRACEABILITY,
        "description": (
            "End-to-end traceability (customer -> order -> production -> "
            "operations -> machines -> inspection -> NCR -> dispatch)."
        ),
    },
    {
        "name": Tags.OEE,
        "description": "Machine Overall Equipment Effectiveness (A x P x Q).",
    },
    {
        "name": Tags.MAINTENANCE,
        "description": "Maintenance events and downtimes.",
    },
    {
        "name": Tags.DASHBOARD,
        "description": "Cross-domain KPIs for operations dashboards.",
    },
    {
        "name": Tags.INTELLIGENCE,
        "description": (
            "Higher-order intelligence endpoints designed to feed future "
            "AI / SPARQL reasoning: 'Why is this lot blocked?', "
            "'Which machine caused delays?', 'Which orders are at risk?'."
        ),
    },
    {
        "name": Tags.ONTOLOGY,
        "description": (
            "Manufacturing ontology graph metadata (RDF / SPARQL ready)."
        ),
    },
    {
        "name": Tags.AUTH,
        "description": "Authentication and current-user profile (AWS Cognito).",
    },
    {
        "name": Tags.MES_CORE,
        "description": (
            "Industry-agnostic multi-tenant API backed by nyra_mes_core. "
            "Tenant context defaults to DEFAULT_TENANT_CODE until login is finalized."
        ),
    },
    {
        "name": Tags.TEMPLATE,
        "description": "Metadata-driven industry template catalog and capabilities.",
    },
    {
        "name": Tags.WORKSPACE,
        "description": "Tenant-scoped project/plant workspaces.",
    },
    {
        "name": Tags.ACTIVATED_CARBON,
        "description": (
            "Activated Carbon industry adapter — reuses common MES tables "
            "with capability-guarded routes."
        ),
    },
    {
        "name": Tags.CHEMICAL,
        "description": (
            "Chemical Processing industry adapter — batch reactor workflows "
            "over common MES tables with capability-guarded routes."
        ),
    },
]
