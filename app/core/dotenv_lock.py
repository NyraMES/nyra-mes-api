"""Load ``.env`` without letting it replace a process-scoped database login.

Set ``NYRA_DOTENV_OVERRIDE=false`` when the process environment already carries
the database settings that must win (the demo API). Other settings still come
from ``.env``.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

_MES_PREFIX = "MES_CORE_"


def load_dotenv_locked() -> None:
    locked = os.getenv("NYRA_DOTENV_OVERRIDE", "true").lower() in ("0", "false", "no")
    snapshot = None
    if locked:
        snapshot = {
            key: os.environ[key]
            for key in os.environ
            if key.startswith(_MES_PREFIX)
        }
    load_dotenv(override=True)
    if snapshot is None:
        return
    for key in list(os.environ):
        if key.startswith(_MES_PREFIX) and key not in snapshot:
            del os.environ[key]
    os.environ.update(snapshot)
