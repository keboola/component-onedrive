"""End-to-end wildcard behaviour tests.

The OneDrive Graph layer is mocked: `_get_folder_contents_onedrive` returns a
fake folder tree, and the actual download is replaced with a recorder that
captures which file names the wildcard machinery decided to fetch. This locks
in the empirically-observed behaviour against a representative folder layout.
"""

from unittest import mock

from client.client import OneDriveClient


def _file(name, item_id):
    return {
        "name": name,
        "id": item_id,
        "file": {},
        "lastModifiedDateTime": "2025-01-01T00:00:00Z",
        "@microsoft.graph.downloadUrl": f"https://example.invalid/{item_id}",
    }


def _folder(name, item_id, child_count=0):
    return {"name": name, "id": item_id, "folder": {"childCount": child_count}}


ROOT_TREE = {
    "root": [
        _folder("data_tests", "id_data_tests", 1),
        _folder("Documents", "id_documents", 1),
        _folder("Moje testovací složka s nabodeníčky", "id_outer", 1),
        _folder("Pictures", "id_pictures", 0),
        _file("průvodce.pdf", "id_root_pdf"),
        _file("zápis.xlsx", "id_root_xlsx"),
    ],
    "id_data_tests": [
        _file("Book.xlsx", "id_book"),
    ],
    "id_documents": [
        _file("lokace.xlsx", "id_loc"),
    ],
    "id_outer": [
        _folder("vnořená složka s nabodeníčky", "id_inner", 3),
    ],
    "id_inner": [
        _file("tabulka.xlsx", "id_inner_xlsx1"),
        _file("dokument s nabodeníčky.pdf", "id_inner_pdf"),
        _file("zápis s nabodeníčky.xlsx", "id_inner_xlsx2"),
    ],
    "id_pictures": [],
}


def _run_download(file_path):
    """Drive `download_files` with a mocked Graph layer; return the list of
    downloaded file names in the order the wildcard code decided to fetch them.
    """
    client = OneDriveClient.__new__(OneDriveClient)
    client.base_url = "https://graph.microsoft.com/v1.0/me"
    client.client_type = "OneDrive"
    client.files_out_folder = "/tmp/ignored"
    client.downloaded_files = []
    client.freshest_file_timestamp = None

    captured = []

    def fake_list(drive_type, folder_id):
        return ROOT_TREE[folder_id]

    def fake_resolve(drive_type, folder_path):
        if folder_path is None or folder_path == "/":
            return "root"
        folder_id = "root"
        for name in [c for c in folder_path.strip("/").split("/") if c]:
            children = ROOT_TREE[folder_id]
            match = next((c for c in children if c.get("folder") is not None and c["name"] == name), None)
            assert match is not None, f"Test fixture missing folder {name!r} under {folder_id!r}"
            folder_id = match["id"]
        return folder_id

    def fake_download(url, output_path, filename):
        captured.append(filename)

    with (
        mock.patch.object(OneDriveClient, "_get_folder_contents_onedrive", side_effect=fake_list),
        mock.patch.object(OneDriveClient, "_resolve_folder_id", side_effect=fake_resolve),
        mock.patch.object(OneDriveClient, "_download_file_from_onedrive_url", side_effect=fake_download),
    ):
        client.download_files(file_path=file_path, output_dir="/tmp/ignored")
    return captured


def test_bare_filename_walks_entire_drive():
    # `Book.xlsx` has no '*', so folder_mask is None and recursion enters every
    # subfolder. The file is found only in data_tests/.
    downloaded = _run_download("Book.xlsx")
    assert downloaded == ["Book.xlsx"]


def test_accent_path_star_pdf_recurses_into_subfolder():
    # `Moje.../*.pdf` looks like "PDFs at this folder", but mask=*.pdf produces
    # folder_mask=* which recurses into subfolders, so the nested PDF gets picked up.
    downloaded = _run_download("Moje testovací složka s nabodeníčky/*.pdf")
    assert downloaded == ["dokument s nabodeníčky.pdf"]


def test_accent_path_star_anything_matches_subfolder_contents():
    # `Moje.../*/*` descends one level (folder_mask=*) and matches every child file.
    downloaded = _run_download("Moje testovací složka s nabodeníčky/*/*")
    assert sorted(downloaded) == sorted(
        [
            "tabulka.xlsx",
            "dokument s nabodeníčky.pdf",
            "zápis s nabodeníčky.xlsx",
        ]
    )


def test_accent_path_star_pdf_nested_picks_only_pdf():
    # `Moje.../*/*.pdf` descends one level, then filters by *.pdf — 1 file.
    downloaded = _run_download("Moje testovací složka s nabodeníčky/*/*.pdf")
    assert downloaded == ["dokument s nabodeníčky.pdf"]


def test_double_star_silently_acts_like_single_star():
    # `**/*.pdf` does NOT fail; it silently recurses into subfolders matching * and
    # filters *.pdf there. Files at the search-root never match because fnmatch
    # tests them against the full `**/*.pdf` (which expects a /).
    downloaded = _run_download("**/*.pdf")
    assert downloaded == ["dokument s nabodeníčky.pdf"]


def test_extension_wildcard_at_root_is_recursive():
    # `*.pdf` at root: folder_mask is None → recurses into every subfolder.
    # Matches both root-level and nested PDFs.
    downloaded = _run_download("*.pdf")
    assert sorted(downloaded) == ["dokument s nabodeníčky.pdf", "průvodce.pdf"]


def test_leading_slash_is_equivalent_to_no_slash():
    # `/Moje.../*/*` and `Moje.../*/*` produce identical results — leading slash is stripped by os.path.normpath.
    a = _run_download("/Moje testovací složka s nabodeníčky/*/*")
    b = _run_download("Moje testovací složka s nabodeníčky/*/*")
    assert sorted(a) == sorted(b)
