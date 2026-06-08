"""SQLAlchemy declarative base for the nyra_mes_core database.

Legacy models use ``app.db.base.Base`` against the original single-tenant DB.
All nyra_mes_core models use this separate base so metadata stays isolated.
"""

from sqlalchemy.orm import declarative_base

MesCoreBase = declarative_base()
