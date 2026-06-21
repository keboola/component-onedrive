"""End-to-end wildcard behaviour tests against the async delta engine.

`AsyncDriveEngine._request_json` is patched to return a single fake delta page
containing the whole subtree (which is how Graph's `/delta` flattens it in
practice), and `_stream_to_file` is replaced with a recorder. Parent paths in
the fixtures are URL-encoded just like Graph returns them in production. This
locks in the wildcard semantics of the async download path, including the
"folder names with spaces / unicode" case.
"""

from unittest import mock
from urllib.parse import quote

from client.async_engine import AsyncDriveEngine
from client.client import OneDriveClient

DRIVE_ID = "test-drive-id"


def _file(name, item_id, parent_path):
    return {
        "name": name,
        "id": item_id,
        "file": {},
        "lastModifiedDateTime": "2025-01-01T00:00:00Z",
        "@microsoft.graph.downloadUrl": f"https://example.invalid/{item_id}",
        "parentReference": {"driveId": DRIVE_ID, "path": quote(parent_path, safe="/:")},
    }


def _folder(name, item_id, parent_path):
    return {
        "name": name,
        "id": item_id,
        "folder": {"childCount": 1},
        "parentReference": {"driveId": DRIVE_ID, "path": quote(parent_path, safe="/:")},
    }


ROOT = f"/drives/{DRIVE_ID}/root:"
MOJE = f"{ROOT}/Moje testovací složka s nabodeníčky"
INNER = f"{MOJE}/vnořená složka s nabodeníčky"
SB = f"{ROOT}/Konfigurátor SB"
PODKLADY = f"{SB}/PODKLADY K CV - pro bankéře"
STEPA = f"{PODKLADY}/Stepa Test"

# Flat delta enumeration of the whole drive subtree (folders + files). Parent
# paths in the helpers above get URL-encoded to mirror Graph's actual response.
ALL_ITEMS = [
    _folder("data_tests", "id_data_tests", ROOT),
    _folder("Documents", "id_documents", ROOT),
    _folder("Moje testovací složka s nabodeníčky", "id_outer", ROOT),
    _folder("Pictures", "id_pictures", ROOT),
    _folder("Konfigurátor SB", "id_sb", ROOT),
    _file("průvodce.pdf", "id_root_pdf", ROOT),
    _file("zápis.xlsx", "id_root_xlsx", ROOT),
    _file("Book.xlsx", "id_book", f"{ROOT}/data_tests"),
    _file("lokace.xlsx", "id_loc", f"{ROOT}/Documents"),
    _folder("vnořená složka s nabodeníčky", "id_inner", MOJE),
    _file("tabulka.xlsx", "id_inner_xlsx1", INNER),
    _file("dokument s nabodeníčky.pdf", "id_inner_pdf", INNER),
    _file("zápis s nabodeníčky.xlsx", "id_inner_xlsx2", INNER),
    _folder("PODKLADY K CV - pro bankéře", "id_podklady", SB),
    _folder("Stepa Test", "id_stepa", PODKLADY),
    _file("kraťasy.xlsm", "id_xlsm_a", STEPA),
    _file("dluhy.xlsm", "id_xlsm_b", STEPA),
    _file("readme.txt", "id_txt", STEPA),
]


def _items_under(scope_folder_path: str) -> list[dict]:
    """Items the engine would see when enumerating from a given scope folder.

    For root scope, that's everything. For a sub-folder scope, /delta on that
    folder returns only items within that subtree. Parent paths in fixtures
    are URL-encoded (matching Graph), so the prefix check encodes too.
    """
    if not scope_folder_path or scope_folder_path == "/":
        return ALL_ITEMS
    normalized = scope_folder_path.strip("/")
    prefix = quote(f"{ROOT}/{normalized}", safe="/:")
    return [
        item
        for item in ALL_ITEMS
        if item["parentReference"]["path"] == prefix or item["parentReference"]["path"].startswith(prefix + "/")
    ]


def _run_download(file_path: str) -> list[str]:
    folder_path, mask = OneDriveClient._split_path_mask(file_path)
    scope = folder_path.strip("/")
    items = _items_under(scope)

    async def fake_request_json(self, url):
        return {"value": items}

    async def fake_stream(self, url, dest, attempt):
        return None

    captured: list[str] = []

    async def fake_token(force_refresh):
        return "token"

    engine = AsyncDriveEngine(
        drive_id=DRIVE_ID,
        scope_folder_id="root" if not scope else "scope-id",
        scope_folder_path=scope,
        mask=mask,
        output_dir="/tmp/ignored",
        last_modified_at=None,
        delta_token_url=None,
        token_provider=fake_token,
    )

    original_download = AsyncDriveEngine._download_item

    async def recording_download(self, item):
        await original_download(self, item)
        captured.append(item["name"])

    with (
        mock.patch.object(AsyncDriveEngine, "_request_json", new=fake_request_json),
        mock.patch.object(AsyncDriveEngine, "_stream_to_file", new=fake_stream),
        mock.patch.object(AsyncDriveEngine, "_download_item", new=recording_download),
    ):
        import asyncio

        asyncio.run(engine.run())

    return captured


