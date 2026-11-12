from pathlib import Path

import pytest

from app.config import app_config
from app.data.db import create_db_engine, init_db, make_session_factory
from app.security.permissions import PermissionDeniedError
from app.security.session_context import set_current_user
from app.services.auth import create_user


@pytest.fixture(autouse=True)
def authenticated_users(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    engine = create_db_engine(db_path=":memory:")
    init_db(engine)
    factory = make_session_factory(engine)

    with factory() as session:
        admin = create_user(
            session, "config-admin", "test-password-123", role="admin"
        )
        session.commit()
        set_current_user(admin)

        operator = create_user(
            session, "config-operator", "test-password-123", role="operator"
        )
        session.commit()

        yield {"admin": admin, "operator": operator}

    set_current_user(None)
    engine.dispose()


def test_not_configured_until_a_location_is_set():
    assert app_config.is_configured() is False
    assert app_config.get_database_dir() is None
    assert app_config.get_configured_database_path() is None


def test_first_run_database_location_can_be_set_without_login(tmp_path):
    target = tmp_path / "FirstRunData"
    set_current_user(None)

    app_config.set_database_dir(target)

    assert app_config.get_database_dir() == target
    assert target.exists()


def test_set_database_dir_persists_across_loads(tmp_path):
    target = tmp_path / "MyInventoryData"
    app_config.set_database_dir(target)

    assert app_config.is_configured() is True
    assert app_config.get_database_dir() == target
    assert app_config.get_configured_database_path() == target / "inventory.db"


def test_set_database_dir_creates_the_folder(tmp_path):
    target = tmp_path / "does" / "not" / "exist" / "yet"
    assert not target.exists()

    app_config.set_database_dir(target)

    assert target.exists()


def test_reconfiguring_overwrites_the_previous_location(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    app_config.set_database_dir(first)
    app_config.set_database_dir(second)

    assert app_config.get_database_dir() == second


def test_backup_dir_defaults_to_none():
    assert app_config.get_backup_dir() is None


def test_set_backup_dir_persists_and_creates_folder(tmp_path):
    target = tmp_path / "Backups" / "Inventory"
    app_config.set_backup_dir(target)

    assert app_config.get_backup_dir() == target
    assert target.exists()


def test_backup_retention_defaults_to_fourteen():
    assert app_config.get_backup_retention() == 14


def test_set_backup_retention_persists():
    app_config.set_backup_retention(30)
    assert app_config.get_backup_retention() == 30


def test_database_and_backup_settings_do_not_clobber_each_other(tmp_path):
    db_dir = tmp_path / "db"
    backup_dir = tmp_path / "backup"

    app_config.set_database_dir(db_dir)
    app_config.set_backup_dir(backup_dir)
    app_config.set_backup_retention(5)

    assert app_config.get_database_dir() == db_dir
    assert app_config.get_backup_dir() == backup_dir
    assert app_config.get_backup_retention() == 5


def test_config_changes_require_admin(tmp_path, authenticated_users):
    app_config.set_database_dir(tmp_path / "initial")

    for user in (None, authenticated_users["operator"]):
        set_current_user(user)

        with pytest.raises(PermissionDeniedError):
            app_config.set_database_dir(tmp_path / "unauthorized-db")

        with pytest.raises(PermissionDeniedError):
            app_config.set_backup_dir(tmp_path / "unauthorized-backups")

        with pytest.raises(PermissionDeniedError):
            app_config.set_backup_retention(30)

    set_current_user(authenticated_users["admin"])


@pytest.mark.parametrize("invalid_count", [0, -1, 366, 1000])
def test_backup_retention_rejects_out_of_range_values(invalid_count):
    with pytest.raises(ValueError):
        app_config.set_backup_retention(invalid_count)
