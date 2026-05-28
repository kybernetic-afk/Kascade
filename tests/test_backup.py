import os
import zipfile

import pytest

from kascade.backup import (
    BackupError,
    MANIFEST_NAME,
    create_backup,
    read_manifest,
    restore_backup,
)


def _write(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


@pytest.fixture
def post_update_dir(tmp_path):
    root = tmp_path / "post_update"
    _write(str(root / "mods" / "extra.jar"), b"jar-bytes")
    _write(str(root / "config" / "mymod.toml"), b"key=value\n")
    _write(str(root / "config" / "nested" / "deep.cfg"), b"nested")
    _write(str(root / "server-files" / "server-icon.png"), b"\x89PNG\r\n")
    # README.txt at the root is NOT in a tracked subfolder, so it should not
    # land in the backup.
    _write(str(root / "README.txt"), b"hello")
    return str(root)


def test_create_backup_includes_expected_files_and_skips_root_readme(tmp_path, post_update_dir):
    zip_path = str(tmp_path / "kascade-backup.zip")
    result = create_backup(post_update_dir, zip_path, ["mods", "config", "server-files"])

    assert os.path.isfile(zip_path)
    assert result.file_count == 4
    assert set(result.folders) == {"mods", "config", "server-files"}

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert MANIFEST_NAME in names
    assert "mods/extra.jar" in names
    assert "config/mymod.toml" in names
    assert "config/nested/deep.cfg" in names
    assert "server-files/server-icon.png" in names
    # README at the root isn't in a tracked subfolder.
    assert "README.txt" not in names


def test_create_backup_manifest_shape(tmp_path, post_update_dir):
    zip_path = str(tmp_path / "b.zip")
    create_backup(post_update_dir, zip_path, ["mods", "config", "server-files"])

    manifest = read_manifest(zip_path)
    assert manifest is not None
    assert manifest["format"] == "kascade-backup"
    assert manifest["version"] >= 1
    assert set(manifest["folders"]) == {"mods", "config", "server-files"}
    assert manifest["file_count"] == 4
    assert "created_utc" in manifest


def test_create_backup_skips_missing_subfolder(tmp_path, post_update_dir):
    zip_path = str(tmp_path / "b.zip")
    # "datapacks" doesn't exist; it should simply not appear in the backup.
    result = create_backup(post_update_dir, zip_path, ["mods", "datapacks"])
    assert result.folders == ["mods"]
    with zipfile.ZipFile(zip_path) as zf:
        assert not any(n.startswith("datapacks/") for n in zf.namelist())


def test_create_backup_empty_subfolder_list_raises(tmp_path):
    with pytest.raises(BackupError):
        create_backup(str(tmp_path), str(tmp_path / "b.zip"), [])


def test_restore_roundtrip_into_empty_dir(tmp_path, post_update_dir):
    zip_path = str(tmp_path / "b.zip")
    create_backup(post_update_dir, zip_path, ["mods", "config", "server-files"])

    target = tmp_path / "fresh"
    result = restore_backup(zip_path, str(target))

    assert result.has_manifest is True
    assert result.file_count == 4
    assert set(result.folders) == {"mods", "config", "server-files"}
    assert (target / "mods" / "extra.jar").read_bytes() == b"jar-bytes"
    assert (target / "config" / "mymod.toml").read_bytes() == b"key=value\n"
    assert (target / "config" / "nested" / "deep.cfg").read_bytes() == b"nested"
    assert (target / "server-files" / "server-icon.png").read_bytes() == b"\x89PNG\r\n"
    # Manifest file should not be extracted to the target tree.
    assert not (target / MANIFEST_NAME).exists()


def test_restore_merges_overwriting_same_names_keeps_other_files(tmp_path, post_update_dir):
    zip_path = str(tmp_path / "b.zip")
    create_backup(post_update_dir, zip_path, ["mods", "config", "server-files"])

    target = tmp_path / "existing"
    # Pre-populate the target with one file that matches a backup entry and
    # one that does not.
    _write(str(target / "mods" / "extra.jar"), b"OLD")
    _write(str(target / "mods" / "keep-me.jar"), b"KEEP")

    restore_backup(zip_path, str(target))

    # Same-named file is overwritten with backup contents.
    assert (target / "mods" / "extra.jar").read_bytes() == b"jar-bytes"
    # Unrelated existing file is left alone (merge semantics).
    assert (target / "mods" / "keep-me.jar").read_bytes() == b"KEEP"


def test_restore_rejects_zip_slip(tmp_path):
    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("../escape.txt", "no")

    target = tmp_path / "dest"
    with pytest.raises(BackupError):
        restore_backup(str(evil_zip), str(target))
    # Make sure the evil file did not land outside the dest dir.
    assert not (tmp_path / "escape.txt").exists()


def test_restore_rejects_absolute_path_member(tmp_path):
    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("/etc/passwd", "no")
    with pytest.raises(BackupError):
        restore_backup(str(evil_zip), str(tmp_path / "dest"))


def test_restore_missing_file_raises(tmp_path):
    with pytest.raises(BackupError):
        restore_backup(str(tmp_path / "nope.zip"), str(tmp_path / "dest"))


def test_restore_bad_zip_raises(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(BackupError):
        restore_backup(str(bad), str(tmp_path / "dest"))


def test_restore_handles_third_party_zip_without_manifest(tmp_path):
    # A plain zip the user assembled by hand still restores; we just flag
    # has_manifest=False so the GUI can warn.
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("mods/handmade.jar", "data")
    result = restore_backup(str(plain), str(tmp_path / "dest"))
    assert result.has_manifest is False
    assert result.file_count == 1
    assert (tmp_path / "dest" / "mods" / "handmade.jar").read_text() == "data"


def test_read_manifest_returns_none_for_non_kascade_zip(tmp_path):
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("hi.txt", "hi")
    assert read_manifest(str(plain)) is None
