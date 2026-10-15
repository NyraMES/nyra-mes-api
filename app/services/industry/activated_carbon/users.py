"""Plant user directory for Activated Carbon tenants.

Persists identity in core.app_user + core.user_tenant_access (and workspace
access when a workspace is in context). Does not write shop-floor triples.
Cognito login is provisioned when the user pool is configured.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import (
    ALL_MES_ROLES,
    MES_DEMO,
    MES_SUPER_ADMIN,
    UserContext,
)
from app.core.config import settings
from app.core.exceptions import ConflictError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.platform import AppUser, UserProjectAccess, UserTenantAccess

ROLE_LABELS: dict[str, str] = {
    "MES_SuperAdmin": "Super Administrator",
    "MES_Admin": "Administrator",
    "MES_Manager": "Plant Manager",
    "MES_Planner": "Production Planner",
    "MES_Operator": "Shop Floor Operator",
    "MES_Quality": "Quality Control",
    "MES_RMS": "Raw-material section",
    "MES_Security": "Plant Entry",
    "MES_Activation": "Activation",
    "MES_PostActivation": "Post Activation",
    "MES_Viewer": "Read-only Viewer",
    "MES_Demo": "Demo Viewer",
}

# Plant roles created from the Users screen (maps 1:1 to Cognito groups).
ADMIN_ASSIGNABLE_ROLES: tuple[str, ...] = (
    "MES_Admin",
    "MES_Manager",
    "MES_RMS",
    "MES_Security",
    "MES_Activation",
    "MES_PostActivation",
    "MES_Quality",
)

DEFAULT_PLANT_PASSWORD = "Welcome!123"


def validate_plant_password(password: str) -> str:
    value = password or ""
    if (
        len(value) < 8
        or not any(char.islower() for char in value)
        or not any(char.isupper() for char in value)
        or not any(char.isdigit() for char in value)
        or not any(not char.isalnum() for char in value)
    ):
        raise ValidationError(
            "Password must be at least 8 characters and include an uppercase letter, "
            "a lowercase letter, a number, and a symbol."
        )
    return value

GR_CARBONS_TEST_USERS: tuple[dict[str, str], ...] = (
    {
        "username": "admin@grcarbons",
        "email": "sudha.param+admin@gmail.com",
        "display_name": "Admin (Nyra test)",
        "role_code": "MES_Admin",
    },
    {
        "username": "manager@grcarbons",
        "email": "sudha.param+manager@gmail.com",
        "display_name": "Manager (Nyra test)",
        "role_code": "MES_Manager",
    },
    {
        "username": "rms@grcarbons",
        "email": "sudha.param+rms@gmail.com",
        "display_name": "RMS (Nyra test)",
        "role_code": "MES_RMS",
    },
    {
        "username": "activation@grcarbons",
        "email": "sudha.param+activation@gmail.com",
        "display_name": "Activation (Nyra test)",
        "role_code": "MES_Activation",
    },
    {
        "username": "postactivation@grcarbons",
        "email": "sudha.param+postactivation@gmail.com",
        "display_name": "Post Activation (Nyra test)",
        "role_code": "MES_PostActivation",
    },
    {
        "username": "quality@grcarbons",
        "email": "sudha.param+quality@gmail.com",
        "display_name": "Quality (Nyra test)",
        "role_code": "MES_Quality",
    },
)


def login_suffix_for_tenant(tenant_code: str) -> str:
    code = (tenant_code or "").strip().upper()
    if code == "GR_CARBONS":
        return "@grcarbons"
    slug = "".join(ch for ch in code.lower() if ch.isalnum())
    return f"@{slug}" if slug else "@grcarbons"


def normalize_login_username(raw: str, tenant_code: str) -> str:
    suffix = login_suffix_for_tenant(tenant_code)
    value = (raw or "").strip().lower()
    if not value:
        raise ValidationError("Enter a user ID.")
    if " " in value:
        raise ValidationError("User ID cannot contain spaces.")
    if "@" not in value:
        local = value
        if not local or not all(ch.isalnum() or ch in "._-" for ch in local):
            raise ValidationError("User ID may use letters, numbers, dot, underscore, or hyphen.")
        return f"{local}{suffix}"
    local, _, domain = value.partition("@")
    if not local or domain != suffix[1:]:
        raise ValidationError(f"User ID must be name{suffix} (not an email address).")
    if not all(ch.isalnum() or ch in "._-" for ch in local):
        raise ValidationError("User ID may use letters, numbers, dot, underscore, or hyphen.")
    return f"{local}{suffix}"


def assignable_roles_for_actor(_actor: UserContext) -> list[dict[str, str]]:
    return [
        {"role_code": code, "label": ROLE_LABELS.get(code, code)}
        for code in ADMIN_ASSIGNABLE_ROLES
        if code in ALL_MES_ROLES
    ]


def assert_actor_may_assign_role(actor: UserContext, role_code: str) -> str:
    code = (role_code or "").strip()
    if code == MES_SUPER_ADMIN or code == MES_DEMO:
        raise ValidationError("This role cannot be assigned from the Users screen.")
    if code not in ALL_MES_ROLES:
        raise ValidationError(f"Unknown role '{role_code}'.")
    allowed = {row["role_code"] for row in assignable_roles_for_actor(actor)}
    if code not in allowed:
        raise ValidationError(f"You cannot assign role '{code}'.")
    return code


def list_tenant_users(db: Session, tenant: TenantContext) -> list[dict[str, Any]]:
    rows = (
        db.query(AppUser, UserTenantAccess)
        .join(UserTenantAccess, UserTenantAccess.user_id == AppUser.user_id)
        .filter(UserTenantAccess.tenant_id == tenant.tenant_id)
        .order_by(AppUser.email)
        .all()
    )
    return [
        _user_out(user, access)
        for user, access in rows
        if access.role_code != MES_SUPER_ADMIN
        and not _is_nyra_services_login(user)
    ]


def nickname_key(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def normalize_nickname(value: str | None) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise ValidationError("Enter a nickname.")
    if len(name) > 64:
        raise ValidationError("Nickname must be 64 characters or less.")
    return name


def nickname_is_taken(
    names: list[tuple[object, str]],
    candidate: str,
    *,
    except_user_id: object = None,
) -> bool:
    key = nickname_key(candidate)
    if not key:
        return False
    for user_id, existing in names:
        if except_user_id is not None and user_id == except_user_id:
            continue
        if nickname_key(existing) == key:
            return True
    return False


def _plant_nicknames(db: Session, tenant: TenantContext) -> list[tuple[object, str]]:
    rows = (
        db.query(AppUser)
        .join(UserTenantAccess, UserTenantAccess.user_id == AppUser.user_id)
        .filter(UserTenantAccess.tenant_id == tenant.tenant_id)
        .all()
    )
    return [(row.user_id, row.display_name or "") for row in rows]


def _assert_nickname_available(
    db: Session,
    tenant: TenantContext,
    nickname: str,
    *,
    except_user_id: object = None,
) -> str:
    name = normalize_nickname(nickname)
    if nickname_is_taken(_plant_nicknames(db, tenant), name, except_user_id=except_user_id):
        raise ConflictError(
            f'Nickname "{name}" is already used in this plant. Choose a different nickname.'
        )
    return name


def create_tenant_user(
    db: Session,
    tenant: TenantContext,
    actor: UserContext,
    *,
    username: str,
    email: str,
    display_name: Optional[str] = None,
    role_code: str,
    password: str,
) -> dict[str, Any]:
    role = assert_actor_may_assign_role(actor, role_code)
    chosen_password = validate_plant_password(password)
    login_username = normalize_login_username(username, tenant.tenant_code)
    if login_username.split("@", 1)[0] == "nyraservices":
        raise ValidationError("This user ID is reserved.")
    normalized_email = _normalize_email(email)
    name = _assert_nickname_available(db, tenant, display_name or "")
    if _login_username_taken(db, tenant, login_username):
        raise ConflictError(f"User ID {login_username} already exists for this plant.")

    user = db.query(AppUser).filter(AppUser.email == normalized_email).first()
    if user is not None:
        existing_access = (
            db.query(UserTenantAccess)
            .filter(
                UserTenantAccess.user_id == user.user_id,
                UserTenantAccess.tenant_id == tenant.tenant_id,
            )
            .first()
        )
        if existing_access is not None:
            raise ConflictError(
                f"A user with email {normalized_email} already has access to this plant."
            )
        user.display_name = user.display_name or name
        user.is_active = True
        _set_login_username(user, login_username)
    else:
        user = AppUser(
            email=normalized_email,
            display_name=name,
            is_active=True,
            metadata_={
                "created_from": "ac_users_screen",
                "login_username": login_username,
            },
        )
        db.add(user)
        db.flush()

    access = UserTenantAccess(
        user_id=user.user_id,
        tenant_id=tenant.tenant_id,
        role_code=role,
        is_default=True,
    )
    db.add(access)
    _ensure_workspace_access(db, tenant, user.user_id, role)
    db.commit()
    db.refresh(user)
    db.refresh(access)

    cognito = _provision_cognito_login(
        username=login_username,
        email=normalized_email,
        role_code=role,
        tenant_code=tenant.tenant_code,
        password=chosen_password,
    )
    if cognito.get("cognito_sub") and not user.cognito_sub:
        user.cognito_sub = cognito["cognito_sub"]
        db.commit()
        db.refresh(user)

    out = _user_out(user, access)
    out["temporary_password"] = cognito.get("temporary_password")
    out["cognito_provisioned"] = bool(cognito.get("provisioned"))
    out["cognito_message"] = cognito.get("message")
    return out


def ensure_known_directory_users(
    db: Session,
    tenant: TenantContext,
    rows: tuple[dict[str, str], ...] | list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Link existing Cognito test logins into the plant directory. No Cognito writes."""
    linked: list[dict[str, Any]] = []
    for row in rows:
        login_username = normalize_login_username(row["username"], tenant.tenant_code)
        email = _normalize_email(row["email"])
        role = row["role_code"]
        name = (row.get("display_name") or "").strip() or login_username.split("@")[0]
        user = db.query(AppUser).filter(AppUser.email == email).first()
        if user is None:
            user = AppUser(
                email=email,
                display_name=name,
                is_active=True,
                metadata_={
                    "created_from": "nyra_test_link",
                    "login_username": login_username,
                    "is_nyra_test": True,
                },
            )
            db.add(user)
            db.flush()
        else:
            user.display_name = user.display_name or name
            user.is_active = True
            _set_login_username(user, login_username, nyra_test=True)
        access = (
            db.query(UserTenantAccess)
            .filter(
                UserTenantAccess.user_id == user.user_id,
                UserTenantAccess.tenant_id == tenant.tenant_id,
            )
            .first()
        )
        if access is None:
            access = UserTenantAccess(
                user_id=user.user_id,
                tenant_id=tenant.tenant_id,
                role_code=role,
                is_default=True,
            )
            db.add(access)
        _ensure_workspace_access(db, tenant, user.user_id, role)
        db.flush()
        linked.append(_user_out(user, access))
    db.commit()
    return linked


