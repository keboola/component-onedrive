"""End-to-end wildcard behaviour tests against the async delta engine.

`AsyncDriveEngine._request_json` is patched to return a single fake delta page
containing the whole subtree (which is how Graph's `/delta` flattens it in
practice), and `_stream_to_file` is replaced with a recorder. This locks in
the wildcard semantics of the async download path.
"""

from unittest import mock

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
        "parentReference": {"driveId": DRIVE_ID, "path": parent_path},
    }


def _folder(name, item_id, parent_path):
    return {
        "name": name,
        "id": item_id,
        "folder": {"childCount": 1},
        "parentReference": {"driveId": DRIVE_ID, "path": parent_path},
    }


ROOT = f"/drives/{DRIVE_ID}/root:"
MOJE = f"{ROOT}/Moje testovací složka s nabodeníčky"
INNER = f"{MOJE}/vnořená složka s nabodeníčky"

# Flat delta enumeration of the whole drive subtree (folders + files).
ALL_ITEMS = [
    _folder("data_tests", "id_data_tests", ROOT),
    _folder("Documents", "id_documents", ROOT),
    _folder("Moje testovací složka s nabodeníčky", "id_outer", ROOT),
    _folder("Pictures", "id_pictures", ROOT),
    _file("průvodce.pdf", "id_root_pdf", ROOT),
    _file("zápis.xlsx", "id_root_xlsx", ROOT),
    _file("Book.xlsx", "id_book", f"{ROOT}/data_tests"),
    _file("lokace.xlsx", "id_loc", f"{ROOT}/Documents"),
    _folder("vnořená složka s nabodeníčky", "id_inner", MOJE),
    _file("tabulka.xlsx", "id_inner_xlsx1", INNER),
    _file("dokument s nabodeníčky.pdf", "id_inner_pdf", INNER),
    _file("zápis s nabodeníčky.xlsx", "id_inner_xlsx2", INNER),
]


def _items_under(scope_folder_path: str) -> list[dict]:
    """Items the engine would see when enumerating from a given scope folder.

    For root scope, that's everything. For a sub-folder scope, /delta on that
    folder returns only items within that subtree.
    """
    if not scope_folder_path or scope_folder_path == "/":
        return ALL_ITEMS
    normalized = scope_folder_path.strip("/")
    prefix = f"{ROOT}/{normalized}"
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
