"""Step 1 of the pipeline: get the raw data.

Downloads the CSV exactly as published and saves it untouched in data/raw/.
It also writes a small metadata file recording where the data came from and
when, so any number in the dashboard can be traced back to its source.

The pipeline downloads two files (the totals and the split by type of
violence), so each function can be told which metadata file to write.
"""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config


def _write_metadata(
    raw_file: Path, origin: str, metadata_file: Path | None = None, source_page: str | None = None
) -> dict:
    """Record where the raw file came from, when, and a fingerprint of its contents."""
    # None means "use the usual setting". The setting is looked up here, when the
    # function runs, rather than in the line above, so the tests can point it elsewhere.
    metadata_file = Path(metadata_file or config.RAW_METADATA_FILE)
    content = raw_file.read_bytes()
    metadata = {
        "origin": origin,
        "source_page": source_page or config.SOURCE_PAGE,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_file.write_text(json.dumps(metadata, indent=2))
    return metadata


def download(
    url: str = config.DATA_URL,
    dest: Path = config.RAW_FILE,
    metadata_file: Path | None = None,
    source_page: str | None = None,
) -> Path:
    """Download the CSV from the web and save it to data/raw/."""
    headers = {"User-Agent": "conflict-risk-monitor/0.1 (learning project)"}
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()  # stop with a clear error if the download failed

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    _write_metadata(dest, origin=url, metadata_file=metadata_file, source_page=source_page)
    return dest


def use_local_file(
    source: Path,
    dest: Path = config.RAW_FILE,
    metadata_file: Path | None = None,
    source_page: str | None = None,
) -> Path:
    """Use a CSV already on disk instead of downloading (offline or blocked network)."""
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"No file at {source}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    _write_metadata(
        dest, origin=f"local file: {source.name}", metadata_file=metadata_file, source_page=source_page
    )
    return dest
