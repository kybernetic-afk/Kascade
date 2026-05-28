"""Zip-based backup and restore of the post-update content folders.

A Kascade backup is just a regular .zip of the user's custom mods, configs,
and server-files (and any other folders they have configured), with a small
``kascade-backup.json`` manifest at the root for sanity-checking on restore.

Kept GUI-free so the round-trip can be unit-tested without Qt.
"""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone


MANIFEST_NAME = "kascade-backup.json"
MANIFEST_VERSION = 1


class BackupError(Exception):
    pass


@dataclass
class BackupResult:
    zip_path: str
    file_count: int
    folders: list


@dataclass
class RestoreResult:
    file_count: int
    folders: list
    has_manifest: bool


def _iter_files(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            yield full, os.path.relpath(full, root)


def create_backup(post_update_dir: str, zip_path: str, subfolders) -> BackupResult:
    """Zip ``subfolders`` (relative to ``post_update_dir``) into ``zip_path``.

    Missing subfolders are silently skipped (the user may not have added any
    server-files yet, for example). A manifest is written at the root.
    """
    if not subfolders:
        raise BackupError("No subfolders to back up.")

    folders_included = []
    file_count = 0
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)) or ".", exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sub in subfolders:
            src_dir = os.path.join(post_update_dir, sub)
            if not os.path.isdir(src_dir):
                continue
            had_file = False
            for full, rel in _iter_files(src_dir):
                arcname = os.path.join(sub, rel).replace("\\", "/")
                zf.write(full, arcname)
                file_count += 1
                had_file = True
            if had_file:
                folders_included.append(sub)

        manifest = {
            "format": "kascade-backup",
            "version": MANIFEST_VERSION,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "folders": folders_included,
            "file_count": file_count,
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))

    return BackupResult(zip_path=zip_path, file_count=file_count, folders=folders_included)


def _is_safe_member(name: str) -> bool:
    """Reject absolute paths and parent-traversal segments (zip-slip)."""
    if not name or name.endswith("/"):
        return False
    norm = name.replace("\\", "/")
    if norm.startswith("/") or ":" in norm:
        return False
    parts = norm.split("/")
    return ".." not in parts and "" not in parts


def read_manifest(zip_path: str):
    """Return the parsed manifest, or ``None`` if the zip has none / is invalid."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if MANIFEST_NAME not in zf.namelist():
                return None
            with zf.open(MANIFEST_NAME) as fh:
                return json.loads(fh.read().decode("utf-8"))
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError):
        return None


def restore_backup(zip_path: str, post_update_dir: str) -> RestoreResult:
    """Extract ``zip_path`` over ``post_update_dir``, overwriting same-named files.

    Other existing files are left in place (merge semantics). The manifest
    entry is skipped; unsafe paths (absolute / parent-traversal) are rejected.
    """
    if not os.path.isfile(zip_path):
        raise BackupError(f"Backup file not found: {zip_path}")

    os.makedirs(post_update_dir, exist_ok=True)
    has_manifest = False
    file_count = 0
    folders = set()

    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as e:
        raise BackupError(f"Not a valid zip file: {e}") from e

    with zf:
        for info in zf.infolist():
            name = info.filename
            if name == MANIFEST_NAME:
                has_manifest = True
                continue
            if info.is_dir():
                continue
            if not _is_safe_member(name):
                raise BackupError(f"Refusing unsafe path in backup: {name!r}")

            target = os.path.join(post_update_dir, name.replace("/", os.sep))
            target_abs = os.path.abspath(target)
            root_abs = os.path.abspath(post_update_dir)
            if not (target_abs == root_abs or target_abs.startswith(root_abs + os.sep)):
                raise BackupError(f"Refusing unsafe path in backup: {name!r}")

            os.makedirs(os.path.dirname(target_abs), exist_ok=True)
            with zf.open(info) as src, open(target_abs, "wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
            file_count += 1
            top = name.replace("\\", "/").split("/", 1)[0]
            if top:
                folders.add(top)

    return RestoreResult(file_count=file_count, folders=sorted(folders), has_manifest=has_manifest)
