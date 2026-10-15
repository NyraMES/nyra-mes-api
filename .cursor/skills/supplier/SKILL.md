---
name: supplier
description: >-
  Activated Carbon supplier inward, raw material release, and post-release
  activation flow (execution with kiln feed first) for SAM_CARBONS / GR Carbons.
  Use when the user mentions /supplier, supplier receipts, gate receipt, RMS bags,
  crusher performance, RM outward, kiln feed, lot routing, triplet ontology, or
  shop-floor execution after release.
---

# Supplier — AC inbound through activation

## Scope rule (important)

**Keep the triplet ontology.** Inward and lot subjects stay as-is. Do not invent
parallel capture screens on analytics.

**Raw Material tabs (current):**

```
Raw Material
  1 · Gate receipt → 2 · Inbound prep → 3 · Release to Production → 4 · Reports
       ↓
Execution         (/execution — kiln feed first; routing auto after Load)
                  Activation includes Kiln Parameters (hourly readings)
                  Activation + Post-activation each have a Reports tab
```

Reports are read-only (process dropdown, on-screen details, bar/pie, Excel). They do not capture shop-floor data and do not change triplet subjects. Raw Material: gate / RMS inward (user generates bags by KG) / lab (volatility) / debit note / RMS Outward / release. The dashboard Raw Material section lists raised debit notes (count, value, supplier). Activation: kiln feed / kiln output / destoning / destoning In Stock. Post-activation: screening through blending, then In Stock. There is no Finished Goods step.

**Dashboard by login.** Admin, supervisor, and viewer keep the plant dashboard. An activation, post-activation, quality, or operator engineer sees their own saved checks for the current week as a line against the top performer in those same checks, and the bags they saved on the selected day. A login that covers more than one of activation, post-activation, and quality gets a separate line for each: activation is kiln output and destoning bags that person created, post-activation is the later process bags they created, and quality is kiln output quality, destoning bag quality, and the post-activation quality tab. Each line is compared with the top performer in that same work. An RMS-only engineer sees a Monday–Sunday line of our-weight kilograms received, and the day's inward orders (inward code, next step, our weight). That login does not get execution, dispatch, bag traceability, plant reports, admin, or masters. Supplier name, code, and value are for the manager, planner, plant admin, Nyra, and Security. The Gate receipt tab is for the supervisor and Security. An RMS login does not get that tab. RMS, activation, post-activation, quality, operator, and viewer do not see supplier identity. User performance on Activation and Post-activation reports stays available to the supervisor.

**Shop-floor identity is the inward order (`ORD-*`)** until inward/release is complete.
Do not show customer PO or `LOT-AC-*` to plant users. They associate “lot” with RMS outward bags.
**Customer PO is not recorded.** Activation demand is an Admin work order (`WO-AC-*`: grade + CTC + KG). Release still creates production lots for bag inventory and triplets.

**Raw Material QC is not required.** Completing RMS Outward auto-marks the inward
`QC_PASSED` so release can proceed. Ontology URIs for QC remain for trace.

**Feasibility Gate is not required.** Released lots can be loaded on Execution
immediately. `/feasibility` redirects to execution. Ontology URIs for
`feasibilityChecked` remain for trace.

**Lot Routing is not a separate screen.** `/routing` and `/kiln-feed` redirect
to `/execution`. Kiln feed Load uses the Admin work order; routing executions are still created after the first load.

Redirects: `/raw-material-inward` → `?tab=inward`; `/raw-material-qc` → `?tab=release`;
`/feasibility`, `/kiln-feed`, `/routing` → `/execution`.

After release, `AcReleaseToProductionPanel` links to **Execution**.

## Inbound prep (after gate)

