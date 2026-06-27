import os
from stat import S_IFDIR, S_IFREG
from types import SimpleNamespace

import pytest

from kascade.core import Updater, find_remote_file, subdir_from_match


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


def _cfg(known=None):
    return SimpleNamespace(
        remote_base="/",
        post_update_folders=["config"],
        known_file_paths={"config": known or {}},
        upload_retries=1,
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


def test_existing_remote_match_is_replaced_in_place(tmp_path):
    pud = tmp_path / "post_update"
    _write(str(pud / "config" / "existing.toml"))
    updater = _updater(_cfg())
    sftp = FakeSFTP(["/config/some/existing.toml"])  # already on the server, nested

    updater._upload_post_update_files(sftp, str(pud))

    assert "/config/some/existing.toml" in _remotes(sftp)
    assert "/config/existing.toml" not in _remotes(sftp)
    assert updater.unplaced_config == []