def test_bare_filename_walks_entire_drive():
    # `Book.xlsx` has no '*', mask has no slash → fnmatch against name across whole subtree.
    downloaded = _run_download("Book.xlsx")
    assert downloaded == ["Book.xlsx"]


def test_accent_path_star_pdf_recurses_into_subfolder():
    # `Moje.../*.pdf` → scope=Moje, mask=*.pdf (no slash) → matches any *.pdf in the subtree.
    downloaded = _run_download("Moje testovací složka s nabodeníčky/*.pdf")
    assert downloaded == ["dokument s nabodeníčky.pdf"]


def test_accent_path_star_anything_matches_subfolder_contents():
    # `Moje.../*/*` → scope=Moje, mask=*/*, requires exactly two path components below scope.
    downloaded = _run_download("Moje testovací složka s nabodeníčky/*/*")
    assert sorted(downloaded) == sorted(
        [
            "tabulka.xlsx",
            "dokument s nabodeníčky.pdf",
            "zápis s nabodeníčky.xlsx",
        ]
    )


def test_accent_path_star_pdf_nested_picks_only_pdf():
    # `Moje.../*/*.pdf` → scope=Moje, mask=*/*.pdf, two levels deep with *.pdf at leaf.
    downloaded = _run_download("Moje testovací složka s nabodeníčky/*/*.pdf")
    assert downloaded == ["dokument s nabodeníčky.pdf"]


def test_extension_wildcard_at_root_is_recursive():
    # `*.pdf` at root → mask has no slash → matches any *.pdf anywhere in the subtree.
    downloaded = _run_download("*.pdf")
    assert sorted(downloaded) == ["dokument s nabodeníčky.pdf", "průvodce.pdf"]


def test_leading_slash_is_equivalent_to_no_slash():
    a = _run_download("/Moje testovací složka s nabodeníčky/*/*")
    b = _run_download("Moje testovací složka s nabodeníčky/*/*")
    assert sorted(a) == sorted(b)


def test_spaces_in_nested_folder_path_match():
    # User-reported regression: a deeply nested SharePoint path with spaces,
    # accents and hyphens. Graph encodes parentReference.path as %20 / %C3%A1 /
    # etc.; the engine must URL-decode it before comparing to scope_folder_path.
    downloaded = _run_download("Konfigurátor SB/PODKLADY K CV - pro bankéře/Stepa Test/*.xlsm")
    assert sorted(downloaded) == ["dluhy.xlsm", "kraťasy.xlsm"]


def test_spaces_in_path_with_slashed_mask():
    # When the mask itself has a slash, _matches_mask falls through to
    # _relative_path, which has to URL-decode parentReference.path. Without
    # decoding, every file under a space-bearing folder would be dropped.
    downloaded = _run_download("Konfigurátor SB/PODKLADY K CV - pro bankéře/*/*.xlsm")
    assert sorted(downloaded) == ["dluhy.xlsm", "kraťasy.xlsm"]


def _run_for_engine(file_path: str, items: list[dict]) -> AsyncDriveEngine:
    """Drive the engine through one /delta page and return it so the caller can
    inspect downloaded_files (the on-disk names, post-deduplication)."""
    folder_path, mask = OneDriveClient._split_path_mask(file_path)
    scope = folder_path.strip("/")

    async def fake_request_json(self, url):
        return {"value": items}

    async def fake_stream(self, url, dest, attempt):
        return None

    async def fake_token(force_refresh):
        return "token"

    engine = AsyncDriveEngine(
        drive_id=DRIVE_ID,
        scope_folder_id="root" if not scope else "scope-id",
        scope_folder_path=scope,
        mask=mask,
        output_dir="/tmp/ignored",
        last_modified_at=None,
        delta_token_url=None,
        token_provider=fake_token,
    )
    with (
        mock.patch.object(AsyncDriveEngine, "_request_json", new=fake_request_json),
        mock.patch.object(AsyncDriveEngine, "_stream_to_file", new=fake_stream),
    ):
        import asyncio

        asyncio.run(engine.run())
    return engine


def test_duplicate_filenames_get_numeric_suffix():
    # Same file name in two different folders → on-disk we keep both with _2 suffix.
    items = [
        _file("report.xlsx", "id_a", f"{ROOT}/data_tests"),
        _file("report.xlsx", "id_b", f"{ROOT}/Documents"),
        _file("report.xlsx", "id_c", f"{ROOT}/Pictures"),
    ]
    engine = _run_for_engine("report.xlsx", items)
    assert sorted(engine.downloaded_files) == ["report.xlsx", "report_2.xlsx", "report_3.xlsx"]


def test_item_source_path_decodes_url_encoded_parent():
    # parentReference.path is URL-encoded by Graph; _item_source_path must decode
    # it so logs and downstream consumers see the literal path the user typed.
    engine = _run_for_engine("*.xlsm", [])
    item = {
        "name": "kraťasy.xlsm",
        "parentReference": {"path": quote(STEPA, safe="/:")},
    }
    assert engine._item_source_path(item) == "/Konfigurátor SB/PODKLADY K CV - pro bankéře/Stepa Test/kraťasy.xlsm"
