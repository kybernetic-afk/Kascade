import os
import socket
import time
import zipfile
import shutil
from stat import S_ISDIR

import paramiko
import requests

WEBHOOK_DOCS_URL = "https://discourse.cubecoders.com/t/webhook-and-stream-deck-integrations/34321"


class CancelledError(Exception):
    pass


class UpdateError(Exception):
    """A user-fixable error, with optional guidance and a docs link."""

    def __init__(self, message, help_url=None):
        super().__init__(message)
        self.help_url = help_url


PHASES = [
    ("stop", "Stopping server"),
    ("locate", "Locating server pack"),
    ("extract", "Extracting files"),
    ("connect", "Connecting to server"),
    ("clean_remote", "Removing old files"),
    ("upload", "Uploading server files"),
    ("post_update", "Applying post-update files"),
    ("cleanup", "Cleaning up"),
    ("start", "Starting server"),
]


class Updater:
    def __init__(self, config, secrets, log=print, is_cancelled=None, phase=None):
        self.cfg = config
        self.s = secrets
        self.log = log
        self._is_cancelled = is_cancelled or (lambda: False)
        self._phase_cb = phase or (lambda key: None)

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
        matches = []
        filename_lower = filename.lower()
        try:
            items = sftp.listdir_attr(search_dir)
        except IOError as e:
            if depth == 0:
                self.log(f"    Warning: Could not list directory {search_dir}: {e}")
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
                matches.extend(self._find_remote_file(sftp, item_path, filename, depth + 1))
            elif item_name.lower() == filename_lower:
                matches.append(item_path)
        return matches

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
                        subdir = known_paths[filename]
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
                    elif len(matching_paths) == 1:
                        remote_path = matching_paths[0]
                        self.log(f"    Replacing: {remote_path}")
                        self._upload(sftp, local_file_path, remote_path)
                    else:
                        self.log("    Multiple matches found - replacing all:")
                        for remote_path in matching_paths:
                            self.log(f"      - {remote_path}")
                            self._upload(sftp, local_file_path, remote_path)

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
        if not url.lower().startswith(("http://", "https://")):
            raise UpdateError(
                f"The AMP webhook URL doesn't look valid: '{url}'. It should start with "
                "https:// and come from your AMP instance.",
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
        host = self.s["AMP_SFTP_HOST"]
        try:
            port = int(self.s.get("AMP_SFTP_PORT") or 2224)
        except (TypeError, ValueError):
            raise UpdateError(
                f"The SFTP port isn't a number: '{self.s.get('AMP_SFTP_PORT')}'. "
                "Fix it on the Secrets page."
            )
        try:
            transport = paramiko.Transport((host, port))
            transport.connect(username=self.s["AMP_SFTP_USER"], password=self.s["AMP_SFTP_PASS"])
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
        sftp = paramiko.SFTPClient.from_transport(transport)

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
            transport.close()

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

        self._phase("start")
        self.log("Starting server...")
        self._call_amp("StartServer")
        self.log("Update completed!")
