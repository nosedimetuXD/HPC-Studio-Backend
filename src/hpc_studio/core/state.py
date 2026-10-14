"""Window layout and session state manager for HPC Studio Linux.

Handles safe atomic serialization and deserialization of QMainWindow geometries,
QDockWidget states, recent files, and session history into ~/.config/hpc-studio/layout.json.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from hpc_studio.core.config import get_xdg_config_dir

logger = logging.getLogger(__name__)

# Attempt to import PySide6 components; fallback gracefully if in headless / test stub mode
try:
    from PySide6.QtCore import QByteArray
    from PySide6.QtWidgets import QMainWindow
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False
    QByteArray = Any  # type: ignore[misc,assignment]
    QMainWindow = Any  # type: ignore[misc,assignment]


class StateError(Exception):
    """Base exception for state management errors."""


class StateSaveError(StateError):
    """Raised when window state cannot be persisted."""


@dataclass
class WindowState:
    """Serialized window geometries, dock layout states, and visibility."""

    geometry_b64: str = ""
    state_b64: str = ""
    is_maximized: bool = False
    is_fullscreen: bool = False
    dock_visibility: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert WindowState to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WindowState:
        """Create WindowState from dictionary."""
        return cls(
            geometry_b64=str(data.get("geometry_b64", "")),
            state_b64=str(data.get("state_b64", "")),
            is_maximized=bool(data.get("is_maximized", False)),
            is_fullscreen=bool(data.get("is_fullscreen", False)),
            dock_visibility=dict(data.get("dock_visibility", {})),
        )


@dataclass
class SessionState:
    """Application session state across launches."""

    active_profile: Optional[str] = None
    last_connected_host: Optional[str] = None
    recent_profiles: List[str] = field(default_factory=list)
    recent_local_paths: List[str] = field(default_factory=list)
    recent_remote_paths: List[str] = field(default_factory=list)
    open_tabs: List[Dict[str, Any]] = field(default_factory=list)
    active_tab_index: int = 0
    custom_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert SessionState to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        """Create SessionState from dictionary."""
        return cls(
            active_profile=data.get("active_profile"),
            last_connected_host=data.get("last_connected_host"),
            recent_profiles=list(data.get("recent_profiles", [])),
            recent_local_paths=list(data.get("recent_local_paths", [])),
            recent_remote_paths=list(data.get("recent_remote_paths", [])),
            open_tabs=list(data.get("open_tabs", [])),
            active_tab_index=int(data.get("active_tab_index", 0)),
            custom_data=dict(data.get("custom_data", {})),
        )


def _scrub_state_secrets(obj: Any) -> Any:
    """Recursively scrub sensitive keys from layout and session dictionaries."""
    sensitive_patterns = ("password", "passphrase", "secret", "token", "private_key", "key_data", "credential")
    if isinstance(obj, dict):
        clean_dict = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(pat in k_lower for pat in sensitive_patterns):
                logger.warning("Redacting sensitive key '%s' from persistent session state.", k)
                continue
            clean_dict[k] = _scrub_state_secrets(v)
        return clean_dict
    elif isinstance(obj, list):
        return [_scrub_state_secrets(item) for item in obj]
    return obj


class StateManager:
    """Manages serialization, storage and restoration of window layout and session."""

    def __init__(
        self,
        organization: Optional[str] = None,
        application: Optional[str] = None,
        layout_file: Optional[Union[Path, str]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self.organization = organization or "HPCStudio"
        self.application = application or "HPCStudio"

        if layout_file is not None:
            self._layout_file = Path(layout_file).absolute()
        elif organization and application and ("Test" in organization or "Test" in application):
            # For testing with custom organization/app in a private user-owned directory
            user_id = os.getuid() if hasattr(os, "getuid") else "user"
            safe_temp_dir = Path(tempfile.gettempdir()) / f"hpc_studio_{user_id}"
            safe_temp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._layout_file = (safe_temp_dir / f"{organization}_{application}_layout.json").absolute()
        else:
            config_dir = get_xdg_config_dir()
            self._layout_file = (config_dir / "layout.json").absolute()

        self._window_state = WindowState()
        self._session_state = SessionState()
        self._loaded = False

    @property
    def layout_file(self) -> Path:
        """Path to layout.json file."""
        return self._layout_file

    @property
    def window_state(self) -> WindowState:
        """Current WindowState."""
        with self._lock:
            if not self._loaded:
                self.load()
            return self._window_state

    @property
    def session_state(self) -> SessionState:
        """Current SessionState."""
        with self._lock:
            if not self._loaded:
                self.load()
            return self._session_state

    def load(self, force_reload: bool = False) -> tuple[WindowState, SessionState]:
        """Safely load layout and session state from disk.

        If the file does not exist or is corrupted, default state is loaded.
        """
        with self._lock:
            if self._loaded and not force_reload:
                return self._window_state, self._session_state

            if self._layout_file.is_symlink():
                raise StateError(f"Refusing to load layout state: {self._layout_file} is a symlink.")

            if not self._layout_file.exists():
                logger.info("Layout file not found at %s. Using default state.", self._layout_file)
                self._window_state = WindowState()
                self._session_state = SessionState()
                self._loaded = True
                return self._window_state, self._session_state

            # Verify and enforce restricted permissions (0o600)
            try:
                st = self._layout_file.stat()
                if hasattr(os, "getuid") and st.st_uid == os.getuid():
                    if (st.st_mode & 0o777) != 0o600:
                        os.chmod(self._layout_file, 0o600)
            except OSError as perm_err:
                logger.warning("Could not verify permissions on %s: %s", self._layout_file, perm_err)

            try:
                with open(self._layout_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

                if not isinstance(raw_data, dict):
                    raise ValueError("Layout state root must be a JSON object.")

                self._window_state = WindowState.from_dict(raw_data.get("window", {}))
                self._session_state = SessionState.from_dict(raw_data.get("session", {}))
            except Exception as err:
                logger.warning("Corrupted or invalid layout file at %s: %s", self._layout_file, err)
                backup_path = self._layout_file.parent / f"{self._layout_file.name}.corrupted"
                try:
                    if backup_path.is_symlink():
                        backup_path.unlink()
                    shutil.copy2(self._layout_file, backup_path, follow_symlinks=False)
                    if backup_path.exists() and hasattr(os, "getuid") and backup_path.stat().st_uid == os.getuid():
                        os.chmod(backup_path, 0o600)
                    logger.info("Corrupted layout backed up to %s", backup_path)
                except Exception as backup_err:
                    logger.error("Failed to backup corrupted layout: %s", backup_err)

                self._window_state = WindowState()
                self._session_state = SessionState()

            self._loaded = True
            return self._window_state, self._session_state

    def save(self) -> None:
        """Persist window state and session state atomically to layout.json."""
        with self._lock:
            if self._layout_file.is_symlink():
                raise StateSaveError(f"Refusing to overwrite symlink layout file: {self._layout_file}")

            target_dir = self._layout_file.parent
            if target_dir.is_symlink():
                raise StateSaveError(f"Layout parent directory {target_dir} is an insecure symlink.")
            target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target_dir.exists() and hasattr(os, "getuid") and target_dir.stat().st_uid == os.getuid():
                try:
                    os.chmod(target_dir, 0o700)
                except OSError:
                    pass

            data = {
                "version": "1.0",
                "organization": self.organization,
                "application": self.application,
                "window": self._window_state.to_dict(),
                "session": _scrub_state_secrets(self._session_state.to_dict()),
            }

            tmp_file: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    dir=target_dir,
                    prefix="layout_",
                    suffix=".tmp",
                    encoding="utf-8",
                    delete=False,
                ) as tf:
                    tmp_file = Path(tf.name)
                    json.dump(data, tf, indent=2, ensure_ascii=False)
                    tf.flush()
                    os.fsync(tf.fileno())

                os.chmod(tmp_file, 0o600)
                os.replace(tmp_file, self._layout_file)
                logger.debug("Layout state safely saved to %s", self._layout_file)
            except Exception as err:
                if tmp_file and tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except OSError:
                        pass
                raise StateSaveError(f"Failed to persist layout state to {self._layout_file}: {err}") from err

    def save_window_state(
        self,
        arg1: Any = None,
        arg2: Any = None,
    ) -> None:
        """Capture and save window geometry and dock states.

        Accepts either:
        - save_window_state(main_window)
        - save_window_state(geom_bytes_or_qbyte, state_bytes_or_qbyte)
        """
        with self._lock:
            geom = None
            state = None
            is_max = False
            is_full = False

            if arg1 is not None and hasattr(arg1, "saveGeometry") and hasattr(arg1, "saveState"):
                # arg1 is QMainWindow
                geom = arg1.saveGeometry()
                state = arg1.saveState()
                if hasattr(arg1, "isMaximized"):
                    is_max = bool(arg1.isMaximized())
                if hasattr(arg1, "isFullScreen"):
                    is_full = bool(arg1.isFullScreen())
            else:
                geom = arg1
                state = arg2

            if geom is not None:
                if hasattr(geom, "toBase64"):
                    self._window_state.geometry_b64 = bytes(geom.toBase64()).decode("ascii")
                elif isinstance(geom, (bytes, bytearray)):
                    self._window_state.geometry_b64 = base64.b64encode(geom).decode("ascii")
                elif isinstance(geom, str):
                    self._window_state.geometry_b64 = geom

            if state is not None:
                if hasattr(state, "toBase64"):
                    self._window_state.state_b64 = bytes(state.toBase64()).decode("ascii")
                elif isinstance(state, (bytes, bytearray)):
                    self._window_state.state_b64 = base64.b64encode(state).decode("ascii")
                elif isinstance(state, str):
                    self._window_state.state_b64 = state

            self._window_state.is_maximized = is_max
            self._window_state.is_fullscreen = is_full
            self.save()

    def capture_window_state(self, main_window: Any) -> None:
        """Explicitly capture geometry and dock states from a QMainWindow instance."""
        self.save_window_state(main_window)

    def restore_window_state(
        self,
        main_window: Any = None,
    ) -> Tuple[Optional[Any], Optional[Any]]:
        """Restore geometry and dock states.

        If main_window is provided, applies restoreGeometry and restoreState directly.
        Returns a tuple of (geometry_bytes, state_bytes) (as QByteArray if PySide6 is available).
        """
        with self._lock:
            if not self._loaded:
                self.load()

            geom_val = None
            state_val = None

            if self._window_state.geometry_b64:
                raw_geom = base64.b64decode(self._window_state.geometry_b64.encode("ascii"))
                if PYSIDE6_AVAILABLE:
                    geom_val = QByteArray(raw_geom)
                else:
                    geom_val = raw_geom

            if self._window_state.state_b64:
                raw_state = base64.b64decode(self._window_state.state_b64.encode("ascii"))
                if PYSIDE6_AVAILABLE:
                    state_val = QByteArray(raw_state)
                else:
                    state_val = raw_state

            if main_window is not None:
                try:
                    if geom_val is not None and hasattr(main_window, "restoreGeometry"):
                        main_window.restoreGeometry(geom_val)
                    if state_val is not None and hasattr(main_window, "restoreState"):
                        main_window.restoreState(state_val)
                    if self._window_state.is_maximized and hasattr(main_window, "showMaximized"):
                        main_window.showMaximized()
                except Exception as err:
                    logger.error("Failed to restore QMainWindow state: %s", err)

            return geom_val, state_val

    def clear(self) -> None:
        """Clear all saved window state and session data."""
        with self._lock:
            self._window_state = WindowState()
            self._session_state = SessionState()
            self.save()

    def reset_layout(self) -> None:
        """Reset window and dock states back to default empty layout."""
        with self._lock:
            self._window_state = WindowState()
            self.save()

    def add_recent_profile(self, profile_name: str, max_entries: int = 10) -> None:
        """Add profile to recent profiles list, avoiding duplicates."""
        with self._lock:
            if not self._loaded:
                self.load()

            recents = [p for p in self._session_state.recent_profiles if p != profile_name]
            recents.insert(0, profile_name)
            self._session_state.recent_profiles = recents[:max_entries]
            self._session_state.active_profile = profile_name
            self.save()

    def add_recent_local_path(self, path: str, max_entries: int = 10) -> None:
        """Add local filesystem path to recent list."""
        with self._lock:
            if not self._loaded:
                self.load()

            recents = [p for p in self._session_state.recent_local_paths if p != path]
            recents.insert(0, path)
            self._session_state.recent_local_paths = recents[:max_entries]
            self.save()

    def add_recent_remote_path(self, path: str, max_entries: int = 10) -> None:
        """Add remote cluster filesystem path to recent list."""
        with self._lock:
            if not self._loaded:
                self.load()

            recents = [p for p in self._session_state.recent_remote_paths if p != path]
            recents.insert(0, path)
            self._session_state.recent_remote_paths = recents[:max_entries]
            self.save()

    def update_session(self, updater: Callable[[SessionState], None]) -> SessionState:
        """Update session state via a callable and save to disk."""
        with self._lock:
            if not self._loaded:
                self.load()

            updater(self._session_state)
            self.save()
            return self._session_state


# Global singleton StateManager instance
_global_state_manager: Optional[StateManager] = None
_global_state_lock = threading.Lock()


def get_state_manager() -> StateManager:
    """Return the global StateManager singleton."""
    global _global_state_manager
    with _global_state_lock:
        if _global_state_manager is None:
            _global_state_manager = StateManager()
        return _global_state_manager
