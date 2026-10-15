-- Plant Entry (MES_Security) is a plant role. Allow it on tenant and workspace access.

ALTER TABLE core.user_tenant_access
    DROP CONSTRAINT IF EXISTS chk_user_role;

ALTER TABLE core.user_tenant_access
    ADD CONSTRAINT chk_user_role CHECK (
        role_code IN (
            'MES_SuperAdmin',
            'MES_Admin',
            'MES_Manager',
            'MES_Planner',
            'MES_Operator',
            'MES_Quality',
            'MES_RMS',
            'MES_Activation',
            'MES_PostActivation',
            'MES_Security',
            'MES_Viewer',
            'MES_Demo'
        )
    );

ALTER TABLE core.user_project_access
    DROP CONSTRAINT IF EXISTS chk_user_project_role;

ALTER TABLE core.user_project_access
    ADD CONSTRAINT chk_user_project_role CHECK (
        role_code IN (
            'MES_SuperAdmin',
            'MES_Admin',
            'MES_Manager',
            'MES_Planner',
            'MES_Operator',
            'MES_Quality',
            'MES_RMS',
            'MES_Activation',
            'MES_PostActivation',
            'MES_Security',
            'MES_Viewer',
            'MES_Demo'
        )
    );
