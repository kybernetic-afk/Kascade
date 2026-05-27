import os
import sys


def app_dir() -> str:
    """Directory of the running app: the exe's folder when frozen, else the package's parent."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "Kascade")
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def _is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def data_root() -> str:
    """Where the app keeps its working folders.

    Prefers the app's own directory (next to the exe) so content is easy to find,
    but falls back to %APPDATA%\\Kascade when that location isn't writable
    (e.g. the exe was placed in Program Files).
    """
    here = app_dir()
    if _is_writable(here):
        return here
    return config_dir()
