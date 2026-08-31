import os
from stat import S_IFDIR, S_IFREG
from types import SimpleNamespace

import pytest

import kascade.amp_api as amp_api
import kascade.core as core
from kascade.core import (
    SFTP_KEEPALIVE,
    UpdateError,
    Updater,
    connect_sftp,
    find_remote_file,
    subdir_from_match,
)


# ---------------------------------------------------------------------------
# A tiny in-memory stand-in for a paramiko SFTP client. Tracks a virtual
# filesystem so we can exercise the search + upload logic without a server.
# ---------------------------------------------------------------------------
class _Attr:
    def __init__(self, filename, is_dir):
        self.filename = filename
        self.st_mode = S_IFDIR if is_dir else S_IFREG


class FakeSFTP:
    def __init__(self, files=()):
        self.files = set()
        self.dirs = {"/"}
        self.uploads = []      # (local, remote) for every put()
        self.made_dirs = []    # every mkdir()
        for f in files:
            self._add_file(f)

    @staticmethod
    def _parent(path):
        path = path.rstrip("/")
        if "/" not in path.lstrip("/"):
            return "/"
        return path.rsplit("/", 1)[0] or "/"

    @staticmethod
    def _name(path):
        return path.rstrip("/").rsplit("/", 1)[-1]

    def _add_file(self, path):
        self.files.add(path)
        parts = path.strip("/").split("/")
        cur = ""
        for part in parts[:-1]:
            cur = f"{cur}/{part}"
            self.dirs.add(cur)

    # --- paramiko-like API ---
    def listdir_attr(self, path):
        path = path.rstrip("/") or "/"
        if path not in self.dirs:
            raise IOError(f"no such directory: {path}")
        attrs = []
        for d in self.dirs:
            if d != "/" and self._parent(d) == path:
                attrs.append(_Attr(self._name(d), True))
        for f in self.files:
            if self._parent(f) == path:
                attrs.append(_Attr(self._name(f), False))
        return attrs

    def stat(self, path):
        path = path.rstrip("/") or "/"
        if path in self.dirs:
            return _Attr(self._name(path), True)
        if path in self.files:
            return _Attr(self._name(path), False)
        raise IOError(f"no such file: {path}")

    def mkdir(self, path):
        path = path.rstrip("/") or "/"
        self.dirs.add(path)
        self.made_dirs.append(path)

    def put(self, local, remote):
        self.uploads.append((local, remote))
        self._add_file(remote)


def _write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def _cfg(known=None, amp_instance_id=""):
    return SimpleNamespace(
        remote_base="/",
        post_update_folders=["config"],
        known_file_paths={"config": known or {}},
        upload_retries=1,
        amp_instance_id=amp_instance_id,
    )


def _updater(cfg):
    return Updater(cfg, {}, log=lambda *_a: None)


def _remotes(sftp):
    return [remote for _local, remote in sftp.uploads]


# ---------------------------------------------------------------------------
# find_remote_file / subdir_from_match
# ---------------------------------------------------------------------------
def test_find_remote_file_locates_nested_and_missing():
    sftp = FakeSFTP(["/config/dcint/backup.toml", "/config/other.cfg"])
    assert find_remote_file(sftp, "/config", "backup.toml") == ["/config/dcint/backup.toml"]
    assert find_remote_file(sftp, "/config", "nope.toml") == []


def test_find_remote_file_is_case_insensitive():
    sftp = FakeSFTP(["/config/Sub/File.TOML"])
    assert find_remote_file(sftp, "/config", "file.toml") == ["/config/Sub/File.TOML"]


def test_subdir_from_match():
    assert subdir_from_match("/config", "/config/dcint/backup.toml") == "dcint"
    assert subdir_from_match("/config", "/config/backup.toml") == ""
    assert subdir_from_match("/config/", "/config/a/b/c.toml") == "a/b"
    assert subdir_from_match("/srv/mc/config", "/srv/mc/config/x/y.cfg") == "x"


# ---------------------------------------------------------------------------
# _upload_post_update_files
# ---------------------------------------------------------------------------
def test_pinned_subdir_uploads_to_that_path(tmp_path):
    pud = tmp_path / "post_update"
    _write(str(pud / "config" / "foo.toml"))
    updater = _updater(_cfg({"foo.toml": "dcint"}))
    sftp = FakeSFTP()  # empty server

    updater._upload_post_update_files(sftp, str(pud))

    assert "/config/dcint/foo.toml" in _remotes(sftp)
    assert updater.unplaced_config == []


def test_empty_pinned_subdir_targets_root_without_double_slash(tmp_path):
    pud = tmp_path / "post_update"
    _write(str(pud / "config" / "foo.toml"))
    updater = _updater(_cfg({"foo.toml": ""}))
    sftp = FakeSFTP()

    updater._upload_post_update_files(sftp, str(pud))

    remotes = _remotes(sftp)
    assert "/config/foo.toml" in remotes
    assert not any("//" in r for r in remotes)
    # A pinned file is never treated as unplaced.
    assert updater.unplaced_config == []


def test_unmatched_config_lands_in_root_and_is_flagged(tmp_path):
    pud = tmp_path / "post_update"
    _write(str(pud / "config" / "newmod.toml"))
    updater = _updater(_cfg())
    sftp = FakeSFTP()  # file exists nowhere on the server

    updater._upload_post_update_files(sftp, str(pud))

    assert "/config/newmod.toml" in _remotes(sftp)
    assert updater.unplaced_config == ["newmod.toml"]