def update_tenant_user_nickname(
    db: Session,
    tenant: TenantContext,
    user_id: UUID,
    display_name: str,
) -> dict[str, Any]:
    access = (
        db.query(UserTenantAccess)
        .filter(
            UserTenantAccess.user_id == user_id,
            UserTenantAccess.tenant_id == tenant.tenant_id,
        )
        .first()
    )
    if access is None:
        raise ValidationError("That user is not on this plant.")
    user = db.query(AppUser).filter(AppUser.user_id == user_id).first()
    if user is None:
        raise ValidationError("That user is not on this plant.")
    user.display_name = _assert_nickname_available(
        db, tenant, display_name, except_user_id=user.user_id
    )
    db.commit()
    db.refresh(user)
    return _user_out(user, access)


def list_plant_nicknames(db: Session, tenant: TenantContext) -> list[dict[str, str]]:
    rows = (
        db.query(AppUser)
        .join(UserTenantAccess, UserTenantAccess.user_id == AppUser.user_id)
        .filter(UserTenantAccess.tenant_id == tenant.tenant_id)
        .all()
    )
    out: list[dict[str, str]] = []
    for user in rows:
        meta = user.metadata_ if isinstance(user.metadata_, dict) else {}
        login = str(meta.get("login_username") or "").strip()
        email = (user.email or "").strip()
        name = (user.display_name or "").strip() or login or email
        if not name:
            continue
        out.append(
            {
                "username": login,
                "email": email,
                "cognito_sub": str(user.cognito_sub or "").strip(),
                "display_name": name,
            }
        )
    return out


