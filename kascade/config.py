import json
import os
from dataclasses import dataclass, field, asdict

from .paths import data_root, config_path


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

For files that must live in a specific sub-path (e.g. a config inside an
author subfolder), use the "Known file paths" setting in the app.
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
        root = data_root()
        if not self.base_dir:
            self.base_dir = os.path.join(root, "ServerPacks")
        if not self.post_update_dir:
            self.post_update_dir = os.path.join(root, "post_update")

    def content_subfolders(self):
        return list(self.post_update_folders) + ["server-files"]

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
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self):
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
