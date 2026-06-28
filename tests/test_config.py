from kascade.config import Config


def test_set_config_path_pins_subdir():
    c = Config()
    c.set_config_path("webserver.conf", "bluemap")
    assert c.get_config_path("webserver.conf") == "bluemap"
    assert c.known_file_paths["config"]["webserver.conf"] == "bluemap"


def test_empty_subdir_pins_to_root_not_unpin():
    # A file that lives in config/ root must be pinnable: '' is a real pin (key
    # present, value ''), distinct from 'no pin' (key absent).
    c = Config()
    c.set_config_path("DraconicEvolution.cfg", "")
    assert c.get_config_path("DraconicEvolution.cfg") == ""
    assert "DraconicEvolution.cfg" in c.known_file_paths["config"]


def test_none_unpins():
    c = Config()
    c.set_config_path("foo.toml", "sub")
    c.set_config_path("foo.toml", None)
    assert c.get_config_path("foo.toml") is None
    assert "foo.toml" not in c.known_file_paths["config"]


def test_unpinned_file_returns_none():
    c = Config()
    assert c.get_config_path("never-set.toml") is None


def test_subdir_is_normalized():
    c = Config()
    c.set_config_path("a.cfg", "  /bluemap/maps/ ")
    assert c.get_config_path("a.cfg") == "bluemap/maps"
