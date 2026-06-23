# Activated Carbon MES — Schema Mapping Report

**Database:** `nyra_mes_core` (PostgreSQL)  
**Industry:** `ACTIVATED_CARBON` (`industry_code` = `activated_carbon` maps to `industry_template_code` = `ACTIVATED_CARBON`)  
**Date:** 2026-06-07  
**Scope:** Optional additional process steps, configurable parameters, execution metadata, traceability triples — **additive only** (no DROP/rename/remove).

### Change boundary (strict)

| In scope | Out of scope |
|----------|--------------|
| `nyra_mes_core` PostgreSQL schema (`core`, `mst`, `exec`, `trn`, `qms`, `kg`, `template`, `reporting`) | Legacy `oemauto` / OEM-only database |
| SQL under `database/migrations/` and `database/docs/` | `nyra-mes-ui` |
| Additive columns, views, functions, seed rows | `nyra-mes-api` application code (models, routes, services) — **until DB is applied on a non-production copy** |
| Local / dev database apply by operator | Live RDS, testbed, SAM Carbons production — **do not run automatically** |

---

## Executive Summary

| Category | Verdict |
|----------|---------|
| Core routing & execution | **Reuse** — `mst.routing`, `mst.routing_operation`, `mst.routing_operation_parameter`, `exec.operation_execution`, `exec.parameter_reading` |
| Batch / lot tracking | **Reuse** — `trn.production_lot` |
| Quality & dispatch | **Reuse** — `qms.quality_check`, `qms.quality_result`, `trn.dispatch` |
| Finished goods | **Reuse** — `trn.production_lot` + `trn.dispatch.finished_goods_lot_no` |
| Scrap | **Extend** — `exec.operation_execution` (`status=SCRAPPED`, `metadata.scrap_quantity`) — no dedicated scrap table |
| Ontology (entity/relation) | **Substitute** — `kg.triple_store_staging` (no `ontology_entity` / `ontology_relation` in mes_core) |
| Optional AC process steps | **Extend + seed** — new columns on `mst.routing_operation` + optional template operations on `AC_STANDARD_PROCESS` |
| Reporting | **Additive views** — new `reporting` schema views only |

**Default flow preserved:** Raw Material Inward → Kiln Feed → Kiln Processing → Screening → Finished Goods → Dispatch (workspace routes and mandatory template ops unchanged).

**Optional flow supported:** … → Screening → **Optional Additional Process** (Inspection / Reprocessing / Drying / Additional Cooling / Customer-specific) → Finished Goods → Dispatch.

---

## Concept Existence Check

| Requested concept | Exists in mes_core? | Actual object | Used by AC today? |
|-------------------|----------------------|---------------|-------------------|
| `routing` | Yes | `mst.routing` | Yes |
| `routing_operation` | Yes | `mst.routing_operation` | Yes |
| `operation_parameter` | Yes (renamed) | `mst.routing_operation_parameter` | Yes (routing builder) |
| `operation_parameter_value` | Yes (renamed) | `exec.parameter_reading` | Yes (kiln/QC capture) |
| `work_order` | Yes (renamed) | `exec.operation_execution` | Yes |
| `production_lot` | Yes | `trn.production_lot` | Yes |
| `quality_result` | Yes | `qms.quality_result` (+ `qms.quality_check`) | Yes |
| `finished_goods` | Yes (composite) | `trn.production_lot` + `trn.dispatch.finished_goods_lot_no` | Yes |
| `dispatch` | Yes | `trn.dispatch` + `qms.quality_check` (type=DISPATCH) | Yes |
| `scrap` | Partial | `exec.operation_execution` (`SCRAPPED`, metadata) | Partial |
| `ontology_entity` | No | — (legacy OEM `ref.ontology_*` only) | No |
| `ontology_relation` / `ontology_relationship` | No | — | No |
| KG triples | Yes | `kg.triple_store_staging` | Minimal |

**AC template route `AC_STANDARD_PROCESS` (migration 004):** 11 mandatory operations including Raw Material Inward (10), Kiln Feed (40), Kiln Activation (50), Cooling (60), Screening (70), FG Packing (100), Dispatch (110). Optional steps are **added** at sequences 75–79 without altering existing rows.

---

## Schema Mapping — Requirement Matrix