| Step | Code | Rules |
|------|------|-------|
| Bag generation | `IN-RMS-BAG` | Separate capture on **Inbound prep**, not on Gate receipt. The RMS engineer enters each bag KG and clicks **Generate bag** (`RI_BAG_*`). No auto-split. The supervisor does not enter bags. If the bag total is short of our weight, confirm, then finish the step. |
| Lab | `IN-LAB` | Quality check on Inbound prep. Only the Quality login records moisture, dust, volatility, and approve/deny. RMS and the supervisor do not. Lab values stay visible after save. The supervisor raises a **debit note** when our weight is short or moisture is above the plant threshold. Quality and RMS do not. Optional — does not block RMS Outward. Deny stops this inward. |
| RMS Outward | `IN-RM-OUT` | The RMS engineer, after Lab. Rotary output bags. At least one line is required (a grade, Unburnt, or Stones). Button **RMS outward complete**, then Release to production. Quality and the supervisor do not record this step. |

Admin (one menu): Users, Suppliers, Destoner CTC allocation, Kiln parameters, Work orders, Stock Reallocation. Users have a nickname stored on the plant user record (not Cognito). It must be unique in the plant, ignoring case. Screens show the nickname. Sign-in and shop-floor “set by” still store the user id. No Customer tab and no Kiln CTC master. Destoner CTC allocation: daily CTC only per destoner (`GET/PUT /api/activated-carbon/destoning/daily-ctc`). Kiln parameters: standing setpoints per kiln (`GET/PUT /api/activated-carbon/kiln/setpoints`) — residence time, temperatures, steam, oxygen, pressure. They stay until changed. Residence time scales Machine utilization designed kg (`monthly capacity × 60 ÷ residence minutes`) and the kiln cycle clock. Work orders: grade + CTC + KG (`GET/POST /api/activated-carbon/work-orders`, codes `WO-AC-*`). Destoning quality is stones Yes/No. Masters **Process rules** (`GET/PUT /api/activated-carbon/masters/process-rules`): 25/500 kg, moisture 20%, CTC 1 decimal. Masters **Mesh configuration** (`GET/PUT /api/activated-carbon/masters/mesh-grade-map`): A–E. Destoning machines live on Masters plant-resources; four destoners `RES-DESTON-01..04` are auto-ensured. Bag serial dates (`DS_`, `KA_`/`KB_`, post-activation) and the destoning CTC day use the customer timezone on `core.tenant.timezone`. GR Carbons is `Asia/Kolkata`.

Rotary inventory and RM outward splits are **per-tenant admin** (`Masters → Inbound settings`,
`GET/PUT /api/activated-carbon/inbound-admin`). GR Carbons is seeded with Rotary A/B and:

- -20 1st Stage - Rotary A
- Grade 1st stage - Rotary A
- -20 2nd Stage - Rotary B
- Grade 2nd stage - Rotary B
- Stones
- Unburnt

## Gate receipt required fields

DC number, supplier weight (KG), our weight (KG). Our weight is received quantity.

## Post-release activation flow

| Step | UI | Notes |
|------|-----|-------|
| Execution | `AcExecutionPage` | Tabs on top. Kiln Feed first. **Kiln feed is work-order based**: pick `WO-AC-*` by work order number, then a kiln. A kiln can hold more than one open work order when grade and CTC are the same; a different grade or CTC waits until that feed is covered by output. Load released RO bags (no product grade; Unburnt and Stones stay off the kiln). A bag already loaded into a kiln is not offered again. A work order leaves the kiln work-order list once kiln output kilograms cover its quantity. Kiln output is weight only, recorded by the activation engineer. Kiln output quality, destoning bag quality, and the post-activation quality tab are recorded by Quality. An activation or post-activation login does not open those tabs. The bag is tagged to an open work order on that kiln that still has feed left. Feed can be continuous — load and output run together. **Running kiln balance** is In (all loads so far) − Out (all output so far); output cannot exceed what is still in the kiln. If nothing is loaded, output is blocked. Kiln output QC measures actual CTC: match counts toward WO fulfilled kg; mismatch keeps the bag for destoning by measured CTC and does not fulfill the WO. Destoning Load bag matches destoner CTC. Destoning quality is a **stones check**: stones Yes returns the bag to destoning; No sends it to **Screening**. Destoning does not go to In Stock. **Screening** chooses mesh A–E before Load bag. The mesh stays until the loader is empty, then tags only the grades on that mesh. Screening output cannot exceed the current loaded kg (In − Out). Work-order CTC is displayed on screening / destoning quality / post-activation quality and is not re-entered there. The loader and the waiting list stay on one work order: the work order on the loader, otherwise the oldest bag still waiting. Screening, crushing, de-dusting, de-magnetisation, blending, and the quality tab list the tags saved on the current plant day, including every work order saved that day. Earlier days stay off those lists. The loader still shows the bags on the machine. Post-activation quality destination (De-dusting, Crushing, …) puts that bag on the next process **Waiting to load** list. Post-activation quality can set destination to **In Stock**. The work order (`WO-AC-*`) is copied from kiln feed through destoning, screening, later post-activation bags, and In Stock. |

