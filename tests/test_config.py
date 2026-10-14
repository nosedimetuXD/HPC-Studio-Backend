"""Unit tests for configuration manager and preferences in HPC Studio Linux."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from hpc_studio.core.config import (
    AppConfig,
    ConfigManager,
    EditorConfig,
    GeneralConfig,
    SSHConfig,
    SlurmConfig,
    get_config_manager,
    get_xdg_cache_dir,
    get_xdg_config_dir,
    get_xdg_data_dir,
)


def test_default_app_config() -> None:
    """Test default values of AppConfig and sub-configurations."""
    config = AppConfig()

    assert config.general.theme == "dark"
    assert config.general.language == "en"
    assert config.general.font_size == 12
    assert config.general.log_level == "INFO"

    assert config.ssh.connection_timeout == 10
    assert config.ssh.keepalive_interval == 30
    assert config.ssh.use_agent is True
    assert "/scratch/$USER" in config.ssh.default_remote_scratch

    assert config.slurm.refresh_interval_sec == 10
    assert config.slurm.auto_notify_jobs is True
    assert config.slurm.max_job_history == 200

    assert config.editor.tab_size == 4
    assert config.editor.use_spaces is True
    assert config.editor.auto_save_interval_sec == 60


def test_app_config_serialization() -> None:
    """Test converting AppConfig to and from dictionary."""
    config = AppConfig()
    config.general.theme = "light"
    config.ssh.connection_timeout = 25
    config.custom["favorite_cluster"] = "cluster01"

    data = config.to_dict()
    assert isinstance(data, dict)
    assert data["general"]["theme"] == "light"
    assert data["ssh"]["connection_timeout"] == 25
    assert data["custom"]["favorite_cluster"] == "cluster01"

    restored = AppConfig.from_dict(data)
    assert restored.general.theme == "light"
    assert restored.ssh.connection_timeout == 25
    assert restored.custom["favorite_cluster"] == "cluster01"


def test_config_paths_and_directories(tmp_path: Path) -> None:
    """Test XDG path resolution and directory creation."""
    config_dir = tmp_path / "custom_config"
    manager = ConfigManager(config_dir=config_dir)

    assert manager.config_dir == config_dir
    assert manager.config_file == config_dir / "config.json"
    assert manager.profiles_dir == config_dir / "profiles"
    assert manager.sessions_dir == config_dir / "sessions"

    manager.ensure_directories()
    assert config_dir.exists()
    assert manager.profiles_dir.exists()
    assert manager.sessions_dir.exists()
    assert manager.logs_dir.exists()


def test_config_save_and_load(tmp_path: Path) -> None:
    """Test saving and loading configuration safely to disk."""
    config_dir = tmp_path / "test_hpc_config"
    manager = ConfigManager(config_dir=config_dir)

    # Initial load creates default config file
    loaded = manager.load()
    assert manager.config_file.exists()
    assert loaded.general.theme == "dark"

    # Check file permissions are restricted to user (0o600)
    file_stat = os.stat(manager.config_file)
    file_mode = stat.S_IMODE(file_stat.st_mode)
    assert file_mode == 0o600

    # Modify and save
    loaded.general.theme = "system"
    loaded.slurm.refresh_interval_sec = 20
    manager.save(loaded)

    # Reload in a new manager instance
    new_manager = ConfigManager(config_dir=config_dir)
    reloaded = new_manager.load()
    assert reloaded.general.theme == "system"
    assert reloaded.slurm.refresh_interval_sec == 20


def test_config_update_callable(tmp_path: Path) -> None:
    """Test updating configuration using the update() helper callable."""
    manager = ConfigManager(config_dir=tmp_path)

    manager.update(lambda cfg: setattr(cfg.general, "font_size", 16))
    assert manager.config.general.font_size == 16

    # Verify persisted to disk
    with open(manager.config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["general"]["font_size"] == 16


def test_config_environment_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test environment variable overrides on loaded configuration."""
    monkeypatch.setenv("HPC_STUDIO_THEME", "light")
    monkeypatch.setenv("HPC_STUDIO_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("HPC_STUDIO_SSH_TIMEOUT", "42")
    monkeypatch.setenv("HPC_STUDIO_REMOTE_SCRATCH", "/lustre/user_scratch")
    monkeypatch.setenv("HPC_STUDIO_SLURM_REFRESH", "5")

    manager = ConfigManager(config_dir=tmp_path)
    loaded = manager.load()

    assert loaded.general.theme == "light"
    assert loaded.general.log_level == "DEBUG"
    assert loaded.ssh.connection_timeout == 42
    assert loaded.ssh.default_remote_scratch == "/lustre/user_scratch"
    assert loaded.slurm.refresh_interval_sec == 5


def test_corrupted_config_recovery(tmp_path: Path) -> None:
    """Test graceful recovery and backup when configuration file is corrupted."""
    config_dir = tmp_path / "corrupt_test"
    config_dir.mkdir(parents=True, exist_ok=True)
    bad_file = config_dir / "config.json"

    # Write malformed JSON
    bad_file.write_text("{ this is not : valid json !!!", encoding="utf-8")

    manager = ConfigManager(config_dir=config_dir)
    loaded = manager.load()

    # Must recover safely to defaults without crashing
    assert loaded.general.theme == "dark"
    # Corrupted file backup should exist
    backup_file = config_dir / "config.json.corrupted"
    assert backup_file.exists()
    assert "{ this is not : valid json" in backup_file.read_text(encoding="utf-8")


def test_reset_to_defaults(tmp_path: Path) -> None:
    """Test resetting configuration back to defaults."""
    manager = ConfigManager(config_dir=tmp_path)
    manager.update(lambda cfg: setattr(cfg.general, "theme", "light"))
    assert manager.config.general.theme == "light"

    manager.reset_to_defaults()
    assert manager.config.general.theme == "dark"


def test_xdg_fallback_and_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test XDG directory resolutions and custom environment variable overrides."""
    custom_cfg = tmp_path / "my_custom_cfg"
    monkeypatch.setenv("HPC_STUDIO_CONFIG_DIR", str(custom_cfg))
    assert get_xdg_config_dir() == custom_cfg.resolve()

    monkeypatch.delenv("HPC_STUDIO_CONFIG_DIR")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))
    assert get_xdg_config_dir() == (tmp_path / "xdg_config" / "hpc-studio").resolve()
