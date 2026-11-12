import sqlite3
import time
from decimal import Decimal

import pytest

from app.data.db import create_db_engine, init_db, make_session_factory
from app.security.session_context import get_current_user, set_current_user
from app.security.permissions import PermissionDeniedError
from app.services.auth import create_user
from app.services.backup import (
    BackupError,
    RestoreError,
    create_backup,
    has_backup_today,
    list_backups,
    prune_backups,
    restore_backup,
    verify_backup_integrity,
)
from app.services.master_data import create_product


@pytest.fixture(autouse=True)
def authenticated_users():
    engine = create_db_engine(db_path=":memory:")
    init_db(engine)
    factory = make_session_factory(engine)

    with factory() as session:
        admin = create_user(
            session, "backup-admin", "test-password-123", role="admin"
        )
        session.commit()
        set_current_user(admin)

        operator = create_user(
            session, "backup-operator", "test-password-123", role="operator"
        )
        session.commit()

        set_current_user(admin)
        yield {"admin": admin, "operator": operator}

        set_current_user(None)

    engine.dispose()


def _make_db_with_product(db_path):
    previous_user = get_current_user()
    set_current_user(None)

    engine = create_db_engine(db_path=str(db_path))
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        admin = create_user(
            session, "admin", "test-password-123", role="admin"
        )
        session.commit()
        set_current_user(admin)

        create_product(
            session, sku="SKU-1", name="Widget", category_id=None, unit_id=None,
            location_id=None, price=Decimal("2"),
            reorder_level=Decimal("0"), opening_stock=Decimal("10"),
        )
        session.commit()
    engine.dispose()
    set_current_user(previous_user)


def test_backup_operations_require_admin(tmp_path, authenticated_users):
    db_path = tmp_path / "inventory.db"
    backup_dir = tmp_path / "backups"
    _make_db_with_product(db_path)

    admin = authenticated_users["admin"]
    operator = authenticated_users["operator"]

    set_current_user(None)
    with pytest.raises(PermissionDeniedError):
        create_backup(db_path, backup_dir)

    set_current_user(operator)
    with pytest.raises(PermissionDeniedError):
        create_backup(db_path, backup_dir)

    with pytest.raises(PermissionDeniedError):
        list_backups(backup_dir)

    with pytest.raises(PermissionDeniedError):
        prune_backups(backup_dir)

    with pytest.raises(PermissionDeniedError):
        has_backup_today(backup_dir)

    with pytest.raises(PermissionDeniedError):
        restore_backup(db_path, tmp_path / "restored.db")

    set_current_user(admin)


def test_create_backup_copies_current_data(tmp_path):
    db_path = tmp_path / "inventory.db"
    backup_dir = tmp_path / "backups"
    _make_db_with_product(db_path)

    backup_path = create_backup(db_path, backup_dir)

    assert backup_path.exists()
    conn = sqlite3.connect(str(backup_path))
    row = conn.execute("SELECT sku FROM products").fetchone()
    conn.close()
    assert row == ("SKU-1",)


def test_create_backup_raises_when_no_database_exists(tmp_path):
    with pytest.raises(BackupError):
        create_backup(tmp_path / "missing.db", tmp_path / "backups")


def test_list_backups_sorted_newest_first(tmp_path):
    db_path = tmp_path / "inventory.db"
    backup_dir = tmp_path / "backups"
    _make_db_with_product(db_path)

    first = create_backup(db_path, backup_dir)
    time.sleep(1.05)
    second = create_backup(db_path, backup_dir)

    backups = list_backups(backup_dir)
    assert backups[0] == second
    assert backups[1] == first


def test_prune_backups_keeps_only_the_newest(tmp_path):
    db_path = tmp_path / "inventory.db"
    backup_dir = tmp_path / "backups"
    _make_db_with_product(db_path)

    for _ in range(5):
        create_backup(db_path, backup_dir)
        time.sleep(1.05)

    removed = prune_backups(backup_dir, keep=2)

    assert len(removed) == 3
    assert len(list_backups(backup_dir)) == 2


def test_has_backup_today(tmp_path):
    db_path = tmp_path / "inventory.db"
    backup_dir = tmp_path / "backups"
    _make_db_with_product(db_path)

    assert has_backup_today(backup_dir) is False
    create_backup(db_path, backup_dir)
    assert has_backup_today(backup_dir) is True


def test_verify_backup_integrity_true_for_valid_db(tmp_path):
    db_path = tmp_path / "inventory.db"
    backup_dir = tmp_path / "backups"
    _make_db_with_product(db_path)
    backup_path = create_backup(db_path, backup_dir)

    assert verify_backup_integrity(backup_path) is True


def test_verify_backup_integrity_false_for_corrupted_file(tmp_path):
    corrupt_file = tmp_path / "corrupt.db"
    corrupt_file.write_bytes(b"not a real sqlite file at all")

    assert verify_backup_integrity(corrupt_file) is False


def test_restore_backup_replaces_database_contents(tmp_path):
    db_path = tmp_path / "inventory.db"
    backup_dir = tmp_path / "backups"
    _make_db_with_product(db_path)
    backup_path = create_backup(db_path, backup_dir)

    db_path.write_bytes(b"garbage - simulating a damaged live database")

    restore_backup(backup_path, db_path)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT sku FROM products").fetchone()
    conn.close()
    assert row == ("SKU-1",)


def test_restore_backup_rejects_corrupted_backup_file(tmp_path):
    db_path = tmp_path / "inventory.db"
    _make_db_with_product(db_path)

    corrupt_backup = tmp_path / "backups" / "bad_backup.db"
    corrupt_backup.parent.mkdir(parents=True, exist_ok=True)
    corrupt_backup.write_bytes(b"not a valid sqlite database")

    with pytest.raises(RestoreError):
        restore_backup(corrupt_backup, db_path)


def test_restore_backup_raises_when_backup_file_missing(tmp_path):
    with pytest.raises(RestoreError):
        restore_backup(tmp_path / "does_not_exist.db", tmp_path / "inventory.db")
