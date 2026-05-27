"""HTTP route handlers (FastAPI APIRouters).

Routes are thin layers that:
  - validate input via Pydantic schemas
  - delegate domain logic to ``app.services``
  - return Pydantic / SQLAlchemy responses
"""
