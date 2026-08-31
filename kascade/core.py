import os
import socket
import time
import zipfile
import shutil
from stat import S_ISDIR
from urllib.parse import urlparse

import paramiko
import requests

from . import amp_api
from .netutil import is_local_host
from .paths import config_dir

WEBHOOK_DOCS_URL = "https://discourse.cubecoders.com/t/webhook-and-stream-deck-integrations/34321"


def find_remote_file(sftp, search_dir, filename, log=None, depth=0):
    """Recursively find every file named `filename` (case-insensitive) under
    `search_dir`. Returns a list of full remote paths."""
    matches = []
    filename_lower = filename.lower()
    try:
        items = sftp.listdir_attr(search_dir)
    except IOError as e:
        if depth == 0 and log:
            log(f"    Warning: Could not list directory {search_dir}: {e}")
        return matches

    for item_attr in items:
        item_name = item_attr.filename
        if search_dir == "/":
            item_path = f"/{item_name}"
        elif search_dir.endswith("/"):
            item_path = f"{search_dir}{item_name}"
        else:
            item_path = f"{search_dir}/{item_name}"

        if S_ISDIR(item_attr.st_mode):
            matches.extend(find_remote_file(sftp, item_path, filename, log, depth + 1))
        elif item_name.lower() == filename_lower:
            matches.append(item_path)
    return matches


def subdir_from_match(search_base, match_path):
    """Given the folder we searched under (e.g. '/config') and a full remote path
    a file was found at (e.g. '/config/dcint/backup.toml'), return the file's
    subdirectory relative to that base ('dcint'; '' when it sits in the base)."""
    base = search_base.rstrip("/")
    rel = match_path
    if rel.startswith(base):
        rel = rel[len(base):]
    rel = rel.strip("/")
    # rel is now like 'dcint/backup.toml' or 'backup.toml'; the subdir is the
    # directory part.
    parts = rel.split("/")
    return "/".join(parts[:-1])


class CancelledError(Exception):
    pass


class UpdateError(Exception):
    """A user-fixable error, with optional guidance and a docs link."""

    def __init__(self, message, help_url=None):
        super().__init__(message)
        self.help_url = help_url


# Seconds without any data on the SFTP channel before a transfer is treated as
# stalled. paramiko has no per-transfer timeout, so a hung put() would otherwise
# block forever; with a timeout it raises and the upload retry loop recovers.
SFTP_STALL_TIMEOUT = 60
# How often to send a keepalive so a dead peer is detected instead of hanging.
SFTP_KEEPALIVE = 15


def connect_sftp(secrets, log=print, stall_timeout=SFTP_STALL_TIMEOUT):
    """Open an SFTP session to the AMP server described by `secrets`.

    Returns (client, sftp); the caller is responsible for closing both. Raises
    UpdateError with a user-readable message on any connection failure. Shared by
    the updater and the GUI's "Find on server" path lookup so both verify the
    host key and report problems identically.

    A keepalive and a per-channel stall timeout are set so a transfer that hangs
    (a known paramiko failure mode on large files) raises instead of blocking the
    app forever - the caller's retry loop then re-attempts it.
    """
    host = secrets["AMP_SFTP_HOST"]
    try:
        port = int(secrets.get("AMP_SFTP_PORT") or 2224)
    except (TypeError, ValueError):
        raise UpdateError(
            f"The SFTP port isn't a number: '{secrets.get('AMP_SFTP_PORT')}'. "
            "Fix it on the Secrets page."
        )
    # Verify the server's host key (trust-on-first-use). The first connection
    # records the key; if a known host later presents a different key we abort
    # rather than hand credentials to a possible man-in-the-middle.
    known_hosts = os.path.join(config_dir(), "known_hosts")
    if not os.path.exists(known_hosts):
        open(known_hosts, "a").close()
    client = paramiko.SSHClient()
    client.load_host_keys(known_hosts)
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username=secrets["AMP_SFTP_USER"],
            password=secrets["AMP_SFTP_PASS"],
            look_for_keys=False,
            allow_agent=False,
            timeout=30,
            banner_timeout=30,
            auth_timeout=30,
        )
    except paramiko.BadHostKeyException as e:
        raise UpdateError(
            f"The SFTP server's identity has changed since the last connection to "
            f"{host}:{port}. This can happen if the server was rebuilt - or it can mean "
            f"the connection is being intercepted. No files were uploaded.\n\n"
            f"If you trust this change, remove the entry for this host from:\n"
            f"{known_hosts}\nand try again.\n\nDetails: {e}"
        )
    except paramiko.AuthenticationException:
        raise UpdateError(
            "SFTP login was rejected. Check the SFTP username and password on the "
            "Secrets page."
        )
    except (socket.gaierror, socket.timeout, ConnectionError, OSError) as e:
        raise UpdateError(
            f"Couldn't connect to the SFTP server at {host}:{port} ({e}). Check the "
            "SFTP host and port on the Secrets page."
        )
    except paramiko.SSHException as e:
        raise UpdateError(
            f"SFTP connection error to {host}:{port} ({e}). Check the SFTP host, port, "
            "and credentials on the Secrets page."
        )
    # Detect a dead peer rather than waiting on it indefinitely.
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(SFTP_KEEPALIVE)
    sftp = client.open_sftp()
    # A stalled transfer now raises socket.timeout instead of hanging forever.
    channel = sftp.get_channel()
    if channel is not None:
        channel.settimeout(stall_timeout)
    return client, sftp


