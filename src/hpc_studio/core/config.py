"""Configuration and preferences management for HPC Studio Linux.

Provides secure atomic loading, saving, environment variable overriding,
and default paths for user profiles and sessions adhering to XDG standards.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Base exception for configuration errors."""


class ConfigSaveError(ConfigError):
    """Raised when configuration cannot be safely persisted to disk."""


class ConfigLoadError(ConfigError):
    """Raised when configuration cannot be loaded or parsed."""


def _scrub_secrets(obj: Any) -> Any:
    """Recursively scrub sensitive keys (passwords, tokens, keys) from dicts before persistence."""
    sensitive_patterns = ("password", "passphrase", "secret", "token", "private_key", "key_data", "credential")
    if isinstance(obj, dict):
        clean_dict = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(pat in k_lower for pat in sensitive_patterns):
                logger.warning("Redacting sensitive key '%s' from persistent configuration.", k)
                continue
            clean_dict[k] = _scrub_secrets(v)
        return clean_dict
    elif isinstance(obj, list):
        return [_scrub_secrets(item) for item in obj]
    return obj


def get_xdg_config_dir() -> Path:
    """Return the configuration base directory adhering to XDG specification."""
    override = os.environ.get("HPC_STUDIO_CONFIG_DIR")
    if override and "\x00" not in override:
        p = Path(override).expanduser()
        if p.is_absolute():
            return p.resolve()
        logger.warning("Ignoring invalid relative HPC_STUDIO_CONFIG_DIR: %s", override)

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home and "\x00" not in xdg_config_home:
        p = Path(xdg_config_home).expanduser()
        if p.is_absolute():
            return (p / "hpc-studio").resolve()
        logger.warning("Ignoring non-absolute XDG_CONFIG_HOME according to XDG spec: %s", xdg_config_home)

    return (Path.home() / ".config" / "hpc-studio").resolve()


def get_xdg_data_dir() -> Path:
    """Return the data base directory adhering to XDG specification."""
    override = os.environ.get("HPC_STUDIO_DATA_DIR")
    if override and "\x00" not in override:
        p = Path(override).expanduser()
        if p.is_absolute():
            return p.resolve()
        logger.warning("Ignoring invalid relative HPC_STUDIO_DATA_DIR: %s", override)

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home and "\x00" not in xdg_data_home:
        p = Path(xdg_data_home).expanduser()
        if p.is_absolute():
            return (p / "hpc-studio").resolve()
        logger.warning("Ignoring non-absolute XDG_DATA_HOME according to XDG spec: %s", xdg_data_home)

    return (Path.home() / ".local" / "share" / "hpc-studio").resolve()


def get_xdg_cache_dir() -> Path:
    """Return the cache base directory adhering to XDG specification."""
    override = os.environ.get("HPC_STUDIO_CACHE_DIR")
    if override and "\x00" not in override:
        p = Path(override).expanduser()
        if p.is_absolute():
            return p.resolve()
        logger.warning("Ignoring invalid relative HPC_STUDIO_CACHE_DIR: %s", override)

    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home and "\x00" not in xdg_cache_home:
        p = Path(xdg_cache_home).expanduser()
        if p.is_absolute():
            return (p / "hpc-studio").resolve()
        logger.warning("Ignoring non-absolute XDG_CACHE_HOME according to XDG spec: %s", xdg_cache_home)

    return (Path.home() / ".cache" / "hpc-studio").resolve()



@dataclass
class GeneralConfig:
    """General desktop application preferences."""

    theme: str = "dark"  # 'dark', 'light', 'system'
    language: str = "en"
    font_family: str = "Monospace"
    font_size: int = 12
    check_updates: bool = True
    log_level: str = "INFO"


@dataclass
class SSHConfig:
    """SSH connection and remote environment preferences."""

    default_config_path: str = str(Path.home() / ".ssh" / "config")
    known_hosts_path: str = str(Path.home() / ".ssh" / "known_hosts")
    connection_timeout: int = 10
    keepalive_interval: int = 30
    use_agent: bool = True
    default_remote_scratch: str = "/scratch/$USER"


