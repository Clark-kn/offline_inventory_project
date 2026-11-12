from pathlib import Path

from app.config.paths import default_data_dir


def test_default_data_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_data_dir() == tmp_path / "OfflineInventory" / "Inventory"


def test_default_data_dir_falls_back_to_home_when_localappdata_is_missing(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_data_dir() == tmp_path / "OfflineInventory" / "Inventory"
