"""Tests for the download step.

The real download is replaced with a stand-in, so the tests never use the internet.
"""

import json

import pytest

from conflict_monitor import config, ingest


class FakeResponse:
    """Stands in for the reply from the website."""

    content = b"Entity,Code,Year,Deaths\nNorthland,NTH,2025,1100\n"

    def raise_for_status(self):
        pass


@pytest.fixture
def raw_folder(tmp_path, monkeypatch):
    """Point the project at a temporary folder so tests never touch real data."""
    monkeypatch.setattr(config, "RAW_METADATA_FILE", tmp_path / "download_metadata.json")
    return tmp_path


def test_download_saves_file_and_records_where_it_came_from(raw_folder, monkeypatch):
    monkeypatch.setattr(ingest.requests, "get", lambda *args, **kwargs: FakeResponse())
    dest = raw_folder / "raw.csv"

    ingest.download(url="https://example.org/data.csv", dest=dest)

    assert dest.read_bytes() == FakeResponse.content
    metadata = json.loads((raw_folder / "download_metadata.json").read_text())
    assert metadata["origin"] == "https://example.org/data.csv"
    assert metadata["size_bytes"] == len(FakeResponse.content)
    assert len(metadata["sha256"]) == 64


def test_download_can_keep_a_separate_record(raw_folder, monkeypatch):
    """The second file's record must not overwrite the first file's."""
    monkeypatch.setattr(ingest.requests, "get", lambda *args, **kwargs: FakeResponse())
    record = raw_folder / "download_metadata_by_type.json"

    ingest.download(
        url="https://example.org/by_type.csv",
        dest=raw_folder / "by_type.csv",
        metadata_file=record,
        source_page="https://example.org/by-type-page",
    )

    metadata = json.loads(record.read_text())
    assert metadata["origin"] == "https://example.org/by_type.csv"
    assert metadata["source_page"] == "https://example.org/by-type-page"
    assert not (raw_folder / "download_metadata.json").exists()  # the usual record is untouched


def test_use_local_file_copies_it_into_place(raw_folder, tmp_path):
    source = tmp_path / "my_download.csv"
    source.write_text("Entity,Code,Year,Deaths\n")
    dest = raw_folder / "raw.csv"

    ingest.use_local_file(source, dest=dest)

    assert dest.read_text() == source.read_text()


def test_use_local_file_fails_clearly_when_file_is_missing(raw_folder, tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest.use_local_file(tmp_path / "nothing_here.csv", dest=raw_folder / "raw.csv")
