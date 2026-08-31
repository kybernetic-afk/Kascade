import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile

import requests

from . import crypto
from .paths import app_dir, data_root

# The values the update needs. Each: (key, label, required, sensitive)
# `key` is what core.py looks up; the user can map it to any Bitwarden secret name.
SECRET_ROLES = [
    ("AMP_SFTP_HOST", "SFTP host", True, False),
    ("AMP_SFTP_PORT", "SFTP port", True, False),
    ("AMP_SFTP_USER", "SFTP username", True, False),
    ("AMP_SFTP_PASS", "SFTP password", True, True),
    ("AMP_TOKEN", "AMP API token", True, True),
    ("AMP_WEBHOOK_URL", "AMP webhook URL", True, False),
    ("AMP_API_USER", "AMP API username", True, False),
    ("AMP_API_PASS", "AMP API password", True, True),
]

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

BWS_VERSION = "2.1.0"

# SHA-256 of the official bws release zips (from the GitHub release asset
# digests). The downloaded archive is verified against these before bws.exe is
# extracted and run, so a tampered download can't execute as the secret handler.
BWS_SHA256 = {
    "x86_64": "8d6f2b51beb6f992b5b1de8b85a98bdf18de74096b724d17fa06219fc23f2bd5",
    "aarch64": "ba18adeb5d123481211c47c4e4d0ad6d81a6b0139150704785542fdee542e583",
}


class SecretError(Exception):
    pass


def _read_persisted_token():
    """Read BWS_ACCESS_TOKEN from the user environment in the registry (Windows).

    setx writes here, but an already-running shell won't have it in os.environ.
    Reading the registry directly picks it up in the same session.
    """
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "BWS_ACCESS_TOKEN")
            return value or None
    except OSError:
        return None


def _token_file() -> str:
    return os.path.join(data_root(), "token.dat")


def token_present() -> bool:
    if os.environ.get("BWS_ACCESS_TOKEN"):
        return True
    # Current mechanism: a DPAPI-encrypted token file readable only by this user.
    tf = _token_file()
    if os.path.isfile(tf):
        try:
            with open(tf, "r", encoding="utf-8") as f:
                token = crypto.unprotect(f.read().strip())
            if token:
                os.environ["BWS_ACCESS_TOKEN"] = token
                return True
        except Exception:
            pass
    # Legacy: older versions saved the token to the user environment in cleartext.
    # Honour it, but migrate it into the encrypted file so new launches stop
    # depending on the plaintext registry copy.
    persisted = _read_persisted_token()
    if persisted:
        os.environ["BWS_ACCESS_TOKEN"] = persisted
        persist_token(persisted)
        return True
    return False


def set_token_for_session(token: str):
    os.environ["BWS_ACCESS_TOKEN"] = token


def persist_token(token: str) -> bool:
    """Store the token encrypted at rest (Windows DPAPI, current user) under the
    app's data folder, so future launches can reuse it without a cleartext copy."""
    try:
        blob = crypto.protect(token)
    except OSError:
        return False
    try:
        path = _token_file()
        with open(path, "w", encoding="utf-8") as f:
            f.write(blob)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def _bws_install_dir() -> str:
    return os.path.join(data_root(), "bin")


def find_bws() -> str:
    """Locate the bws executable: env override, PATH, then known bin/ folders."""
    override = os.environ.get("BWS_PATH")
    if override and os.path.isfile(override):
        return override
    on_path = shutil.which("bws")
    if on_path:
        return on_path
    for candidate in (
        os.path.join(_bws_install_dir(), "bws.exe"),
        os.path.join(app_dir(), "bin", "bws.exe"),
        os.path.join(app_dir(), "bws.exe"),
    ):
        if os.path.isfile(candidate):
            return candidate
    raise SecretError(
        "Could not find the 'bws' executable. Install it or set BWS_PATH to its full path."
    )


def download_bws(log=print) -> str:
    """Download the pinned bws release and extract bws.exe into the app's bin folder."""
    arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
    url = (
        f"https://github.com/bitwarden/sdk-sm/releases/download/"
        f"bws-v{BWS_VERSION}/bws-{arch}-pc-windows-msvc-{BWS_VERSION}.zip"
    )
    log(f"Bitwarden CLI not found. Downloading bws {BWS_VERSION} ({arch})...")
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SecretError(f"Failed to download bws: {e}")

    expected = BWS_SHA256.get(arch)
    digest = hashlib.sha256(resp.content).hexdigest()
    if expected and digest != expected:
        raise SecretError(
            f"The downloaded Bitwarden CLI failed its integrity check and was not "
            f"installed (expected {expected[:12]}..., got {digest[:12]}...). This could "
            "indicate a corrupted or tampered download."
        )

    dest_dir = _bws_install_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "bws.exe")
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith("bws.exe")), None)
            if not member:
                raise SecretError("bws.exe was not found in the downloaded archive.")
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    except zipfile.BadZipFile:
        raise SecretError("The downloaded bws archive was invalid.")

    log(f"Installed bws to: {dest}")
    return dest


def ensure_bws(log=print) -> str:
    """Return a usable bws path, downloading it on first use if necessary."""
    try:
        return find_bws()
    except SecretError:
        return download_bws(log)


def fetch_all_bws_secrets(project_id: str = "", log=None) -> dict:
    """Return all secrets the access token can read, as a {key: value} dict.

    Downloads the bws CLI on first use if it isn't installed.
    """
    log = log or (lambda _msg: None)
    bws = ensure_bws(log)
    cmd = [bws, "secret", "list"]
    if project_id:
        cmd.append(project_id)
    cmd += ["-o", "json", "-c", "no"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise SecretError(f"Failed to launch bws: {e}")
    except subprocess.TimeoutExpired:
        raise SecretError("bws timed out while fetching secrets.")

    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()
        raise SecretError(f"bws failed (exit {result.returncode}): {msg}")

    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SecretError("Could not parse bws output as JSON.")

    return {item["key"]: item["value"] for item in items if "key" in item}


def config_needs_bws(sources: dict) -> bool:
    return any((s or {}).get("mode") == "bws" for s in (sources or {}).values())


def resolve_secrets(sources: dict, project_id: str = "", log=None) -> dict:
    """Resolve each role to a concrete value from plaintext config or Bitwarden.

    `sources` maps role key -> {"mode": "plaintext"|"bws", "value": str, "bws_key": str}.
    Only contacts Bitwarden if at least one role uses bws mode.
    Raises SecretError if a required value is missing.
    """
    log = log or (lambda _msg: None)
    sources = sources or {}

    bws_values = {}
    if config_needs_bws(sources):
        if not token_present():
            raise SecretError(
                "Some values are set to come from Bitwarden, but BWS_ACCESS_TOKEN is not set."
            )
        bws_values = fetch_all_bws_secrets(project_id, log)

    resolved = {}
    missing = []
    for key, label, required, _sensitive in SECRET_ROLES:
        src = sources.get(key) or {}
        if src.get("mode") == "plaintext":
            value = (src.get("value") or "").strip()
        else:
            bws_key = (src.get("bws_key") or key).strip()
            value = bws_values.get(bws_key)
            if value is None:
                if required:
                    missing.append(f"{label} (Bitwarden key '{bws_key}')")
                value = ""
        if required and not value:
            if label not in " ".join(missing):
                missing.append(label)
        resolved[key] = value

    if missing:
        raise SecretError("Missing required value(s): " + "; ".join(dict.fromkeys(missing)))
    return resolved
