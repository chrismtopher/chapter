from __future__ import annotations

import os
import pwd
from pathlib import Path


STORAGE_OWNER_ENV = "ABS_KIDS_PLAYER_STORAGE_OWNER"


def ensure_storage_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    apply_configured_owner(path)


def finalize_storage_file(path: Path, mode: int = 0o600) -> None:
    path.chmod(mode)
    apply_configured_owner(path)


def apply_configured_owner(path: Path) -> None:
    owner = configured_storage_owner()
    if owner is None:
        return
    os.chown(path, owner.pw_uid, owner.pw_gid)


def configured_storage_owner() -> pwd.struct_passwd | None:
    username = os.environ.get(STORAGE_OWNER_ENV, "").strip()
    if not username or os.geteuid() != 0:
        return None
    return pwd.getpwnam(username)