# ---------------------------------------------------------------------------
# connect_sftp keepalive + stall-timeout wiring
# ---------------------------------------------------------------------------
class _FakeTransport:
    def __init__(self):
        self.keepalive = None

    def set_keepalive(self, interval):
        self.keepalive = interval


class _FakeChannel:
    def __init__(self):
        self.timeout = None

    def settimeout(self, t):
        self.timeout = t


class _FakeSSHClient:
    def __init__(self):
        self.transport = _FakeTransport()
        self.channel = _FakeChannel()
        self.connect_kwargs = None

    def load_host_keys(self, path):
        pass

    def set_missing_host_key_policy(self, policy):
        pass

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs

    def get_transport(self):
        return self.transport

    def open_sftp(self):
        return SimpleNamespace(get_channel=lambda: self.channel)


def test_connect_sftp_sets_keepalive_and_stall_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    fake = _FakeSSHClient()
    monkeypatch.setattr(core.paramiko, "SSHClient", lambda: fake)

    secrets = {
        "AMP_SFTP_HOST": "host", "AMP_SFTP_PORT": "2224",
        "AMP_SFTP_USER": "u", "AMP_SFTP_PASS": "p",
    }
    client, sftp = connect_sftp(secrets, log=lambda *_a: None, stall_timeout=42)

    assert client is fake
    assert fake.transport.keepalive == SFTP_KEEPALIVE
    assert fake.channel.timeout == 42
    # The connect call still carries the handshake timeouts.
    assert fake.connect_kwargs["timeout"] == 30
    assert fake.connect_kwargs["auth_timeout"] == 30


def test_existing_remote_match_is_replaced_in_place(tmp_path):
    pud = tmp_path / "post_update"
    _write(str(pud / "config" / "existing.toml"))
    updater = _updater(_cfg())
    sftp = FakeSFTP(["/config/some/existing.toml"])  # already on the server, nested

    updater._upload_post_update_files(sftp, str(pud))

    assert "/config/some/existing.toml" in _remotes(sftp)
    assert "/config/existing.toml" not in _remotes(sftp)
    assert updater.unplaced_config == []


# ---------------------------------------------------------------------------
# _sync_neoforge_version
# ---------------------------------------------------------------------------
class _FakeAMPInstanceAPI:
    """Records calls instead of hitting a real AMP instance."""

    current_value = "21.1.247"

    def __init__(self, base_url, instance_id, log=print):
        self.base_url = base_url
        self.instance_id = instance_id
        self.calls = []

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def get_config(self, node):
        self.calls.append(("get_config", node))
        return {"CurrentValue": self.current_value, "EnumValues": {"21.1.249": "21.1.249"}}

    def set_config(self, node, value):
        self.calls.append(("set_config", node, value))

    def update_application(self):
        self.calls.append(("update_application",))

    def wait_for_update(self, is_cancelled=None):
        self.calls.append(("wait_for_update",))


def _updater_with_amp(cfg, monkeypatch, fake_api_cls=_FakeAMPInstanceAPI):
    secrets = {
        "AMP_WEBHOOK_URL": "https://amp.example.com/API/WebhookPlugin/Trigger",
        "AMP_API_USER": "bot",
        "AMP_API_PASS": "hunter2",
    }
    captured = {}

    def factory(base_url, instance_id, log=print):
        api = fake_api_cls(base_url, instance_id, log=log)
        captured["api"] = api
        return api

    monkeypatch.setattr(amp_api, "AMPInstanceAPI", factory)
    updater = Updater(cfg, secrets, log=lambda *_a: None)
    return updater, captured


def test_sync_neoforge_version_sets_config_and_triggers_update(monkeypatch):
    cfg = _cfg(amp_instance_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    updater, captured = _updater_with_amp(cfg, monkeypatch)

    updater._sync_neoforge_version("neoforge-21.1.249-installer.jar")

    api = captured["api"]
    assert api.base_url == "https://amp.example.com"
    assert ("login", "bot", "hunter2") in api.calls
    assert ("set_config", amp_api.NEOFORGE_VERSION_NODE, "21.1.249") in api.calls
    assert ("update_application",) in api.calls
    assert ("wait_for_update",) in api.calls


def test_sync_neoforge_version_skips_update_when_already_current(monkeypatch):
    class _AlreadyCurrent(_FakeAMPInstanceAPI):
        current_value = "21.1.249"

    cfg = _cfg(amp_instance_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    updater, captured = _updater_with_amp(cfg, monkeypatch, fake_api_cls=_AlreadyCurrent)

    updater._sync_neoforge_version("neoforge-21.1.249-installer.jar")

    api = captured["api"]
    assert not any(call[0] == "set_config" for call in api.calls)
    assert not any(call[0] == "update_application" for call in api.calls)


def test_sync_neoforge_version_requires_instance_id(monkeypatch):
    cfg = _cfg(amp_instance_id="")
    updater, _captured = _updater_with_amp(cfg, monkeypatch)

    with pytest.raises(UpdateError, match="instance ID"):
        updater._sync_neoforge_version("neoforge-21.1.249-installer.jar")


def test_sync_neoforge_version_requires_parseable_installer_name(monkeypatch):
    cfg = _cfg(amp_instance_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    updater, _captured = _updater_with_amp(cfg, monkeypatch)

    with pytest.raises(UpdateError, match="NeoForge version"):
        updater._sync_neoforge_version("forge-1.20.1-installer.jar")


def test_sync_neoforge_version_rejects_unlisted_version(monkeypatch):
    cfg = _cfg(amp_instance_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    updater, _captured = _updater_with_amp(cfg, monkeypatch)

    with pytest.raises(UpdateError, match="doesn't list"):
        updater._sync_neoforge_version("neoforge-99.9.999-installer.jar")
