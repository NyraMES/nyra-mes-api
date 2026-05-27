"""Ontology registry for the Manufacturing Workflow Intelligence Platform.

The ontology captures the *semantic* manufacturing relationships that go
beyond foreign keys. This metadata is exposed at runtime so that future
modules can:

  * emit RDF / OWL triples (Turtle / JSON-LD) from live data
  * load the graph into a triple store (Apache Jena, GraphDB, Stardog, ...)
  * answer SPARQL queries (e.g. "which machines are part of routings that
    produce a part dispatched to customer X?")
  * power AI reasoning ("Why is this lot blocked?", "Which operations
    generate maximum NCR?", "Which orders are at risk?")

The relationships defined here MUST be preserved by every service / model
refactor. Adding new domain entities means adding the relevant triples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


NAMESPACE = "https://nyra.example.com/mes/ontology#"


@dataclass(frozen=True)
class OntologyTriple:
    """An (subject, predicate, object) class-level triple."""

    subject: str
    predicate: str
    object: str

    def as_turtle(self) -> str:
        return f"mes:{self.subject} mes:{self.predicate} mes:{self.object} ."


CORE_TRIPLES: Tuple[OntologyTriple, ...] = (
    # Demand chain
    OntologyTriple("Customer",          "places",             "CustomerOrder"),
    OntologyTriple("CustomerOrder",     "hasLine",            "CustomerOrderLine"),
    OntologyTriple("CustomerOrderLine", "for",                "Part"),
    OntologyTriple("CustomerOrderLine", "derivesInto",        "ProductionOrder"),

    # Production chain
    OntologyTriple("ProductionOrder",   "splitsInto",         "ProductionLot"),
    OntologyTriple("ProductionLot",     "requires",           "Machine"),
    OntologyTriple("ProductionLot",     "requires",           "Material"),
    OntologyTriple("ProductionLot",     "requires",           "Tool"),
    OntologyTriple("ProductionLot",     "requires",           "WorkforceRole"),

    # Routing chain
    OntologyTriple("Routing",           "definedFor",         "Part"),
    OntologyTriple("Routing",           "hasOperation",       "RoutingOperation"),
    OntologyTriple("RoutingOperation",  "requires",           "Material"),
    OntologyTriple("RoutingOperation",  "runsOn",             "Machine"),

    # Scheduling / execution
    OntologyTriple("ProductionLot",     "scheduledAs",        "ProductionSchedule"),
    OntologyTriple("ProductionSchedule","assignsMachine",     "Machine"),
    OntologyTriple("ProductionSchedule","releasesAs",         "WorkOrder"),
    OntologyTriple("WorkOrder",         "executes",           "RoutingOperation"),
    OntologyTriple("WorkOrder",         "producedBy",         "ProductionLot"),

    # Quality chain
    OntologyTriple("WorkOrder",         "inspectedBy",        "InspectionResult"),
    OntologyTriple("InspectionResult",  "evaluates",          "InspectionParameter"),
    OntologyTriple("InspectionResult",  "creates",            "NCR"),
    OntologyTriple("NCR",               "documents",          "Defect"),

    # Dispatch / traceability
    OntologyTriple("ProductionLot",     "dispatchedThrough",  "Dispatch"),
    OntologyTriple("Dispatch",          "deliveredTo",        "Customer"),
    OntologyTriple("Dispatch",          "closesOrder",        "CustomerOrder"),
    OntologyTriple("ProductionLot",     "tracedBy",           "TraceabilityClosure"),

    # OEE / maintenance
    OntologyTriple("Machine",           "reports",            "OEEDailySummary"),
    OntologyTriple("Machine",           "experiences",        "MachineDowntime"),
    OntologyTriple("Machine",           "undergoes",          "MaintenanceEvent"),
)


def relations_for(entity: str) -> List[OntologyTriple]:
    """Return all triples whose subject is ``entity``."""
    return [t for t in CORE_TRIPLES if t.subject == entity]


def relations_to(entity: str) -> List[OntologyTriple]:
    """Return all triples whose object is ``entity``."""
    return [t for t in CORE_TRIPLES if t.object == entity]


def as_jsonld_context() -> Dict[str, str]:
    """Minimal JSON-LD context for future SPARQL / RDF generation."""
    return {
        "@vocab": NAMESPACE,
        "mes": NAMESPACE,
    }


def as_turtle_classes() -> str:
    """Return all triples in Turtle syntax (class-level, no instances)."""
    lines = [
        f"@prefix mes: <{NAMESPACE}> .",
        "",
        *(t.as_turtle() for t in CORE_TRIPLES),
    ]
    return "\n".join(lines)
