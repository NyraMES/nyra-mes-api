"""Ontology routes - expose the manufacturing relationship graph.

This is what future AI / SPARQL modules will consume:

  * ``GET /ontology/graph`` returns the JSON-LD-friendly relationship list.
  * ``GET /ontology/ttl`` returns Turtle for direct loading into a triple
    store (Apache Jena, GraphDB, Stardog, Blazegraph, ...).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.openapi_tags import Tags
from app.core.ontology import (
    CORE_TRIPLES,
    NAMESPACE,
    as_jsonld_context,
    as_turtle_classes,
)

router = APIRouter(prefix="/ontology", tags=[Tags.ONTOLOGY])


@router.get(
    "/graph",
    summary=(
        "Return the manufacturing ontology relationships as JSON-LD-ready "
        "subject/predicate/object triples"
    ),
)
def get_ontology_graph():
    return {
        "@context": as_jsonld_context(),
        "namespace": NAMESPACE,
        "triples": [
            {"subject": t.subject, "predicate": t.predicate, "object": t.object}
            for t in CORE_TRIPLES
        ],
        "count": len(CORE_TRIPLES),
    }


@router.get(
    "/ttl",
    response_class=PlainTextResponse,
    summary="Return the class-level ontology in Turtle (RDF) format",
)
def get_ontology_ttl():
    return as_turtle_classes()
