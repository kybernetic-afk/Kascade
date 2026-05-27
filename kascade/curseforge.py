import os
import urllib.parse

import requests

BASE = "https://www.curseforge.com/api/v1"
CDN = "https://mediafilez.forgecdn.net/files"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class CurseForgeError(Exception):
    pass


def _headers():
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def cdn_url(file_id: int, file_name: str) -> str:
    return f"{CDN}/{file_id // 1000}/{file_id % 1000}/{urllib.parse.quote(file_name)}"


def find_latest_server_pack(project_id: int, name_contains: str = "ServerFiles", log=print) -> dict:
    """Return info about the newest server pack (a .zip whose name contains name_contains).

    Returns dict with: file_id, file_name, file_length, date, parent_version, download_url.
    Raises CurseForgeError on failure.
    """
    log(f"Querying CurseForge project {project_id}...")
    try:
        resp = requests.get(
            f"{BASE}/mods/{project_id}/files",
            params={"pageIndex": 0, "pageSize": 30, "sort": "dateCreated", "sortDescending": "true"},
            headers=_headers(),
            timeout=30,
        )
    except requests.RequestException as e:
        raise CurseForgeError(f"Failed to reach CurseForge: {e}")

    if resp.status_code != 200:
        raise CurseForgeError(f"CurseForge file list returned HTTP {resp.status_code}")

    files = resp.json().get("data", [])
    if not files:
        raise CurseForgeError("No files returned for that project.")

    needle = name_contains.lower()
    for f in files:
        if not (f.get("hasServerPack") or f.get("additionalServerPackFilesCount")):
            continue
        parent_id = f.get("id")
        log(f"Checking server pack for {f.get('displayName', parent_id)}...")
        try:
            extra = requests.get(
                f"{BASE}/mods/{project_id}/files/{parent_id}/additional-files",
                headers=_headers(),
                timeout=30,
            )
        except requests.RequestException as e:
            raise CurseForgeError(f"Failed to fetch server pack info: {e}")
        if extra.status_code != 200:
            continue

        for sp in extra.json().get("data", []):
            name = sp.get("fileName", "")
            if needle in name.lower() and name.lower().endswith(".zip"):
                file_id = sp["id"]
                return {
                    "file_id": file_id,
                    "file_name": name,
                    "file_length": sp.get("fileLength", 0),
                    "date": sp.get("dateCreated", ""),
                    "parent_version": f.get("displayName", ""),
                    "download_url": cdn_url(file_id, name),
                }

    raise CurseForgeError(
        f"No server pack matching '{name_contains}' found in the latest releases."
    )


def download_file(url, dest_path, log=print, progress_cb=None, is_cancelled=None):
    """Stream a download to dest_path (via a .part temp file). Returns the final path."""
    is_cancelled = is_cancelled or (lambda: False)
    part_path = dest_path + ".part"
    log(f"Downloading: {url}")
    try:
        with requests.get(url, headers=_headers(), stream=True, timeout=60) as r:
            if r.status_code != 200:
                raise CurseForgeError(f"Download returned HTTP {r.status_code}")
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            last_pct = -1
            with open(part_path, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if is_cancelled():
                        raise CurseForgeError("Download cancelled.")
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    if total and progress_cb:
                        pct = int(done * 100 / total)
                        if pct != last_pct:
                            last_pct = pct
                            progress_cb(pct)
    except requests.RequestException as e:
        _safe_remove(part_path)
        raise CurseForgeError(f"Download failed: {e}")
    except CurseForgeError:
        _safe_remove(part_path)
        raise

    if os.path.exists(dest_path):
        _safe_remove(dest_path)
    os.replace(part_path, dest_path)
    log(f"Saved to: {dest_path}")
    return dest_path


def _safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