## Triplet ontology (kg.triple_store_staging)

**Inward steps**: subject `urn:nyra:ac:inward:{order_code}` — receipt, lab, bags, crusher, RM outward.
Bag nodes: `urn:nyra:ac:inwardBag:{bag_code}`.

**Post-release steps** (lot-scoped): subject `urn:nyra:ac:lot:{lot_code}` — kiln feed, routing, screening, grade separation, quality testing, dispatch.

Reference: `acTripletOntology.js` (UI), `adapter.py` / `inbound_workflow.py` / `inbound_execution.py` (API).

## Domain rules

- **Inward receipt**: supplier, DC, supplier weight (KG), our weight (KG). Our weight defaults to 0 and must be > 0 and ≤ supplier weight.
- **Debit note**: optional, after lab only. Eligible when our weight < supplier weight or moisture > plant threshold. The supplier name is shown only to the manager and supervisor. User enters the debit note value. Code `DN-AC-*` on inward metadata. Does not block RMS Outward.
- **Units**: moisture, dust, volatility = **%**; all weights = **KG**. Historical AD remains on old triples.
- **RMS bags** are created after gate: user enters KG and clicks **Generate bag**, then keeps adding. If bag total is short of our weight, confirm before Lab. Historical 25 kg / `repack_500` remain for older inwards. **Outward bags** carry the admin split label as grade.
- **Post-release** = Execution (kiln feed first; remaining process-map steps as any-order tabs). Kiln feed Load bags lists released RO bags (no product grade; Unburnt and Stones stay off the kiln). Work order grade is demand only, not matched to RO.
- **Customer PO is not recorded** (menu removed; `/customer-sales` redirects to Admin work orders). Dispatch has no historical PO picker.
- **Work order ID** = `WO-AC-*`. Inward stays `ORD-AC-*`. **Dispatch is work-order based**: pick `WO-AC-*`, then select the In Stock bags on that work order. Select all ships their combined kilograms in one dispatch. A shipment does not take kilograms from a bag that was not selected, and it cannot exceed the work order quantity still pending. The screen shows dispatched kg and pending kg.
- **Material in plant** counts each kilogram once: charcoal not released, lots awaiting kiln, kilograms still in process, and In Stock. A lot awaiting kiln is not also counted as kiln feed. Shipped kilograms stay on Dispatched.
- **Reports** on Raw Material, Activation, and Post-activation each have Search, for every login that can open that tab (RMS, activation, post-activation, quality, operator, supervisor, plant admin, viewer, Nyra). Search narrows the rows and the chart in the From–To range. Every login that can open a Reports tab sees the rows in the From–To range, and Search narrows those rows. On Raw Material that is inward, DC, material, bag, and grade. On Activation and Post-activation that is the process rows (bag, grade, or process). Supplier name, code, weight, and value are not search fields or columns except for the supervisor, plant admin, and Nyra. Debit note stays on the supervisor report. The date picker closes after a date is chosen. Security has no Reports tab. Supervisors and Nyra keep supplier fields in Search. A viewer’s plant Production reports stay the summary charts. Supervisors open **User performance** on Activation reports and Post-activation reports, and Search there matches a person, bag, or grade. On a phone the same report is full width: the menu opens from the top bar, and the chart is shown above the table. The kilograms and the person on each check stay the same. It sums the kilograms of checks saved in the date range, by the person who saved the check. A supervisor who saves a kiln-output, destoning, or post-activation check is included. Raw Material reports do not have that process.
- **Stock Reallocation** (Admin menu, formerly In-stock work order) is supervisor-only, same gate as Destoner CTC allocation. The Admin tab label is Destoner CTC allocation. Role names on the corner and the user form are Administrator, Plant Manager, Raw-material section, Plant Entry, Activation, Post Activation, and Quality Control. Creating a user asks for a temporary password and emails it. Sign-in has Show password and Reset password. Activation Execution opens with the flow Kiln Feed → Kiln Output → Destoning. Standing kiln settings are visible on Kiln parameters and on Kiln output. Each save is kept in a change log. A new kiln output bag stores the settings in effect, and traceability shows them on that bag. Scrap is not a kiln parameter. An In Stock bag can move to another work order only when the grade matches. The previous work order stays on the bag. A new `assignedTo` triple is added; existing subjects and predicates are not rewritten.
- **Traceability** (Dashboard tab) is read-only. Choose work order, bag, inward, or dispatch, then pick from this month’s list. Supplier mapping walks back to the gate inward and is shown only to the manager and supervisor. A kiln blend can list more than one supplier with feed kg for those logins. Customer is not shown. `LOT-AC-*` is not a lookup key. A raw-material lookup lists every work order that material has used, including one it was moved from.
- **Work-order CTC** is entered once on the work order. Screening, destoning quality, and post-activation quality display it. Kiln output QC still measures actual CTC for fulfillment.
- **Screening**: pick mesh A–E (Masters mesh-grade map), then tag a grade from that mesh. Output kg cannot exceed the current loaded kg.
- **GRC-RPT-2026.10.13-R1 guards** (same subjects and bag prefixes): a shipment cannot exceed the selected bags; Unburnt and Stones stay off the kiln; release waits until RMS outward is complete; a short RMS bag total needs confirmation; destoner output cannot exceed the loader; lab moisture, dust, and volatility stay within 0–100%. A duplicate DC stays allowed. nyraservices@grcarbons has no invented nickname.

