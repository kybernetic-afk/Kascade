import json
import os
from dataclasses import dataclass, field, asdict

from . import crypto
from .paths import app_dir, data_root, config_path

# Marks a secret value that is DPAPI-encrypted on disk. Values without it are
# treated as legacy cleartext and re-encrypted on the next save.
_ENC_PREFIX = "dpapi:"


def _encrypt_secrets(secrets: dict) -> dict:
    """Return a copy of `secrets` with plaintext-mode values encrypted at rest."""
    out = {}
    for key, src in (secrets or {}).items():
        src = dict(src or {})
        value = src.get("value", "")
        if src.get("mode") == "plaintext" and value and not value.startswith(_ENC_PREFIX):
            try:
                src["value"] = _ENC_PREFIX + crypto.protect(value)
            except OSError:
                pass  # DPAPI unavailable (non-Windows dev) - leave as-is
        out[key] = src
    return out


def _decrypt_secrets(secrets: dict) -> dict:
    """Return a copy of `secrets` with any encrypted values decrypted in memory."""
    out = {}
    for key, src in (secrets or {}).items():
        src = dict(src or {})
        value = src.get("value", "")
        if isinstance(value, str) and value.startswith(_ENC_PREFIX):
            try:
                src["value"] = crypto.unprotect(value[len(_ENC_PREFIX):])
            except Exception:
                # Wrong user/machine, or corrupted - drop it rather than expose a
                # stale/unusable blob in the UI.
                src["value"] = ""
        out[key] = src
    return out


def default_base_dir() -> str:
    return os.path.join(data_root(), "ServerPacks")


def default_post_update_dir() -> str:
    return os.path.join(data_root(), "post_update")


def _default_targets():
    return [
        "config",
        "datapacks",
        "defaultconfigs",
        "kubejs",
        "local",
        "mods",
        "server-icon.png",
        "startserver.bat",
        "startserver.sh",
        "user_jvm_args.txt",
    ]


def _default_known_file_paths():
    return {
        "config": {},
        "mods": {},
    }


def _default_secrets():
    # Default: pull each value from Bitwarden using the same key name.
    keys = ["AMP_SFTP_HOST", "AMP_SFTP_PORT", "AMP_SFTP_USER",
            "AMP_SFTP_PASS", "AMP_TOKEN", "AMP_WEBHOOK_URL"]
    return {k: {"mode": "bws", "value": "", "bws_key": k} for k in keys}


README_TEXT = """Kascade - content folders
================================

Drop your custom files into these folders. After each server-pack update they
are pushed to the server, overriding the files that came with the pack.

  config/        Custom config files. They are matched by name against the
                 server's existing config files (searched recursively) and
                 replace them. New files land in the config root.

  mods/          Extra/override mod .jar files. Same name-matching as config.

  server-files/  Files copied directly to the server root. Put a custom
                 server-icon.png here, or startserver scripts, etc.

For a config file that must live in a specific sub-path (e.g. inside an author
subfolder), pin its path on the Content page - use "Find on server" to locate
where it currently lives, or "Set path" to type the subfolder yourself. Files
without a pinned path are matched by name against the server and, if not found,
land in the config root.
"""


@dataclass
class Config:
    base_dir: str = ""
    remote_base: str = "/"
    post_update_dir: str = ""
    targets: list = field(default_factory=_default_targets)
    post_update_folders: list = field(default_factory=lambda: ["config", "mods"])
    known_file_paths: dict = field(default_factory=_default_known_file_paths)
    upload_retries: int = 3
    stop_delay: int = 15
    bws_project_id: str = ""
    curseforge_project_id: int = 925200
    server_pack_match: str = "ServerFiles"
    secrets: dict = field(default_factory=_default_secrets)

    def __post_init__(self):
        # Resolve to the computed default when unset, or migrate the old
        # exe-relative location to the new default so existing installs heal.
        legacy_base = os.path.join(app_dir(), "ServerPacks")
        legacy_post = os.path.join(app_dir(), "post_update")
        if not self.base_dir or self.base_dir == legacy_base:
            self.base_dir = default_base_dir()
        if not self.post_update_dir or self.post_update_dir == legacy_post:
            self.post_update_dir = default_post_update_dir()

    def content_subfolders(self):
        return list(self.post_update_folders) + ["server-files"]

    def get_config_path(self, filename):
        """Return the pinned sub-path for a config file (relative to config/), or
        None if it has no pin and is matched by name on the server."""
        return self.known_file_paths.get("config", {}).get(filename)

    def set_config_path(self, filename, subdir):
        """Pin a config file's destination sub-path (relative to config/). An
        empty string pins it to the config root; pass subdir=None to remove the
        pin entirely (revert to automatic name-matching)."""
        paths = self.known_file_paths.setdefault("config", {})
        if subdir is None:
            paths.pop(filename, None)
        else:
            paths[filename] = subdir.strip().strip("/")

    def ensure_dirs(self):
        """Create the app's working folders if they don't exist. Best-effort."""
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            os.makedirs(self.post_update_dir, exist_ok=True)
            for sub in self.content_subfolders():
                os.makedirs(os.path.join(self.post_update_dir, sub), exist_ok=True)
            readme = os.path.join(self.post_update_dir, "README.txt")
            if not os.path.exists(readme):
                with open(readme, "w", encoding="utf-8") as f:
                    f.write(README_TEXT)
        except OSError:
            pass

    @classmethod
    def load(cls):
        path = config_path()
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.secrets = _decrypt_secrets(cfg.secrets)
        return cfg

    def save(self):
        data = asdict(self)
        # Don't pin the folder paths unless they were actually customized, so
        # the computed default (under %APPDATA%) keeps applying.
        if self.base_dir == default_base_dir():
            data["base_dir"] = ""
        if self.post_update_dir == default_post_update_dir():
            data["post_update_dir"] = ""
        # Encrypt plaintext secret values at rest (self.secrets stays cleartext
        # in memory for the UI / updater).
        data["secrets"] = _encrypt_secrets(self.secrets)
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
