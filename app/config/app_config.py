import json
import os
from pathlib import Path

from app.security.permissions import require_admin

CONFIG_VENDOR = "OfflineInventory"
CONFIG_FILE_NAME = "config.json"
DB_FILE_NAME = "inventory.db"
MIN_BACKUP_RETENTION = 1
MAX_BACKUP_RETENTION = 365


def config_dir() -> Path:
    """Where the small pointer config file lives."""
    base = os.environ.get("APPDATA", str(Path.home()))
    path = Path(base) / CONFIG_VENDOR
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file_path() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def is_configured() -> bool:
    return config_file_path().exists()


def load_config() -> dict:
    path = config_file_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_config(data: dict) -> None:
    config_file_path().write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def get_database_dir() -> Path | None:
    value = load_config().get("database_dir")
    return Path(value) if value else None


def set_database_dir(directory: Path) -> None:
    # First-run setup must work before an administrator can log in.
    # Once configured, only an administrator may change the location.
    if is_configured():
        require_admin()

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config["database_dir"] = str(directory)
    _save_config(config)


def get_configured_database_path() -> Path | None:
    directory = get_database_dir()
    return (directory / DB_FILE_NAME) if directory else None


def get_backup_dir() -> Path | None:
    value = load_config().get("backup_dir")
    return Path(value) if value else None


def set_backup_dir(directory: Path) -> None:
    require_admin()

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config["backup_dir"] = str(directory)
    _save_config(config)


def get_backup_retention() -> int:
    return load_config().get("backup_retention", 14)


def set_backup_retention(count: int) -> None:
    require_admin()

    count = int(count)
    if not MIN_BACKUP_RETENTION <= count <= MAX_BACKUP_RETENTION:
        raise ValueError(
            f"Backup retention must be between "
            f"{MIN_BACKUP_RETENTION} and {MAX_BACKUP_RETENTION} days."
        )

    config = load_config()
    config["backup_retention"] = count
    _save_config(config)
