-- GR Carbons is the first production AC client (rename from SAM_CARBONS seed name).
-- Safe on DBs that already ran 004; no-op if already renamed.

UPDATE core.tenant
SET tenant_code = 'GR_CARBONS',
    tenant_name = 'GR Carbons'
WHERE tenant_code = 'SAM_CARBONS'
  AND NOT EXISTS (SELECT 1 FROM core.tenant t2 WHERE t2.tenant_code = 'GR_CARBONS');

UPDATE core.project_workspace pw
SET workspace_code = 'GR_CARBONS_ACTIVATED_CARBON',
    workspace_name = 'GR Carbons — Activated Carbon'
FROM core.tenant t
WHERE pw.tenant_id = t.tenant_id
  AND t.tenant_code = 'GR_CARBONS'
  AND pw.workspace_code = 'SAM_CARBONS_ACTIVATED_CARBON'
  AND NOT EXISTS (
      SELECT 1 FROM core.project_workspace w2
      WHERE w2.workspace_code = 'GR_CARBONS_ACTIVATED_CARBON'
  );
