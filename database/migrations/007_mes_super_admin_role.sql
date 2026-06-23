-- Allow MES_SuperAdmin in user access role checks (Cognito group for process/raw-material setup).

ALTER TABLE core.user_tenant_access
    DROP CONSTRAINT IF EXISTS chk_user_role;

ALTER TABLE core.user_tenant_access
    ADD CONSTRAINT chk_user_role CHECK (
        role_code IN (
            'MES_SuperAdmin',
            'MES_Admin',
            'MES_Planner',
            'MES_Operator',
            'MES_Quality',
            'MES_Viewer'
        )
    );

ALTER TABLE core.user_project_access
    DROP CONSTRAINT IF EXISTS chk_user_project_role;

ALTER TABLE core.user_project_access
    ADD CONSTRAINT chk_user_project_role CHECK (
        role_code IN (
            'MES_SuperAdmin',
            'MES_Admin',
            'MES_Planner',
            'MES_Operator',
            'MES_Quality',
            'MES_Viewer'
        )
    );