def display_name_for_session(db: Session, user: UserContext) -> str | None:
    row = None
    sub = (user.sub or "").strip()
    if sub:
        row = db.query(AppUser).filter(AppUser.cognito_sub == sub).first()
    email = (user.email or "").strip().lower()
    if row is None and email:
        row = db.query(AppUser).filter(func.lower(AppUser.email) == email).first()
    username = (user.username or "").strip().lower()
    if row is None and username:
        for candidate in db.query(AppUser).all():
            meta = candidate.metadata_ if isinstance(candidate.metadata_, dict) else {}
            login = str(meta.get("login_username") or "").strip().lower()
            mail = (candidate.email or "").strip().lower()
            if username in {login, mail}:
                row = candidate
                break
    if row is None:
        return None
    name = (row.display_name or "").strip()
    return name or None


def _is_nyra_services_login(user: AppUser) -> bool:
    meta = user.metadata_ if isinstance(user.metadata_, dict) else {}
    for raw in (meta.get("login_username"), user.email, user.display_name):
        local = str(raw or "").strip().lower().split("@", 1)[0]
        if local == "nyraservices":
            return True
    return False


def _user_out(user: AppUser, access: UserTenantAccess) -> dict[str, Any]:
    meta = user.metadata_ if isinstance(user.metadata_, dict) else {}
    return {
        "user_id": user.user_id,
        "username": meta.get("login_username") or "",
        "email": user.email,
        "display_name": user.display_name,
        "role_code": access.role_code,
        "role_label": ROLE_LABELS.get(access.role_code, access.role_code),
        "is_active": bool(user.is_active),
        "cognito_linked": bool(user.cognito_sub) or bool(meta.get("is_nyra_test")),
        "created_at": user.created_at,
    }


