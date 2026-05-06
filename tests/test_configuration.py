import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from configuration import Settings  # noqa: E402


def test_load_from_dict_preserves_non_ascii_characters():
    cfg = Settings.load_from_dict({"file_path": "Moje testovací složka s nabodeníčky/*"})
    assert cfg.file_path == "Moje testovací složka s nabodeníčky/*"
