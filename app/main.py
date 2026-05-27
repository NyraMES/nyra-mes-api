"""FastAPI application entrypoint.

Composes the Manufacturing Workflow Intelligence Platform:

  * eager model import so ``Base.metadata`` is fully populated
  * domain exception -> JSON handler
  * CORS for the React/Vite frontend
  * routers grouped by manufacturing-workflow tag
  * optional AWS Cognito JWT + role-based access per domain router
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  - ensure all SQLAlchemy models are registered

from app.core.auth import require_router_access
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.openapi_tags import OPENAPI_TAGS

from app.routes.auth import router as auth_router
from app.routes.customer import router as customer_router
from app.routes.part import parts_router, router as part_router
from app.routes.order import router as order_router
from app.routes.production import router as production_router
from app.routes.lot import router as lot_router
from app.routes.routing import router as routing_router
from app.routes.resource import router as resource_router
from app.routes.feasibility import router as feasibility_router
from app.routes.schedule import router as schedule_router
from app.routes.workorder import router as workorder_router
from app.routes.inspection import router as inspection_router
from app.routes.ncr import router as ncr_router
from app.routes.dispatch import router as dispatch_router
from app.routes.traceability import router as traceability_router
from app.routes.oee import router as oee_router
from app.routes.maintenance import router as maintenance_router
from app.routes.dashboard import router as dashboard_router
from app.routes.data_capture import router as data_capture_router
from app.routes.ontology import router as ontology_router
from app.routes.process import router as process_router

DOMAIN_ROUTERS = [
    (customer_router, "customer"),
    (part_router, "part"),
    (parts_router, "part"),
    (order_router, "order"),
    (production_router, "production"),
    (lot_router, "lot"),
    (routing_router, "routing"),
    (resource_router, "resource"),
    (feasibility_router, "feasibility"),
    (schedule_router, "schedule"),
    (workorder_router, "workorder"),
    (process_router, "process"),
    (data_capture_router, "data_capture"),
    (inspection_router, "inspection"),
    (ncr_router, "ncr"),
    (dispatch_router, "dispatch"),
    (traceability_router, "traceability"),
    (oee_router, "oee"),
    (maintenance_router, "maintenance"),
    (dashboard_router, "dashboard"),
    (ontology_router, "ontology"),
]


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=settings.app_description,
    openapi_tags=OPENAPI_TAGS,
)


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = FastAPI.openapi(app)
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "CognitoBearer"
    ] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "AWS Cognito access or ID token",
    }
    if settings.auth_enabled:
        schema["security"] = [{"CognitoBearer": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


register_exception_handlers(app)

app.include_router(auth_router)

for router, domain in DOMAIN_ROUTERS:
    app.include_router(
        router,
        dependencies=[require_router_access(domain)],
    )


@app.get("/", tags=["Health"], summary="Liveness check")
def root():
    return {
        "message": f"{settings.app_name} running",
        "version": settings.app_version,
        "docs": "/docs",
        "redoc": "/redoc",
        "ontology": "/ontology/graph",
        "auth_enabled": settings.auth_enabled,
    }


@app.get("/health", tags=["Health"], summary="Health probe")
def health():
    return {"status": "ok", "auth_enabled": settings.auth_enabled}