@dataclass
class SlurmConfig:
    """Slurm queue monitor preferences."""

    refresh_interval_sec: int = 10
    auto_notify_jobs: bool = True
    notify_on_finish: bool = True
    notify_on_fail: bool = True
    max_job_history: int = 200


@dataclass
class EditorConfig:
    """Editor and input form builder preferences."""

    tab_size: int = 4
    use_spaces: bool = True
    auto_save_interval_sec: int = 60
    show_line_numbers: bool = True
    word_wrap: bool = False


@dataclass
class AppConfig:
    """Root configuration tree for HPC Studio Linux."""

    general: GeneralConfig = field(default_factory=GeneralConfig)
    ssh: SSHConfig = field(default_factory=SSHConfig)
    slurm: SlurmConfig = field(default_factory=SlurmConfig)
    editor: EditorConfig = field(default_factory=EditorConfig)
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Create AppConfig recursively from dictionary with graceful defaults."""
        general_data = data.get("general", {})
        ssh_data = data.get("ssh", {})
        slurm_data = data.get("slurm", {})
        editor_data = data.get("editor", {})
        custom_data = data.get("custom", {})

        return cls(
            general=GeneralConfig(
                theme=str(general_data.get("theme", GeneralConfig.theme)),
                language=str(general_data.get("language", GeneralConfig.language)),
                font_family=str(general_data.get("font_family", GeneralConfig.font_family)),
                font_size=int(general_data.get("font_size", GeneralConfig.font_size)),
                check_updates=bool(general_data.get("check_updates", GeneralConfig.check_updates)),
                log_level=str(general_data.get("log_level", GeneralConfig.log_level)),
            ),
            ssh=SSHConfig(
                default_config_path=str(ssh_data.get("default_config_path", SSHConfig.default_config_path)),
                known_hosts_path=str(ssh_data.get("known_hosts_path", SSHConfig.known_hosts_path)),
                connection_timeout=int(ssh_data.get("connection_timeout", SSHConfig.connection_timeout)),
                keepalive_interval=int(ssh_data.get("keepalive_interval", SSHConfig.keepalive_interval)),
                use_agent=bool(ssh_data.get("use_agent", SSHConfig.use_agent)),
                default_remote_scratch=str(ssh_data.get("default_remote_scratch", SSHConfig.default_remote_scratch)),
            ),
            slurm=SlurmConfig(
                refresh_interval_sec=int(slurm_data.get("refresh_interval_sec", SlurmConfig.refresh_interval_sec)),
                auto_notify_jobs=bool(slurm_data.get("auto_notify_jobs", SlurmConfig.auto_notify_jobs)),
                notify_on_finish=bool(slurm_data.get("notify_on_finish", SlurmConfig.notify_on_finish)),
                notify_on_fail=bool(slurm_data.get("notify_on_fail", SlurmConfig.notify_on_fail)),
                max_job_history=int(slurm_data.get("max_job_history", SlurmConfig.max_job_history)),
            ),
            editor=EditorConfig(
                tab_size=int(editor_data.get("tab_size", EditorConfig.tab_size)),
                use_spaces=bool(editor_data.get("use_spaces", EditorConfig.use_spaces)),
                auto_save_interval_sec=int(editor_data.get("auto_save_interval_sec", EditorConfig.auto_save_interval_sec)),
                show_line_numbers=bool(editor_data.get("show_line_numbers", EditorConfig.show_line_numbers)),
                word_wrap=bool(editor_data.get("word_wrap", EditorConfig.word_wrap)),
            ),
            custom=dict(custom_data) if isinstance(custom_data, dict) else {},
        )


class ConfigManager:
    """Thread-safe manager for loading, persisting, and querying configuration."""

    def __init__(self, config_dir: Optional[Path] = None, config_file: Optional[Path] = None) -> None:
        self._lock = threading.RLock()
        self._config_dir = (Path(config_dir).absolute() if config_dir else get_xdg_config_dir())
        self._config_file = (Path(config_file).absolute() if config_file else (self._config_dir / "config.json"))
        self._profiles_dir = (self._config_dir / "profiles")
        self._sessions_dir = (self._config_dir / "sessions")
        self._logs_dir = (get_xdg_cache_dir() / "logs")

        self._current_config: AppConfig = AppConfig()
        self._loaded = False

    @property
    def config_dir(self) -> Path:
        """Root configuration directory."""
        return self._config_dir

    @property
    def config_file(self) -> Path:
        """Absolute path to config.json."""
        return self._config_file

    @property
    def profiles_dir(self) -> Path:
        """Directory storing SSH & HPC connection profiles."""
        return self._profiles_dir

    @property
    def sessions_dir(self) -> Path:
        """Directory storing session workspace states."""
        return self._sessions_dir

    @property
    def logs_dir(self) -> Path:
        """Directory storing application log files."""
        return self._logs_dir

    @property
    def config(self) -> AppConfig:
        """Get current loaded configuration."""
        with self._lock:
            if not self._loaded:
                self.load()
            return self._current_config

    def ensure_directories(self) -> None:
        """Ensure all required configuration and data directories exist with restricted permissions."""
        with self._lock:
            for directory in [self._config_dir, self._profiles_dir, self._sessions_dir, self._logs_dir]:
                if directory.is_symlink():
                    raise ConfigError(f"Directory path {directory} is an insecure symlink.")
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                if directory.exists() and hasattr(os, "getuid") and directory.stat().st_uid == os.getuid():
                    try:
                        os.chmod(directory, 0o700)
                    except OSError:
                        pass

    def apply_environment_overrides(self, config: AppConfig) -> AppConfig:
        """Override configuration fields from environment variables.

        Supported overrides:
        - HPC_STUDIO_THEME -> general.theme
        - HPC_STUDIO_LOG_LEVEL -> general.log_level
        - HPC_STUDIO_SSH_TIMEOUT -> ssh.connection_timeout
        - HPC_STUDIO_REMOTE_SCRATCH -> ssh.default_remote_scratch
        - HPC_STUDIO_SLURM_REFRESH -> slurm.refresh_interval_sec
        """
        if "HPC_STUDIO_THEME" in os.environ:
            config.general.theme = os.environ["HPC_STUDIO_THEME"].strip().lower()

        if "HPC_STUDIO_LOG_LEVEL" in os.environ:
            config.general.log_level = os.environ["HPC_STUDIO_LOG_LEVEL"].strip().upper()

        if "HPC_STUDIO_SSH_TIMEOUT" in os.environ:
            try:
                config.ssh.connection_timeout = int(os.environ["HPC_STUDIO_SSH_TIMEOUT"])
            except ValueError:
                logger.warning("Invalid HPC_STUDIO_SSH_TIMEOUT value in environment.")

        if "HPC_STUDIO_REMOTE_SCRATCH" in os.environ:
            config.ssh.default_remote_scratch = os.environ["HPC_STUDIO_REMOTE_SCRATCH"].strip()

        if "HPC_STUDIO_SLURM_REFRESH" in os.environ:
            try:
                config.slurm.refresh_interval_sec = int(os.environ["HPC_STUDIO_SLURM_REFRESH"])
            except ValueError:
                logger.warning("Invalid HPC_STUDIO_SLURM_REFRESH value in environment.")

        return config

    def load(self, force_reload: bool = False) -> AppConfig:
        """Load configuration from disk safely.

        If the file does not exist, defaults are created and returned.
        If the file is corrupted, a backup is created and defaults are returned.
        Environment variable overrides are applied on top.
        """
        with self._lock:
            if self._loaded and not force_reload:
                return self._current_config

            self.ensure_directories()

            if self._config_file.is_symlink():
                raise ConfigLoadError(f"Refusing to load configuration: {self._config_file} is a symlink.")

            if not self._config_file.exists():
                logger.info("Configuration file not found. Creating default at %s", self._config_file)
                self._current_config = self.apply_environment_overrides(AppConfig())
                self.save()
                self._loaded = True
                return self._current_config

            # Verify and enforce restricted file permissions (0o600)
            try:
                st = self._config_file.stat()
                if hasattr(os, "getuid") and st.st_uid == os.getuid():
                    current_mode = st.st_mode & 0o777
                    if current_mode != 0o600:
                        os.chmod(self._config_file, 0o600)
            except OSError as perm_err:
                logger.warning("Could not verify permissions on %s: %s", self._config_file, perm_err)

            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

                if not isinstance(raw_data, dict):
                    raise ValueError("Configuration root must be a JSON object.")

                loaded_config = AppConfig.from_dict(raw_data)
            except Exception as err:
                logger.warning("Corrupted or invalid configuration file at %s: %s", self._config_file, err)
                # Create backup of corrupted file safely
                backup_file = self._config_dir / f"{self._config_file.name}.corrupted"
                try:
                    if backup_file.is_symlink():
                        backup_file.unlink()
                    shutil.copy2(self._config_file, backup_file, follow_symlinks=False)
                    if backup_file.exists() and hasattr(os, "getuid") and backup_file.stat().st_uid == os.getuid():
                        os.chmod(backup_file, 0o600)
                    logger.info("Corrupted configuration backed up to %s", backup_file)
                except Exception as backup_err:
                    logger.error("Failed to backup corrupted configuration: %s", backup_err)

                loaded_config = AppConfig()

            self._current_config = self.apply_environment_overrides(loaded_config)
            self._loaded = True
            return self._current_config

    def save(self, config: Optional[AppConfig] = None) -> None:
        """Save configuration atomically to disk using a temporary file.

        Ensures file integrity, secret scrubbing, and user-only read/write permissions (0o600).
        """
        with self._lock:
            self.ensure_directories()

            if self._config_file.is_symlink():
                raise ConfigSaveError(f"Refusing to overwrite symlink configuration file: {self._config_file}")

            target_config = config or self._current_config
            data = _scrub_secrets(target_config.to_dict())

            tmp_file: Optional[Path] = None
            try:
                # Create temp file in same directory to ensure atomic os.replace across filesystems
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    dir=self._config_dir,
                    prefix="config_",
                    suffix=".tmp",
                    encoding="utf-8",
                    delete=False,
                ) as tf:
                    tmp_file = Path(tf.name)
                    json.dump(data, tf, indent=2, ensure_ascii=False)
                    tf.flush()
                    os.fsync(tf.fileno())

                # Set secure user-only file permissions
                os.chmod(tmp_file, 0o600)
                # Atomic rename
                os.replace(tmp_file, self._config_file)

                if config is not None:
                    self._current_config = config
                self._loaded = True
                logger.debug("Configuration safely saved to %s", self._config_file)
            except Exception as err:
                if tmp_file and tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except OSError:
                        pass
                raise ConfigSaveError(f"Failed to persist configuration to {self._config_file}: {err}") from err

    def update(self, updater: Callable[[AppConfig], None]) -> AppConfig:
        """Safely modify configuration using an updater callable and persist changes."""
        with self._lock:
            cfg = self.config
            updater(cfg)
            self.save(cfg)
            return self._current_config

    def reset_to_defaults(self) -> AppConfig:
        """Reset configuration to default values and persist."""
        with self._lock:
            default_cfg = self.apply_environment_overrides(AppConfig())
            self.save(default_cfg)
            return default_cfg


# Global singleton manager instance
_global_config_manager: Optional[ConfigManager] = None
_global_lock = threading.Lock()


def get_config_manager() -> ConfigManager:
    """Return the global ConfigManager singleton."""
    global _global_config_manager
    with _global_lock:
        if _global_config_manager is None:
            _global_config_manager = ConfigManager()
        return _global_config_manager


def get_config() -> AppConfig:
    """Return the currently loaded AppConfig from the global manager."""
    return get_config_manager().config
