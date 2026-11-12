import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from app.utils.timezone import KIGALI_TIMEZONE, kigali_now
from app.security.permissions import require_admin

BACKUP_PREFIX = "inventory_backup_"
BACKUP_SUFFIX = ".db"
DEFAULT_RETENTION = 14


class BackupError(Exception):
    pass


class RestoreError(Exception):
    pass


def _timestamp_name() -> str:
    return kigali_now().strftime("%Y%m%d_%H%M%S")


def create_backup(db_path: Path, backup_dir: Path) -> Path:
    require_admin()

    db_path = Path(db_path)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise BackupError(f"No database found at {db_path}")

    dest_path = backup_dir / f"{BACKUP_PREFIX}{_timestamp_name()}{BACKUP_SUFFIX}"

    source_conn = sqlite3.connect(str(db_path))
    dest_conn = sqlite3.connect(str(dest_path))
    try:
        source_conn.backup(dest_conn)
    except sqlite3.Error as exc:
        raise BackupError(f"Backup failed: {exc}") from exc
    finally:
        dest_conn.close()
        source_conn.close()

    return dest_path


def list_backups(backup_dir: Path) -> list[Path]:
    require_admin()

    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    files = [
        p for p in backup_dir.iterdir()
        if p.is_file() and p.name.startswith(BACKUP_PREFIX) and p.suffix == BACKUP_SUFFIX
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def prune_backups(backup_dir: Path, keep: int = DEFAULT_RETENTION) -> list[Path]:
    require_admin()

    backups = list_backups(backup_dir)
    to_remove = backups[keep:]
    for path in to_remove:
        path.unlink(missing_ok=True)
    return to_remove


def has_backup_today(backup_dir: Path) -> bool:
    require_admin()

    today = kigali_now().date()
    for path in list_backups(backup_dir):
        backup_date = datetime.fromtimestamp(
            path.stat().st_mtime, tz=KIGALI_TIMEZONE
        ).date()
        if backup_date == today:
            return True
    return False


def verify_backup_integrity(backup_path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(backup_path))
    except sqlite3.DatabaseError:
        return False

    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        return result is not None and result[0] == "ok"
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()


def restore_backup(backup_path: Path, db_path: Path) -> None:
    require_admin()

    backup_path = Path(backup_path)
    db_path = Path(db_path)

    if not backup_path.exists():
        raise RestoreError(f"Backup file not found: {backup_path}")
    if not verify_backup_integrity(backup_path):
        raise RestoreError("Backup file failed integrity check and will not be restored")

    try:
        shutil.copy2(backup_path, db_path)
    except OSError as exc:
        raise RestoreError(f"Could not restore backup: {exc}") from exc
