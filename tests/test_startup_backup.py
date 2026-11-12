from types import SimpleNamespace

import pytest

import app.services.startup_backup as startup_backup


@pytest.mark.parametrize("role", ["manager", "operator", "viewer"])
def test_non_admin_login_skips_automatic_backup(role, monkeypatch):
    def unexpected_backup_call(*args, **kwargs):
        pytest.fail("Non-admin login must not invoke admin-only backup operations.")

    monkeypatch.setattr(startup_backup, "has_backup_today", unexpected_backup_call)

    startup_backup.run_auto_backup_if_needed(SimpleNamespace(role=role))