## Local stack

- UI: `nyra-mes-ui`, `npm run dev:ac`, `.env.ac` → API (prefer port `8003` if `8002` stuck)
- API: `scripts/run_sam_carbons_api_8003.ps1`
- Tenant: `GR_CARBONS` / `GR_CARBONS_ACTIVATED_CARBON`

## Files

| Area | Path |
|------|------|
| Dashboard | `nyra-mes-ui/.../pages/ActivatedCarbonDashboard.jsx`, `AcManagementDashboard.jsx` |
| Traceability | Dashboard tab `?view=traceability` — look up by work order / bag / inward / dispatch (this month’s list). Supplier from inward `supplies` walk. `GET /api/activated-carbon/material-trace` + `/options` |
| Raw Material tabs | `nyra-mes-ui/.../pages/RawMaterialPage.jsx` |
| Gate receipt | `RawMaterialInwardPage.jsx`, `AcGenerateRmsBagsPanel.jsx` |
| Inward list | `AcInwardRecordsTable.jsx` — click a receipt to open Inward, Lab, and Outward as separate rows (no gray highlight) |
| Inbound prep | `AcInboundProcessPanel.jsx`, `AcInboundStepCapture.jsx`, `AcInboundDebitNotePanel.jsx` |
| Inbound admin | `AcInboundAdminPanel.jsx`, `inbound_admin.py` |
| Release | `AcReleaseToProductionPanel.jsx` |
| Activation rail | `AcActivationProductionFlow.jsx`, `acActivationFlowConstants.js` |
| Kiln feed UI | `AcExecutionKilnFeedPanel.jsx` on Execution |
| Execution UI | `AcExecutionPage.jsx` |
| Triplet constants | `acTripletOntology.js` |
| Inward workflow + triples | `app/services/industry/activated_carbon/inbound_workflow.py` |
| Debit note | `app/services/industry/activated_carbon/debit_notes.py` |
| Inward execution | `app/services/industry/activated_carbon/inbound_execution.py` |
| Inward receipt + release | `app/services/industry/activated_carbon/adapter.py` |
| Material trace | `app/services/industry/activated_carbon/material_trace.py` |
