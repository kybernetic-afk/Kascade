import pytest

from kascade.amp_api import AMPAPIError, AMPInstanceAPI, parse_neoforge_version


def test_parse_neoforge_version_matches_installer_filename():
    assert parse_neoforge_version("neoforge-21.1.249-installer.jar") == "21.1.249"


def test_parse_neoforge_version_ignores_non_neoforge_filenames():
    assert parse_neoforge_version("forge-1.20.1-47.4.0-installer.jar") is None
    assert parse_neoforge_version("neoforge-21.1.249-universal.jar") is None


def test_rejects_plain_http_to_a_non_local_host():
    with pytest.raises(AMPAPIError):
        AMPInstanceAPI("http://amp.example.com", "instance-id")


def test_allows_plain_http_to_a_local_host():
    # Should not raise.
    AMPInstanceAPI("http://localhost:8080", "instance-id")


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_login_raises_on_rejected_credentials(monkeypatch):
    api = AMPInstanceAPI("https://amp.example.com", "instance-id")
    monkeypatch.setattr(
        "kascade.amp_api.requests.post",
        lambda *a, **k: _FakeResponse(200, {"success": False, "resultReason": "nope"}),
    )
    with pytest.raises(AMPAPIError, match="nope"):
        api.login("user", "pass")


def test_call_raises_on_amp_error_payload(monkeypatch):
    api = AMPInstanceAPI("https://amp.example.com", "instance-id")
    monkeypatch.setattr(
        "kascade.amp_api.requests.post",
        lambda *a, **k: _FakeResponse(
            200, {"Title": "Unauthorized Access", "Message": "nope", "StackTrace": None}
        ),
    )
    with pytest.raises(AMPAPIError, match="nope"):
        api.get_config("Some.Node")


def test_wait_for_update_returns_once_no_tasks_are_running(monkeypatch):
    api = AMPInstanceAPI("https://amp.example.com", "instance-id")
    monkeypatch.setattr(api, "get_tasks", lambda: [])
    api.wait_for_update(timeout=10, poll_interval=0)


def test_wait_for_update_times_out_if_tasks_never_clear(monkeypatch):
    api = AMPInstanceAPI("https://amp.example.com", "instance-id")
    monkeypatch.setattr(api, "get_tasks", lambda: [{"id": "still-running"}])
    with pytest.raises(AMPAPIError, match="Timed out"):
        api.wait_for_update(timeout=0.05, poll_interval=0)


def test_check_permissions_all_pass(monkeypatch):
    api = AMPInstanceAPI("https://amp.example.com", "instance-id")
    monkeypatch.setattr(api, "get_config", lambda node: {"CurrentValue": "21.1.247"})
    monkeypatch.setattr(api, "set_config", lambda node, value: None)
    monkeypatch.setattr(api, "current_session_has_permission", lambda node: True)

    checks = api.check_permissions()

    assert [c.label for c in checks] == [
        "Read the NeoForge Version setting",
        "Change the NeoForge Version setting",
        "Trigger Download / Update",
    ]
    assert all(c.ok for c in checks)


def test_check_permissions_stops_after_failed_read(monkeypatch):
    api = AMPInstanceAPI("https://amp.example.com", "instance-id")
    monkeypatch.setattr(api, "get_config", lambda node: (_ for _ in ()).throw(AMPAPIError("no read access")))

    checks = api.check_permissions()

    assert len(checks) == 1
    assert checks[0].ok is False
    assert "no read access" in checks[0].detail


def test_check_permissions_flags_missing_write_and_update_permission(monkeypatch):
    api = AMPInstanceAPI("https://amp.example.com", "instance-id")
    monkeypatch.setattr(api, "get_config", lambda node: {"CurrentValue": "21.1.247"})
    monkeypatch.setattr(
        api, "set_config", lambda node, value: (_ for _ in ()).throw(AMPAPIError("write denied"))
    )
    monkeypatch.setattr(api, "current_session_has_permission", lambda node: False)

    checks = api.check_permissions()

    by_label = {c.label: c for c in checks}
    assert by_label["Read the NeoForge Version setting"].ok is True
    assert by_label["Change the NeoForge Version setting"].ok is False
    assert "write denied" in by_label["Change the NeoForge Version setting"].detail
    assert by_label["Trigger Download / Update"].ok is False
    assert "Core.AppManagement.UpdateApplication" in by_label["Trigger Download / Update"].detail
