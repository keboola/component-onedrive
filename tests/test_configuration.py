import dacite

from configuration import Settings


def test_load_preserves_non_ascii_characters():
    cfg = dacite.from_dict(Settings, {"file_path": "Moje testovací složka s nabodeníčky/*"})
    assert cfg.file_path == "Moje testovací složka s nabodeníčky/*"