PHASES = [
    ("stop", "Stopping server"),
    ("locate", "Locating server pack"),
    ("extract", "Extracting files"),
    ("connect", "Connecting to server"),
    ("clean_remote", "Removing old files"),
    ("upload", "Uploading server files"),
    ("post_update", "Applying post-update files"),
    ("cleanup", "Cleaning up"),
    ("sync_version", "Syncing NeoForge version"),
    ("start", "Starting server"),
]


class Updater:
    def __init__(self, config, secrets, log=print, is_cancelled=None, phase=None):
        self.cfg = config
        self.s = secrets
        self.log = log
        self._is_cancelled = is_cancelled or (lambda: False)
        self._phase_cb = phase or (lambda key: None)
        # Config files that had no pinned path and weren't found on the server,
        # so they landed in config/ root and may not take effect. Surfaced after
        # the run so the user can pin a path for them.
        self.unplaced_config = []

    def _phase(self, key):
        self._phase_cb(key)

    # ------------------------------------------------------------------
    # cancellation
    # ------------------------------------------------------------------
    def _check_cancel(self):
        if self._is_cancelled():
            raise CancelledError("Update cancelled by user.")

    def _sleep(self, seconds):
        for _ in range(int(seconds)):
            self._check_cancel()
            time.sleep(1)

    # ------------------------------------------------------------------
    # SFTP helpers
    # ------------------------------------------------------------------
    def _isdir(self, sftp, path):
        try:
            return S_ISDIR(sftp.stat(path).st_mode)
        except IOError:
            return False

    def _exists(self, sftp, path):
        try:
            sftp.stat(path)
            return True
        except IOError:
            return False

    def _makedirs(self, sftp, remote_dir):
        if self._exists(sftp, remote_dir):
            return
        parts = remote_dir.strip("/").split("/")
        current_path = ""
        for part in parts:
            current_path = f"{current_path}/{part}"
            if not self._exists(sftp, current_path):
                try:
                    sftp.mkdir(current_path)
                    self.log(f"    Created directory: {current_path}")
                except IOError as e:
                    self.log(f"    Warning: Could not create {current_path}: {e}")

    def _upload(self, sftp, local_path, remote_path):
        self._check_cancel()
        retries = self.cfg.upload_retries
        for attempt in range(1, retries + 1):
            try:
                sftp.put(local_path, remote_path)
                self.log(f"Uploaded file: {remote_path}")
                return
            except Exception as e:
                self.log(f"[Retry {attempt}/{retries}] Failed to upload {remote_path}: {e}")
                time.sleep(2)
        raise Exception(f"Failed to upload {local_path} after retries")

    def _upload_dir(self, sftp, local_dir, remote_dir):
        try:
            sftp.mkdir(remote_dir)
        except IOError:
            pass
        for item in os.listdir(local_dir):
            lpath = os.path.join(local_dir, item)
            rpath = f"{remote_dir}/{item}"
            if os.path.isdir(lpath):
                self._upload_dir(sftp, lpath, rpath)
            else:
                self._upload(sftp, lpath, rpath)

    def _remove_remote(self, sftp, path):
        try:
            if self._isdir(sftp, path):
                for item in sftp.listdir(path):
                    self._remove_remote(sftp, f"{path}/{item}")
                sftp.rmdir(path)
                self.log(f"Removed directory: {path}")
            else:
                sftp.remove(path)
                self.log(f"Removed file: {path}")
        except IOError:
            pass

    def _find_remote_file(self, sftp, search_dir, filename, depth=0):
        return find_remote_file(sftp, search_dir, filename, log=self.log, depth=depth)

    def _upload_post_update_files(self, sftp, post_update_dir):
        remote_base = self.cfg.remote_base
        for folder in self.cfg.post_update_folders:
            self._check_cancel()
            local_folder = os.path.join(post_update_dir, folder)
            remote_search_base = f"{remote_base}{folder}"

            if not os.path.isdir(local_folder):
                self.log(f"Post-update folder not found: {local_folder}, skipping.")
                continue

            self.log(f"\nProcessing post-update folder: {folder}")
            self.log(f"  Local source: {local_folder}")
            self.log(f"  Remote search base: {remote_search_base}")

            known_paths = self.cfg.known_file_paths.get(folder, {})

            for root, dirs, files in os.walk(local_folder):
                for filename in files:
                    self._check_cancel()
                    local_file_path = os.path.join(root, filename)
                    self.log(f"\n  Processing: {filename}")

                    if filename in known_paths:
                        # An empty/'.'/'/' subdir means the folder root; strip it
                        # so the path is 'config/file', not 'config//file'.
                        subdir = (known_paths[filename] or "").strip("/").strip()
                        if subdir in ("", "."):
                            remote_dir = remote_search_base
                        else:
                            remote_dir = f"{remote_search_base}/{subdir}"
                        remote_path = f"{remote_dir}/{filename}"
                        self.log(f"    Using known path: {remote_path}")
                        self._makedirs(sftp, remote_dir)
                        self._upload(sftp, local_file_path, remote_path)
                        continue

                    self.log("    Searching server for existing file...")
                    matching_paths = self._find_remote_file(sftp, remote_search_base, filename)
                    self.log(f"    Found {len(matching_paths)} match(es)")

                    if len(matching_paths) == 0:
                        remote_path = f"{remote_search_base}/{filename}"
                        self.log(f"    No match found - uploading to: {remote_path}")
                        self._upload(sftp, local_file_path, remote_path)
                        # A config file that wasn't found anywhere on the server
                        # landed in config/ root, where most mods won't read it.
                        # Flag it so the run can tell the user to pin a path.
                        if folder == "config":
                            self.unplaced_config.append(filename)
                    elif len(matching_paths) == 1:
                        remote_path = matching_paths[0]
                        self.log(f"    Replacing: {remote_path}")
                        self._upload(sftp, local_file_path, remote_path)
                    else:
                        self.log("    Multiple matches found - replacing all:")
                        for remote_path in matching_paths:
                            self.log(f"      - {remote_path}")
                            self._upload(sftp, local_file_path, remote_path)

        if self.unplaced_config:
            self.log("\n" + "!" * 50)
            self.log(
                f"WARNING: {len(self.unplaced_config)} config file(s) had no known "
                "destination and weren't found on the server, so they were placed in "
                "config/ root and may not take effect:"
            )
            for name in self.unplaced_config:
                self.log(f"    - {name}")
            self.log(
                "Set a path for them on the Content page ('Find on server' or "
                "'Set path')."
            )
            self.log("!" * 50)

        server_files_dir = os.path.join(post_update_dir, "server-files")
        if os.path.isdir(server_files_dir):
            self.log("\nProcessing server-files...")
            for root, dirs, files in os.walk(server_files_dir):
                for filename in files:
                    local_file_path = os.path.join(root, filename)
                    remote_path = f"{remote_base}{filename}"
                    self.log(f"  Uploading server file: {filename} -> {remote_path}")
                    self._upload(sftp, local_file_path, remote_path)

    # ------------------------------------------------------------------
    # AMP webhook
    # ------------------------------------------------------------------
    def _call_amp(self, payload_name, fatal=False):
        token = self.s["AMP_TOKEN"]
        url = self.s["AMP_WEBHOOK_URL"]
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorize": f"Bearer {token}",
        }
        payload = {"payload": payload_name, "SESSIONID": token}

        if not url:
            raise UpdateError(
                "No AMP webhook URL is set. Add it on the Secrets page.", WEBHOOK_DOCS_URL
            )
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise UpdateError(
                f"The AMP webhook URL doesn't look valid: '{url}'. It should start with "
                "https:// and come from your AMP instance.",
                WEBHOOK_DOCS_URL,
            )
        # The AMP token rides in this request (Bearer header + body). Refuse to
        # send it over plain http to anything beyond the local machine/LAN.
        if scheme == "http" and not is_local_host(parsed.hostname or ""):
            raise UpdateError(
                f"The AMP webhook URL uses http://, which would send your AMP token in "
                f"cleartext to {parsed.hostname}. Use an https:// URL (plain http is only "
                "allowed for a local or LAN AMP instance).",
                WEBHOOK_DOCS_URL,
            )

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
        except requests.exceptions.SSLError:
            raise UpdateError(
                f"Couldn't establish a secure connection to the webhook URL ({url}). "
                "Double-check the address.",
                WEBHOOK_DOCS_URL,
            )
        except requests.exceptions.ConnectionError:
            raise UpdateError(
                f"Couldn't reach the AMP webhook URL ({url}). Check the address and that "
                "your AMP instance is reachable.",
                WEBHOOK_DOCS_URL,
            )
        except requests.RequestException as e:
            raise UpdateError(f"Webhook request failed: {e}", WEBHOOK_DOCS_URL)

        if r.status_code == 200:
            self.log(f"Webhook '{payload_name}' sent.")
            return

        if r.status_code in (401, 403):
            raise UpdateError(
                "The webhook was rejected (unauthorized). Check your AMP API token on the "
                "Secrets page and that the webhook is enabled in AMP.",
                WEBHOOK_DOCS_URL,
            )
        if r.status_code == 404:
            raise UpdateError(
                f"The webhook URL was not found (404): {url}. Re-copy it from AMP.",
                WEBHOOK_DOCS_URL,
            )

        message = f"Webhook '{payload_name}' returned HTTP {r.status_code}."
        if fatal:
            raise UpdateError(message + " Check your webhook configuration.", WEBHOOK_DOCS_URL)
        self.log(message)

    # ------------------------------------------------------------------
    # AMP application config (NeoForge version)
    # ------------------------------------------------------------------
    def _sync_neoforge_version(self, installer_name):
        """Make sure AMP is configured to run the NeoForge version we just
        uploaded, and have AMP actually download/install it, before Start is
        called. Without this, AMP starts up against whatever version it was
        last configured for - not the installer we just placed on disk - and
        fails silently."""
        version = amp_api.parse_neoforge_version(installer_name)
        if not version:
            raise UpdateError(
                f"Could not read a NeoForge version out of '{installer_name}'."
            )
        if not self.cfg.amp_instance_id:
            raise UpdateError(
                "No AMP instance ID is set. Add it on the Settings page so Kascade can "
                "sync the NeoForge version with AMP before starting the server."
            )

        webhook_url = self.s["AMP_WEBHOOK_URL"]
        if not webhook_url:
            raise UpdateError(
                "No AMP webhook URL is set. Add it on the Secrets page.", WEBHOOK_DOCS_URL
            )

        self.log(f"Signing in to AMP to sync the NeoForge version to {version}...")
        try:
            base_url = amp_api.base_url_from_webhook_url(webhook_url)
            api = amp_api.AMPInstanceAPI(base_url, self.cfg.amp_instance_id, log=self.log)
            api.login(self.s["AMP_API_USER"], self.s["AMP_API_PASS"])

            node = amp_api.NEOFORGE_VERSION_NODE
            current = api.get_config(node)
            enum_values = (current or {}).get("EnumValues") or {}
            if enum_values and version not in enum_values:
                raise UpdateError(
                    f"AMP doesn't list NeoForge version {version} as available yet. "
                    "Try again shortly, or check the version in AMP's UI."
                )

            if (current or {}).get("CurrentValue") == version:
                self.log("AMP's NeoForge Version already matches; skipping download.")
                return

            api.set_config(node, version)
            self.log(f"Set AMP's NeoForge Version to {version}. Triggering download...")
            api.update_application()
            api.wait_for_update(is_cancelled=self._is_cancelled)
            self.log("AMP finished downloading and installing NeoForge.")
        except amp_api.AMPAPIError as e:
            raise UpdateError(str(e))

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------
    def run(self):
        cfg = self.cfg
        base_dir = cfg.base_dir
        remote_base = cfg.remote_base

        self._phase("stop")
        self.log("Stopping Minecraft server...")
        self._call_amp("StopServer", fatal=True)
        self._sleep(cfg.stop_delay)

        self._phase("locate")
        self.log(f"Looking for latest ServerFiles-*.zip in {base_dir}...")
        zip_candidates = [
            os.path.join(base_dir, f)
            for f in os.listdir(base_dir)
            if f.startswith("ServerFiles-") and f.endswith(".zip")
        ]
        if not zip_candidates:
            raise UpdateError(
                f"No ServerFiles-*.zip found in {base_dir}. Use 'Download Latest' to fetch "
                "the newest pack first, or drop a ServerFiles zip into that folder."
            )

        latest_zip = max(zip_candidates, key=os.path.getmtime)
        self.log(f"Using latest server zip: {latest_zip}")

        extracted_dir = os.path.join(
            base_dir, os.path.splitext(os.path.basename(latest_zip))[0]
        )

        self._phase("extract")
        self.log(f"Extracting to: {extracted_dir}")
        with zipfile.ZipFile(latest_zip, "r") as zf:
            zf.extractall(extracted_dir)

        local_dir = extracted_dir
        self.log(f"Using extracted server files from: {local_dir}")

        installer_name = None
        for f in os.listdir(local_dir):
            if f.startswith("neoforge-") and f.endswith("-installer.jar"):
                installer_name = f
                break
        if not installer_name:
            raise Exception("NeoForge installer not found in server files.")
        self.log(f"Detected NeoForge installer: {installer_name}")

        self._check_cancel()
        self._phase("connect")
        self.log("Connecting to SFTP...")
        client, sftp = connect_sftp(self.s, log=self.log)

        try:
            self._phase("clean_remote")
            self.log("Deleting remote files...")
            for item in cfg.targets:
                self._remove_remote(sftp, f"{remote_base}{item}")

            self.log("Removing old NeoForge installers...")
            try:
                for f in sftp.listdir(remote_base):
                    if (
                        f.startswith("neoforge-")
                        and f.endswith("-installer.jar")
                        and f != installer_name
                    ):
                        sftp.remove(f"{remote_base}{f}")
                        self.log(f"Removed old installer: {f}")
            except Exception:
                pass

            self._phase("upload")
            self.log("Uploading server files...")
            for item in cfg.targets:
                lpath = os.path.join(local_dir, item)
                rpath = f"{remote_base}{item}"
                if os.path.isdir(lpath):
                    self._upload_dir(sftp, lpath, rpath)
                elif os.path.exists(lpath):
                    self._upload(sftp, lpath, rpath)

            self._upload(
                sftp,
                os.path.join(local_dir, installer_name),
                f"{remote_base}{installer_name}",
            )

            self._phase("post_update")
            self.log("\n" + "=" * 50)
            self.log("Uploading post-update files...")
            self.log("=" * 50)
            if os.path.isdir(cfg.post_update_dir):
                self._upload_post_update_files(sftp, cfg.post_update_dir)
            else:
                self.log(f"Warning: post_update directory not found at {cfg.post_update_dir}")
        finally:
            sftp.close()
            client.close()

        self._phase("cleanup")
        self.log("Cleaning up local extracted files...")
        try:
            if os.path.isdir(extracted_dir):
                shutil.rmtree(extracted_dir)
                self.log(f"Deleted folder: {extracted_dir}")
        except Exception as e:
            self.log(f"Warning: failed to delete folder {extracted_dir}: {e}")

        try:
            if os.path.exists(latest_zip):
                os.remove(latest_zip)
                self.log(f"Deleted zip: {latest_zip}")
        except Exception as e:
            self.log(f"Warning: failed to delete zip {latest_zip}: {e}")

        self._phase("sync_version")
        self._sync_neoforge_version(installer_name)

        self._phase("start")
        self.log("Starting server...")
        self._call_amp("StartServer")
        self.log("Update completed!")
