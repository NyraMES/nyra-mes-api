"""Chemical Processing industry constants — process flow and reactor parameter catalog."""

from __future__ import annotations

from app.schemas.mes_core.schemas import ChemReactorParameterDefinition

FINISHED_PRODUCT_CODE = "CHEM-SOLVENT-A"
ROUTING_CODE = "RT-CHEM-SOLVENT-A-V1"

REACTOR_PARAMETER_DEFINITIONS: list[ChemReactorParameterDefinition] = [
    ChemReactorParameterDefinition(key="reactor_temp_c", label="Reactor Temp (°C)", unit="°C"),
    ChemReactorParameterDefinition(key="pressure_bar", label="Pressure (bar)", unit="bar"),
    ChemReactorParameterDefinition(key="agitator_rpm", label="Agitator (RPM)", unit="RPM"),
    ChemReactorParameterDefinition(key="feed_rate_kg_h", label="Feed Rate (kg/h)", unit="kg/h"),
    ChemReactorParameterDefinition(key="ph", label="pH", unit=""),
    ChemReactorParameterDefinition(
        key="batch_time_min", label="Batch Time (min)", unit="min"
    ),
]

# Manufacturing sequence shown on the dashboard (capability optional for mes-core gates).
CHEM_PROCESS_FLOW: list[tuple[int, str, str, str | None]] = [
    (1, "Raw Material Receipt", "raw-material-receipt", "CHEM_RAW_MATERIAL_RECEIPT"),
    (2, "Raw Material QC", "raw-material-qc", "CHEM_RAW_MATERIAL_QC"),
    (3, "Feasibility Gate", "feasibility", None),
    (4, "Reactor Charge", "reactor-charge", "CHEM_REACTOR_CHARGE"),
    (5, "Lot Routing", "routing", None),
    (6, "Execution", "execution", None),
    (7, "Reactor Parameters", "reactor-parameters", "CHEM_REACTOR_PARAMETERS"),
    (8, "Blend & Formulation", "blend-formulation", "CHEM_BLEND_FORMULATION"),
    (9, "Batch QC", "batch-qc", "CHEM_BATCH_QC"),
    (10, "Batch Analytics", "batch-analytics", "CHEM_BATCH_ANALYTICS"),
    (11, "Dispatch", "dispatch", None),
]

CHEM_PROCESS_COUNT_KEYS: dict[str, str] = {
    "routing": "ROUTING",
    "feasibility": "FEASIBILITY",
    "execution": "EXECUTION",
    "dispatch": "DISPATCH",
}
