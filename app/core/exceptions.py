"""Domain exceptions used across the service layer.

Services raise these *domain* exceptions; the route layer translates them
into HTTP responses via :func:`register_exception_handlers`. Keeping domain
logic free of HTTP concerns is what makes the services unit-testable and
reusable (e.g. for future SPARQL-driven AI reasoning).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Base class for all domain-layer errors."""

    status_code: int = 400

    def __init__(
        self,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"detail": self.message, "context": self.details}


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    status_code = 409


class ValidationError(DomainError):
    status_code = 400


class UnauthorizedError(DomainError):
    status_code = 401


class ForbiddenError(DomainError):
    status_code = 403


class WorkflowError(DomainError):
    """Raised when a workflow transition is not allowed.

    Example: scheduling attempted while feasibility != READY,
    or dispatch attempted with an open NCR.
    """

    status_code = 422


class InternalError(DomainError):
    """Unexpected internal error - the service rolled back and gave up."""

    status_code = 500


def register_exception_handlers(app: FastAPI) -> None:
    """Attach JSON exception handlers for all :class:`DomainError` types."""

    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        payload: Dict[str, Any] = {"detail": exc.message}
        if exc.details:
            payload["context"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=payload)
