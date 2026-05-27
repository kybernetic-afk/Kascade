import os
import sys


def app_dir() -> str:
    """Directory of the running app: the exe's folder when frozen, else the package's parent."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(rel: str) -> str:
    """Path to a bundled resource: PyInstaller's temp dir when frozen, else the repo root."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, rel)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel)


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "Kascade")
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def data_root() -> str:
    """Where the app keeps its working folders (ServerPacks, post_update, bin).

    Always under %APPDATA%\\Kascade so the app never litters the folder the exe
    happens to be run from (e.g. Downloads).
    """
    return config_dir()
