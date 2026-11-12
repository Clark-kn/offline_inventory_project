"""Best-effort daily backup during an administrator session."""

import logging

from app.config import app_config
from app.config.paths import backup_dir, database_path
from app.data.session import new_session
from app.services.audit import log_action
from app.services.backup import (
    BackupError,
    create_backup,
    has_backup_today,
    prune_backups,
)


def run_auto_backup_if_needed(user) -> None:
    """Run the daily backup only when an administrator is signed in.

    Non-admin users must still be able to enter the application. If one signs
    in first, the next admin login can perform the daily backup.
    """
    if user.role != "admin":
        return

    try:
        if has_backup_today(backup_dir()):
            return

        create_backup(database_path(), backup_dir())
        prune_backups(
            backup_dir(),
            keep=app_config.get_backup_retention(),
        )

        with new_session() as session:
            log_action(session, "auto_backup", "Daily automatic backup")
            session.commit()

    except BackupError as exc:
        logging.getLogger("app").warning(
            "Automatic backup failed: %s", exc
        )