| Requirement | Existing Table | Existing Column(s) | Gap | Proposed Action |
|-------------|----------------|-------------------|-----|-----------------|
| **Tenant scope** | `core.tenant` | `tenant_id` | None | Reuse FK on all operational tables |
| **Industry = activated_carbon** | `mst.routing`, `mst.routing_operation` | `industry_template_code` | No `industry_code` alias column | Reuse `industry_template_code = 'ACTIVATED_CARBON'`; document mapping |
| **Process Step** | `mst.routing_operation` | `operation_code`, `operation_name`, `metadata.process_step` | None for identity | Reuse; seed optional ops with distinct `process_step` values |
| **Process Sequence** | `mst.routing_operation` | `operation_sequence`, `operation_seq` | None | Reuse; optional ops at seq 75–79 (after Screening 70, before Grade Sep 80) |
| **Mandatory step flag** | `mst.routing_operation` | — | No explicit flag | **ADD** `is_mandatory BOOLEAN NOT NULL DEFAULT TRUE`; backfill existing rows TRUE |
| **Optional step flag** | `mst.routing_operation` | — | No explicit flag | **ADD** `is_optional BOOLEAN NOT NULL DEFAULT FALSE`; seed optional ops TRUE |
| **Active / inactive step** | `mst.routing_operation` | `is_active` | None | Reuse |
| **Insert-after anchor (optional flow)** | `mst.routing_operation` | `metadata` | No dedicated anchor column | **ADD** `insert_after_operation_code VARCHAR(64)` nullable; optional ops → `'AC-OP-SCREENING'` |
| **Process Parameter definition** | `mst.routing_operation_parameter` | `parameter_code`, `data_type`, `is_mandatory`, `is_active`, `min_value`, `max_value`, `unit` | None for core definition | Reuse; seed parameters for optional ops |
| **Parameter types** (text, number, date, boolean, dropdown, remarks) | `mst.routing_operation_parameter` | `data_type` (free VARCHAR) | No enum constraint; no dropdown options | **ADD** CHECK `chk_parameter_data_type`; **ADD** `dropdown_options JSONB`; normalize legacy values |
| **Parameter report visibility** | `mst.routing_operation_parameter` | — | No flag | **ADD** `show_in_report BOOLEAN NOT NULL DEFAULT TRUE` |
| **Process Parameter Value** | `exec.parameter_reading` | `reading_value`, `reading_text`, `parameter_code`, `recorded_at` | No FK to parameter definition | **ADD** nullable `routing_operation_parameter_id` FK |
| **Process Execution / Work Order** | `exec.operation_execution` | `execution_code`, `production_lot_id`, `routing_operation_id` | None | Reuse |
| **Execution status** | `exec.operation_execution` | `status` CHECK (`NOT_STARTED`, `IN_PROGRESS`, `COMPLETED`, `HOLD`, `SCRAPPED`) | None | Reuse |
| **Operator** | `exec.operation_execution` | `metadata` (ad hoc) | No first-class column | **ADD** nullable `operator_code VARCHAR(64)` |
| **Start / end time** | `exec.operation_execution` | `started_at`, `completed_at` | None | Reuse |
| **Execution remarks** | `exec.operation_execution` | `metadata` (ad hoc) | No first-class column | **ADD** nullable `remarks TEXT` |
| **Parameter operator / recorder** | `exec.parameter_reading` | `metadata` | No first-class column | **ADD** nullable `recorded_by VARCHAR(128)` |
| **Batch tracking** | `trn.production_lot` | `lot_code`, `metadata` | No `kiln_batch` table | Reuse `production_lot`; kiln context in lot metadata / equipment on execution |
| **Quality result** | `qms.quality_result` | full row | None | Reuse for QC chain |
| **Finished goods bag / lot** | `trn.production_lot`, `trn.dispatch` | `finished_goods_lot_no`, `bag_count` | None | Reuse |
| **Dispatch** | `trn.dispatch` | full row | None | Reuse |
| **Scrap material** | `exec.operation_execution` | `status`, `metadata` | No scrap dispatch table | Reuse execution + triple predicate `sold as` → Scrap Dispatch |
| **Ontology Entity** | — | — | Not in mes_core | Represent subjects/objects as URI strings in `kg.triple_store_staging` |
| **Ontology Relation** | — | — | Not in mes_core | Represent predicates as URI strings in `kg.triple_store_staging` |
| **Traceability triples** | `kg.triple_store_staging` | `subject_uri`, `predicate_uri`, `object_uri`, `source_table`, `source_id` | Not systematically populated | **ADD** function `kg.upsert_traceability_triple()` + **ADD** view `reporting.v_ac_lot_traceability` |
| **Standard predicate catalog** | — | — | No ontology tables | **ADD** view `reporting.v_ac_standard_predicates` (no new table) |
| **Process execution reporting** | — | — | No reporting views in repo | **ADD** view `reporting.v_ac_process_execution` |
| **Raw material parameter profiles** | `template.raw_material_parameter_profile` | full row | Not wired in all UIs | Reuse (no schema change) |

---

## Preferred Reuse Mapping (Confirmed)

