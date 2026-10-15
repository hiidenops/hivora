"""Backups of the panel itself (not of the apps): its database, master key and launch
options, in ``<data>/backups/_hivora/`` (no app slug starts with "_"). Taken before each
schema migration and by ``python -m hivora backup-self``; restored by hand (README).

The archive holds the master key next to the encrypted secrets: whoever has it can read
every app secret. It is 0600 in a 0700 folder; never restored automatically.
"""

import os
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hivora.db.migrate import db_revision

KEEP = 5  # newest archives kept
FOLDER = Path("backups") / "_hivora"
EXTRA = ("secret.key", "install.env")  # beside hivora.db, when present


def backup_panel(data_dir: Path, now: datetime | None = None) -> Path:
    """Archive the panel (database copied with ``VACUUM INTO``: consistent while it runs)
    and keep the ``KEEP`` newest archives. Returns the new archive's path."""
    db = data_dir / "hivora.db"
    if not db.is_file():
        raise FileNotFoundError(f"no panel database to back up: {db}")
    folder = data_dir / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    dest = folder / f"panel-{stamp}-r{db_revision(db) or 'none'}.tar.gz"
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        copy = Path(tmp) / "hivora.db"
        with closing(sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)) as conn:
            conn.execute("VACUUM INTO ?", (str(copy),))
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
                tar.add(copy, "hivora.db")
                for name in EXTRA:
                    if (data_dir / name).is_file():
                        tar.add(data_dir / name, name)
        except BaseException:
            dest.unlink(missing_ok=True)  # never leave half an archive
            raise
    for old in sorted(folder.glob("panel-*.tar.gz"))[:-KEEP]:
        old.unlink()
    return dest