def _normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if "@" not in value or " " in value or value.startswith("@") or value.endswith("@"):
        raise ValidationError("Enter a valid email address.")
    local, _, domain = value.partition("@")
    if "." not in domain:
        raise ValidationError("Enter a valid email address.")
    if len(value) > 320:
        raise ValidationError("Email is too long.")
    if not local:
        raise ValidationError("Enter a valid email address.")
    return value


def _set_login_username(user: AppUser, login_username: str, *, nyra_test: bool = False) -> None:
    meta = dict(user.metadata_ or {})
    meta["login_username"] = login_username
    if nyra_test:
        meta["is_nyra_test"] = True
        meta.setdefault("created_from", "nyra_test_link")
    user.metadata_ = meta
    flag_modified(user, "metadata_")


def _login_username_taken(db: Session, tenant: TenantContext, login_username: str) -> bool:
    rows = (
        db.query(AppUser)
        .join(UserTenantAccess, UserTenantAccess.user_id == AppUser.user_id)
        .filter(UserTenantAccess.tenant_id == tenant.tenant_id)
        .all()
    )
    wanted = login_username.lower()
    for user in rows:
        meta = user.metadata_ if isinstance(user.metadata_, dict) else {}
        if str(meta.get("login_username") or "").lower() == wanted:
            return True
    return False


def _ensure_workspace_access(
    db: Session,
    tenant: TenantContext,
    user_id: UUID,
    role_code: str,
) -> None:
    if not tenant.workspace_id:
        return
    existing = (
        db.query(UserProjectAccess)
        .filter(
            UserProjectAccess.user_id == user_id,
            UserProjectAccess.workspace_id == tenant.workspace_id,
        )
        .first()
    )
    if existing is not None:
        return
    db.add(
        UserProjectAccess(
            user_id=user_id,
            workspace_id=tenant.workspace_id,
            role_code=role_code,
            is_default=True,
        )
    )