| Business concept | mes_core mapping | Notes |
|------------------|------------------|-------|
| Process Step | `mst.routing_operation` | `metadata.process_step` = business step code |
| Process Sequence | `mst.routing_operation.operation_sequence` / `operation_seq` | Unique per `(tenant_id, routing_id)` |
| Process Parameter | `mst.routing_operation_parameter` | Per-operation capture definition |
| Process Parameter Value | `exec.parameter_reading` | Linked to `exec.operation_execution` |
| Process Execution | `exec.operation_execution` | Serves as work order |
| Batch Tracking | `trn.production_lot` | Lot-centric traceability |
| Ontology Entity | URI in `kg.triple_store_staging.subject_uri` / `object_uri` | e.g. `urn:nyra:ac:lot:{lot_code}` |
| Ontology Relation | URI in `kg.triple_store_staging.predicate_uri` | e.g. `urn:nyra:predicate:produces` |

---

## Optional Process Steps — Seed Plan (AC_STANDARD_PROCESS)

All rows use `ON CONFLICT DO NOTHING`. Existing mandatory operations are **not** updated.

| operation_code | operation_seq | process_step | is_mandatory | is_optional | insert_after |
|----------------|---------------|--------------|--------------|-------------|--------------|
| `AC-OP-OPT-INSPECTION` | 75 | `OPTIONAL_INSPECTION` | FALSE | TRUE | `AC-OP-SCREENING` |
| `AC-OP-OPT-REPROCESSING` | 76 | `OPTIONAL_REPROCESSING` | FALSE | TRUE | `AC-OP-SCREENING` |
| `AC-OP-OPT-DRYING` | 77 | `OPTIONAL_DRYING` | FALSE | TRUE | `AC-OP-SCREENING` |
| `AC-OP-OPT-ADDITIONAL-COOLING` | 78 | `OPTIONAL_COOLING` | FALSE | TRUE | `AC-OP-SCREENING` |
| `AC-OP-OPT-CUSTOMER-PROCESS` | 79 | `OPTIONAL_CUSTOMER_PROCESS` | FALSE | TRUE | `AC-OP-SCREENING` |

> **Note:** Template already has mandatory `AC-OP-COOLING` at sequence 60 (post-kiln). `AC-OP-OPT-ADDITIONAL-COOLING` is a distinct **optional** post-screening step — no rename or removal of the existing cooling step.

---

## Triplet Ontology — Traceability Chain

| Subject | Predicate | Object | Source for triple materialization |
|---------|-----------|--------|-----------------------------------|
| Supplier | `urn:nyra:predicate:supplies` | Raw Material Batch | `trn.production_lot.metadata` / inward execution |
| Raw Material Batch | `urn:nyra:predicate:issued_to` | Kiln | Kiln feed `exec.operation_execution` |
| Kiln Batch | `urn:nyra:predicate:produces` | Finished Goods Batch | Kiln activation execution → lot |
| Routing Operation | `urn:nyra:predicate:captures` | Operation Parameter | `mst.routing_operation_parameter` |
| Work Order / Process Execution | `urn:nyra:predicate:executes` | Routing Operation | `exec.operation_execution` |
| Finished Goods Bag | `urn:nyra:predicate:dispatched_to` | Customer | `trn.dispatch` |
| Scrap Material | `urn:nyra:predicate:sold_as` | Scrap Dispatch | `exec.operation_execution` (SCRAPPED) |

Full chain: **Supplier → Raw Material Inward → Kiln Feed → Kiln Processing → Optional Process → Quality → Finished Goods Bag → Dispatch**

Implementation: `kg.upsert_traceability_triple()` writes to `kg.triple_store_staging` with `source_table` / `source_id` provenance. No changes to legacy OEM ontology tables.

---

## Objects Created by Migration 006 (Additive Only)

| Object | Type | Purpose |
|--------|------|---------|
| `mst.routing_operation.is_mandatory` | Column | Distinguish mandatory vs optional steps |
| `mst.routing_operation.is_optional` | Column | Flag optional post-screening steps |
| `mst.routing_operation.insert_after_operation_code` | Column | Anchor optional steps after Screening |
| `mst.routing_operation_parameter.dropdown_options` | Column | Dropdown parameter values |
| `mst.routing_operation_parameter.show_in_report` | Column | Report visibility |
| `exec.operation_execution.operator_code` | Column | Operator on execution |
| `exec.operation_execution.remarks` | Column | Execution remarks |
| `exec.parameter_reading.routing_operation_parameter_id` | Column + FK | Link reading to parameter definition |
| `exec.parameter_reading.recorded_by` | Column | Operator on parameter capture |
| `reporting` schema | Schema | Isolated reporting views |
| `reporting.v_ac_standard_predicates` | View | Standard AC predicate URIs |
| `reporting.v_ac_process_execution` | View | Lot execution + operation + status |
| `reporting.v_ac_lot_traceability` | View | Lot-level triple chain |
| `kg.upsert_traceability_triple()` | Function | Idempotent triple upsert |
| Optional AC template ops + parameters | Seed data | ON CONFLICT DO NOTHING |

**No new operational tables.** No drops, renames, or deletes.

---

## Migration Reference

Apply after migrations 003–005:

```bash
psql -d nyra_mes_core -f database/migrations/006_ac_optional_process_and_ontology_enhancement.sql
```
