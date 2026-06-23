"""Resolve nyra_mes_core PostgreSQL credentials from env or AWS Secrets Manager.

Production (testbed / EC2):
  Set ``MES_CORE_DB_SECRET_ID`` to the RDS-managed secret name or ARN.
  The EC2 instance role needs ``secretsmanager:GetSecretValue`` on that secret.
  ``MES_CORE_DB_PASSWORD`` can be omitted — password is fetched at runtime.

Local development:
  Either set ``MES_CORE_DB_PASSWORD`` in ``.env``, or set ``MES_CORE_DB_SECRET_ID``
  with AWS credentials configured (``aws configure`` / env vars).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Optional

from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass(frozen=True)
class MesCoreDbCredentials:
    host: str
    port: str
    name: str
    user: str
    password: str


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _aws_region() -> str:
    return (
        _env("AWS_REGION")
        or _env("AWS_DEFAULT_REGION")
        or _env("MES_CORE_AWS_REGION")
        or _env("COGNITO_REGION")
        or "eu-north-1"
    )


def _parse_secret_json(
    data: Mapping[str, Any],
    *,
    host: str,
    port: str,
    name: str,
    user: str,
) -> MesCoreDbCredentials:
    password = str(data.get("password") or data.get("Password") or "").strip()
    if not password:
        raise ValueError("Secret JSON is missing 'password'")

    resolved_user = str(
        data.get("username") or data.get("user") or data.get("Username") or user
    ).strip()
    resolved_host = str(data.get("host") or data.get("Host") or host).strip()
    resolved_port = str(data.get("port") or data.get("Port") or port or "5432").strip()
    resolved_name = str(
        data.get("dbname")
        or data.get("database")
        or data.get("dbInstanceIdentifier")
        or name
        or "postgres"
    ).strip()

    if not resolved_host:
        raise ValueError(
            "Secret JSON has no host — set MES_CORE_DB_HOST in .env alongside "
            "MES_CORE_DB_SECRET_ID"
        )
    if not resolved_user:
        raise ValueError(
            "Secret JSON has no username — set MES_CORE_DB_USER in .env alongside "
            "MES_CORE_DB_SECRET_ID"
        )

    return MesCoreDbCredentials(
        host=resolved_host,
        port=resolved_port,
        name=resolved_name,
        user=resolved_user,
        password=password,
    )


def fetch_secret_json(secret_id: str, *, region: Optional[str] = None) -> dict[str, Any]:
    """Fetch and parse a Secrets Manager secret (RDS JSON or plain password string)."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required for MES_CORE_DB_SECRET_ID — pip install boto3"
        ) from exc

    client = boto3.client("secretsmanager", region_name=region or _aws_region())
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Could not read secret '{secret_id}' in {region or _aws_region()}: {exc}"
        ) from exc

    raw = response.get("SecretString") or ""
    if not raw and response.get("SecretBinary"):
        raw = response["SecretBinary"].decode("utf-8")
    if not raw:
        raise ValueError(f"Secret '{secret_id}' has empty SecretString")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"password": raw.strip()}

    if not isinstance(parsed, dict):
        raise ValueError(f"Secret '{secret_id}' must be JSON object or plain password string")
    return parsed


@lru_cache(maxsize=1)
def get_mes_core_db_credentials() -> MesCoreDbCredentials:
    """Cached credentials for the process lifetime (restart picks up rotated secrets)."""
    host = _env("MES_CORE_DB_HOST")
    port = _env("MES_CORE_DB_PORT", "5432")
    name = _env("MES_CORE_DB_NAME", "nyra_mes_core")
    user = _env("MES_CORE_DB_USER")
    password = _env("MES_CORE_DB_PASSWORD")
    secret_id = _env("MES_CORE_DB_SECRET_ID")

    if secret_id:
        data = fetch_secret_json(secret_id)
        return _parse_secret_json(
            data,
            host=host,
            port=port,
            name=name,
            user=user,
        )

    if password and host and user:
        return MesCoreDbCredentials(
            host=host,
            port=port or "5432",
            name=name or "nyra_mes_core",
            user=user,
            password=password,
        )

    raise ValueError(
        "nyra_mes_core database credentials are not configured. Set either:\n"
        "  • MES_CORE_DB_SECRET_ID (recommended on testbed — RDS Secrets Manager), or\n"
        "  • MES_CORE_DB_HOST, MES_CORE_DB_USER, and MES_CORE_DB_PASSWORD (local dev)\n"
        "EC2 needs IAM permission: secretsmanager:GetSecretValue on the secret."
    )


def clear_mes_core_db_credentials_cache() -> None:
    get_mes_core_db_credentials.cache_clear()
