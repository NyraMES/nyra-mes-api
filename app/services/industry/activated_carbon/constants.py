"""Activated Carbon industry constants — process flow and kiln parameter catalog."""

from __future__ import annotations

from app.schemas.mes_core.schemas import AcKilnParameterDefinition

# Finished product linked to RT-AC-8x30-V1 in nyra_sam_carbons_demo_tenant.sql
FINISHED_PRODUCT_CODE = "AC-GRAN-8x30"
ROUTING_CODE = "RT-AC-8x30-V1"

KILN_PARAMETER_DEFINITIONS: list[AcKilnParameterDefinition] = [
    AcKilnParameterDefinition(key="zone1_temp_c", label="Zone 1 Temp (°C)", unit="°C"),
    AcKilnParameterDefinition(key="zone2_temp_c", label="Zone 2 Temp (°C)", unit="°C"),
    AcKilnParameterDefinition(key="steam_flow_kg_h", label="Steam Flow (kg/h)", unit="kg/h"),
    AcKilnParameterDefinition(
        key="residence_time_min", label="Residence Time (min)", unit="min"
    ),
    AcKilnParameterDefinition(key="o2_pct", label="O₂ (%)", unit="%"),
    AcKilnParameterDefinition(key="kiln_temp_c", label="Kiln Temp (°C)", unit="°C"),
    AcKilnParameterDefinition(key="pressure_bar", label="Pressure (bar)", unit="bar"),
]

# Manufacturing sequence shown on the dashboard (capability optional for mes-core gates).
AC_PROCESS_FLOW: list[tuple[int, str, str, str | None]] = [
    (1, "Raw Material Inward", "raw-material-inward", "AC_RAW_MATERIAL_INWARD"),
    (2, "Raw Material QC", "raw-material-qc", "AC_RAW_MATERIAL_QC"),
    (3, "Kiln Feed", "kiln-feed", "AC_KILN_FEED"),
    (4, "Feasibility Gate", "feasibility", None),
    (5, "Lot Routing", "routing", None),
    (6, "Execution", "execution", None),
    (7, "Kiln Parameters", "kiln-parameters", "AC_HOURLY_KILN_PARAMETERS"),
    (8, "Screening", "screening", "AC_SCREENING"),
    (9, "Quality Testing", "quality-testing", "AC_QUALITY_TESTING"),
    (10, "Yield Analysis", "yield-analysis", "AC_YIELD_ANALYSIS"),
    (11, "Dispatch", "dispatch", None),
]

# Count keys for steps without an industry capability code.
AC_PROCESS_COUNT_KEYS: dict[str, str] = {
    "routing": "ROUTING",
    "feasibility": "FEASIBILITY",
    "execution": "EXECUTION",
    "dispatch": "DISPATCH",
}
