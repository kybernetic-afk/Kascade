import re
import time
from collections import namedtuple
from urllib.parse import urlparse

import requests

from .netutil import is_local_host

# AMP's config node for the Minecraft module's "NeoForge Version" setting
# (Server and Startup tab). Confirmed against a live AMP 2.8.0.4 instance.
NEOFORGE_VERSION_NODE = "MinecraftModule.Minecraft.SpecificNeoForgeVersion"

# The permission AMP requires to fire the "Download / Update" action (verified
# against a live instance's GetAPISpec).
UPDATE_APPLICATION_PERMISSION = "Core.AppManagement.UpdateApplication"

_INSTALLER_RE = re.compile(r"^neoforge-(.+)-installer\.jar$", re.IGNORECASE)

# One row of a permission check: what was tested, whether it passed, and any
# detail to show the user (a value read back, or an error message).
PermissionCheck = namedtuple("PermissionCheck", ["label", "ok", "detail"])


def base_url_from_webhook_url(webhook_url):
    """AMP's Core API and its webhook plugin live on the same host - derive
    the API base URL from the already-configured webhook URL rather than
    asking for it a second time."""
    parsed = urlparse(webhook_url or "")
    if not parsed.scheme or not parsed.netloc:
        raise AMPAPIError(f"The AMP webhook URL doesn't look valid: '{webhook_url}'.")
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_neoforge_version(installer_filename):
    """Extract the version out of a 'neoforge-<version>-installer.jar' filename,
    e.g. 'neoforge-21.1.249-installer.jar' -> '21.1.249'. Returns None if the
    filename doesn't match that pattern."""
    m = _INSTALLER_RE.match(installer_filename)
    return m.group(1) if m else None


class AMPAPIError(Exception):
    pass


class AMPInstanceAPI:
    """Thin client for AMP's Core API, scoped to a single ADS-managed instance.

    AMP's ADS controller proxies API calls to a managed instance's own API
    under `/API/ADSModule/Servers/<InstanceId>/API/<Module>/<Method>` - logging
    in against that same path returns a session scoped to the instance itself
    (distinct from a session against the ADS controller root).
    """

    def __init__(self, base_url, instance_id, log=print, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.instance_id = instance_id
        self.log = log
        self.timeout = timeout
        self.session_id = None

        parsed = urlparse(self.base_url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise AMPAPIError(f"The AMP URL doesn't look valid: '{self.base_url}'.")
        if scheme == "http" and not is_local_host(parsed.hostname or ""):
            raise AMPAPIError(
                f"The AMP URL uses http://, which would send your AMP login in cleartext "
                f"to {parsed.hostname}. Use an https:// URL (plain http is only allowed for "
                "a local or LAN AMP instance)."
            )

    def _url(self, module, method):
        return f"{self.base_url}/API/ADSModule/Servers/{self.instance_id}/API/{module}/{method}"

    def _call(self, module, method, **params):
        url = self._url(module, method)
        data = dict(params)
        if self.session_id:
            data["SESSIONID"] = self.session_id
        try:
            r = requests.post(
                url,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json=data,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise AMPAPIError(f"AMP API request failed ({module}/{method}): {e}")

        if r.status_code != 200:
            raise AMPAPIError(f"AMP API {module}/{method} returned HTTP {r.status_code}.")
        try:
            result = r.json()
        except ValueError:
            raise AMPAPIError(f"AMP API {module}/{method} returned a non-JSON response.")

        # AMP reports errors (bad module/method, missing permission, etc.) as a
        # {Title, Message, StackTrace} object rather than an HTTP error status.
        if isinstance(result, dict) and result.get("Title") and "StackTrace" in result:
            raise AMPAPIError(f"AMP API {module}/{method} failed: {result.get('Message') or result.get('Title')}")
        return result

    def login(self, username, password):
        if not username or not password:
            raise AMPAPIError(
                "No AMP API username/password is set. Add them on the Secrets page."
            )
        result = self._call("Core", "Login", username=username, password=password, token="", rememberMe=False)
        if not result.get("success"):
            reason = result.get("resultReason") or "login was rejected"
            raise AMPAPIError(f"AMP login failed for user '{username}': {reason}")
        self.session_id = result["sessionID"]

    def get_config(self, node):
        return self._call("Core", "GetConfig", node=node)

    def set_config(self, node, value):
        result = self._call("Core", "SetConfig", node=node, value=value)
        if isinstance(result, dict) and result.get("Status") is False:
            raise AMPAPIError(f"AMP rejected setting '{node}' to '{value}': {result.get('Reason')}")
        return result

    def update_application(self):
        result = self._call("Core", "UpdateApplication")
        if isinstance(result, dict) and result.get("Status") is False:
            raise AMPAPIError(f"AMP's UpdateApplication failed: {result.get('Reason')}")
        return result

    def get_tasks(self):
        result = self._call("Core", "GetTasks")
        return result if isinstance(result, list) else []

    def current_session_has_permission(self, permission_node):
        return bool(self._call("Core", "CurrentSessionHasPermission", PermissionNode=permission_node))

    def check_permissions(self):
        """Verify the logged-in account can actually do what the NeoForge
        version sync needs, without changing anything real: read the version
        setting, write it back to its own current value (a no-op), and check
        the permission that gates triggering a download. Returns a list of
        PermissionCheck rows, most-fatal-first."""
        checks = []

        try:
            current = self.get_config(NEOFORGE_VERSION_NODE)
            value = (current or {}).get("CurrentValue")
            checks.append(PermissionCheck(
                "Read the NeoForge Version setting", True, f"current value: {value}"
            ))
        except AMPAPIError as e:
            checks.append(PermissionCheck("Read the NeoForge Version setting", False, str(e)))
            return checks  # nothing else can be tested without this

        try:
            self.set_config(NEOFORGE_VERSION_NODE, value)
            checks.append(PermissionCheck(
                "Change the NeoForge Version setting", True,
                "verified by writing back the current value",
            ))
        except AMPAPIError as e:
            checks.append(PermissionCheck("Change the NeoForge Version setting", False, str(e)))

        try:
            allowed = self.current_session_has_permission(UPDATE_APPLICATION_PERMISSION)
            checks.append(PermissionCheck(
                "Trigger Download / Update", allowed,
                None if allowed else f"Missing permission: {UPDATE_APPLICATION_PERMISSION}",
            ))
        except AMPAPIError as e:
            checks.append(PermissionCheck("Trigger Download / Update", False, str(e)))

        return checks

    def wait_for_update(self, timeout=180, poll_interval=3, is_cancelled=None):
        """Block until AMP has no running tasks (the update/download has
        finished), or raise if that takes too long or the run is cancelled."""
        deadline = time.time() + timeout
        # Give AMP a moment to register the task before polling for "done",
        # since GetTasks can briefly read empty right after triggering it.
        time.sleep(poll_interval)
        while time.time() < deadline:
            if is_cancelled and is_cancelled():
                raise AMPAPIError("Cancelled while waiting for AMP to finish updating.")
            if not self.get_tasks():
                return
            time.sleep(poll_interval)
        raise AMPAPIError(
            f"Timed out after {timeout}s waiting for AMP to finish downloading/installing "
            "the NeoForge update."
        )
