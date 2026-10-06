"""nyra_mes_core SQLAlchemy models — registered separately from legacy models."""

from app.models.mes_core.execution import (
    OperationExecution,
    ParameterReading,
    QualityCheck,
    QualityResult,
    TripleStoreStaging,
)
from app.models.mes_core.master import (
    Customer,
    Supplier,
    Equipment,
    OperationResourceRequirement,
    Product,
    Resource,
    Routing,
    RoutingOperation,
    RoutingOperationParameter,
)
from app.models.mes_core.platform import (
    AppUser,
    Capability,
    IndustryCapability,
    IndustryTemplate,
    ProjectWorkspace,
    Tenant,
    UserProjectAccess,
    UserTenantAccess,
)
from app.models.mes_core.transaction import (
    CustomerOrder,
    CustomerOrderLine,
    Dispatch,
    FeasibilityCheck,
    ProductionLot,
    ProductionOrder,
)

__all__ = [
    "AppUser",
    "Capability",
    "Customer",
    "Supplier",
    "CustomerOrder",
    "CustomerOrderLine",
    "Dispatch",
    "Equipment",
    "FeasibilityCheck",
    "IndustryCapability",
    "IndustryTemplate",
    "OperationExecution",
    "OperationResourceRequirement",
    "ParameterReading",
    "Product",
    "ProductionLot",
    "ProductionOrder",
    "ProjectWorkspace",
    "QualityCheck",
    "QualityResult",
    "Resource",
    "Routing",
    "RoutingOperation",
    "RoutingOperationParameter",
    "Tenant",
    "TripleStoreStaging",
    "UserProjectAccess",
    "UserTenantAccess",
]