def _provision_cognito_login(
    *,
    username: str,
    email: str,
    role_code: str,
    tenant_code: str,
    password: str,
) -> dict[str, Any]:
    pool_id = (settings.cognito_user_pool_id or "").strip()
    region = (settings.cognito_region or "").strip()
    if not settings.auth_enabled:
        return {
            "provisioned": False,
            "message": (
                "User saved for this plant. Cognito login is created when "
                "authentication is enabled on the server."
            ),
        }
    if not pool_id or not region:
        return {
            "provisioned": False,
            "message": (
                "User saved for this plant. Cognito is not configured here, "
                "so they cannot sign in until login is provisioned."
            ),
        }
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        return {
            "provisioned": False,
            "message": "User saved. boto3 is not installed, so Cognito login was skipped.",
        }

    client = boto3.client("cognito-idp", region_name=region)
    created = False
    cognito_sub = None
    try:
        existing = client.admin_get_user(UserPoolId=pool_id, Username=username)
        created = False
        cognito_sub = _sub_from_cognito_attrs(existing.get("UserAttributes") or [])
        client.admin_update_user_attributes(
            UserPoolId=pool_id,
            Username=username,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "custom:tenant_code", "Value": tenant_code},
            ],
        )
        password = None
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "UserNotFoundException":
            return {
                "provisioned": False,
                "message": f"User saved. Cognito login could not be created: {exc}",
            }
        attributes = [
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "custom:tenant_code", "Value": tenant_code},
        ]
        emailed = False
        try:
            created_user = client.admin_create_user(
                UserPoolId=pool_id,
                Username=username,
                UserAttributes=attributes,
                TemporaryPassword=password,
                DesiredDeliveryMediums=["EMAIL"],
            )
            emailed = True
        except ClientError as create_exc:
            code = create_exc.response.get("Error", {}).get("Code")
            detail = str(create_exc)
            if code == "InvalidPasswordException":
                return {
                    "provisioned": False,
                    "message": (
                        "User saved in the plant, but the sign-in service rejected the password. "
                        "Use 8 or more characters with upper and lower case, a number, and a symbol."
                    ),
                }
            email_failed = code in {
                "CodeDeliveryFailureException",
                "InvalidEmailRoleAccessPolicyException",
            } or "email" in detail.lower() or "message" in detail.lower()
            if not email_failed:
                return {
                    "provisioned": False,
                    "message": f"User saved. Cognito login could not be created: {create_exc}",
                }
            try:
                created_user = client.admin_create_user(
                    UserPoolId=pool_id,
                    Username=username,
                    UserAttributes=attributes,
                    TemporaryPassword=password,
                    MessageAction="SUPPRESS",
                )
            except ClientError as retry_exc:
                return {
                    "provisioned": False,
                    "message": f"User saved. Cognito login could not be created: {retry_exc}",
                }
        created = True
        cognito_sub = (created_user.get("User") or {}).get("Username")
        attrs = (created_user.get("User") or {}).get("Attributes") or []
        cognito_sub = _sub_from_cognito_attrs(attrs) or cognito_sub
        if not emailed:
            password_note = (
                f"Login created for {username}. The invitation email could not be sent. "
                "Give them the temporary password shown here. They set a new password at first sign-in."
            )
        else:
            password_note = (
                f"Login created. A temporary password was emailed to {email}. "
                f"They sign in as {username} and set a new password."
            )

    try:
        _ensure_cognito_group(client, pool_id, role_code)
        client.admin_add_user_to_group(
            UserPoolId=pool_id,
            Username=username,
            GroupName=role_code,
        )
    except ClientError as exc:
        return {
            "provisioned": created,
            "temporary_password": password if created else None,
            "cognito_sub": cognito_sub,
            "message": (
                "Cognito user exists, but the role group could not be assigned: "
                f"{exc}"
            ),
        }

    if created:
        return {
            "provisioned": True,
            "temporary_password": password,
            "cognito_sub": cognito_sub,
            "message": password_note,
        }
    return {
        "provisioned": True,
        "cognito_sub": cognito_sub,
        "message": (
            f"Existing Cognito login {username} was linked to this plant and role. "
            "Password was not changed."
        ),
    }


def _ensure_cognito_group(client: Any, pool_id: str, group: str) -> None:
    from botocore.exceptions import ClientError

    try:
        client.get_group(GroupName=group, UserPoolId=pool_id)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        client.create_group(
            GroupName=group,
            UserPoolId=pool_id,
            Description=f"Nyra MES role {group}",
        )


def _sub_from_cognito_attrs(attrs: list[dict[str, str]]) -> Optional[str]:
    for row in attrs or []:
        if row.get("Name") == "sub" and row.get("Value"):
            return row["Value"]
    return None
