"""Unit tests for window state and session manager in HPC Studio Linux."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from hpc_studio.core.state import (
    PYSIDE6_AVAILABLE,
    SessionState,
    StateManager,
    WindowState,
)

if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QTextEdit


def test_default_window_and_session_state() -> None:
    """Test default values of WindowState and SessionState."""
    w_state = WindowState()
    assert w_state.geometry_b64 == ""
    assert w_state.state_b64 == ""
    assert w_state.is_maximized is False
    assert w_state.is_fullscreen is False
    assert w_state.dock_visibility == {}

    s_state = SessionState()
    assert s_state.active_profile is None
    assert s_state.recent_profiles == []
    assert s_state.recent_local_paths == []
    assert s_state.recent_remote_paths == []
    assert s_state.open_tabs == []
    assert s_state.active_tab_index == 0


def test_state_serialization() -> None:
    """Test dictionary serialization and deserialization."""
    w_state = WindowState(
        geometry_b64="AQAAAB4A...",
        state_b64="BAAAAD1...",
        is_maximized=True,
        dock_visibility={"explorer": True, "terminal": False},
    )
    w_dict = w_state.to_dict()
    assert w_dict["is_maximized"] is True
    assert w_dict["dock_visibility"]["explorer"] is True

    restored_w = WindowState.from_dict(w_dict)
    assert restored_w.geometry_b64 == "AQAAAB4A..."
    assert restored_w.is_maximized is True
    assert restored_w.dock_visibility["terminal"] is False

    s_state = SessionState(
        active_profile="HPC_Cluster_A",
        recent_profiles=["HPC_Cluster_A", "Local_Test"],
        recent_remote_paths=["/scratch/user", "/home/user"],
    )
    s_dict = s_state.to_dict()
    assert s_dict["active_profile"] == "HPC_Cluster_A"

    restored_s = SessionState.from_dict(s_dict)
    assert restored_s.active_profile == "HPC_Cluster_A"
    assert restored_s.recent_profiles == ["HPC_Cluster_A", "Local_Test"]


def test_state_save_and_load(tmp_path: Path) -> None:
    """Test persisting state atomically to disk and reloading."""
    layout_file = tmp_path / "layout.json"
    manager = StateManager(layout_file=layout_file)

    # Initial load returns default states
    w, s = manager.load()
    assert w.is_maximized is False

    # Modify and save
    manager.window_state.is_maximized = True
    manager.session_state.active_profile = "Cluster_Beta"
    manager.save()

    assert layout_file.exists()
    # Check permissions 0o600
    file_stat = os.stat(layout_file)
    assert stat.S_IMODE(file_stat.st_mode) == 0o600

    # Load with another manager
    new_manager = StateManager(layout_file=layout_file)
    w_loaded, s_loaded = new_manager.load()
    assert w_loaded.is_maximized is True
    assert s_loaded.active_profile == "Cluster_Beta"


def test_recent_entries_management(tmp_path: Path) -> None:
    """Test managing recent profiles, local paths, and remote paths."""
    layout_file = tmp_path / "layout.json"
    manager = StateManager(layout_file=layout_file)

    # Add profiles
    manager.add_recent_profile("Cluster1")
    manager.add_recent_profile("Cluster2")
    manager.add_recent_profile("Cluster1")  # Move to front

    assert manager.session_state.recent_profiles == ["Cluster1", "Cluster2"]
    assert manager.session_state.active_profile == "Cluster1"

    # Add local paths
    manager.add_recent_local_path("/path/one")
    manager.add_recent_local_path("/path/two")
    manager.add_recent_local_path("/path/one")
    assert manager.session_state.recent_local_paths == ["/path/one", "/path/two"]

    # Add remote paths
    manager.add_recent_remote_path("/remote/scratch")
    assert manager.session_state.recent_remote_paths == ["/remote/scratch"]


def test_corrupted_layout_recovery(tmp_path: Path) -> None:
    """Test recovering gracefully from corrupted layout.json."""
    layout_file = tmp_path / "layout.json"
    layout_file.write_text("INVALID_JSON_CONTENT{{{", encoding="utf-8")

    manager = StateManager(layout_file=layout_file)
    w, s = manager.load()

    assert w.is_maximized is False
    assert s.active_profile is None

    # Corrupted backup exists
    backup = tmp_path / "layout.json.corrupted"
    assert backup.exists()
    assert "INVALID_JSON_CONTENT" in backup.read_text(encoding="utf-8")


def test_reset_layout(tmp_path: Path) -> None:
    """Test resetting layout clears geometry and persists clean state."""
    layout_file = tmp_path / "layout.json"
    manager = StateManager(layout_file=layout_file)
    manager.window_state.geometry_b64 = "SOME_GEOMETRY"
    manager.save()

    manager.reset_layout()
    assert manager.window_state.geometry_b64 == ""

    # Verify disk
    reloaded_manager = StateManager(layout_file=layout_file)
    assert reloaded_manager.window_state.geometry_b64 == ""


@pytest.mark.skipif(not PYSIDE6_AVAILABLE, reason="PySide6 is required for QMainWindow tests")
def test_qmainwindow_state_capture_and_restore(tmp_path: Path) -> None:
    """Test capturing and restoring state with a real QMainWindow."""
    # Ensure offscreen Qt application exists
    app = QApplication.instance()
    if app is None:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app = QApplication([])

    window = QMainWindow()
    window.setObjectName("MainWindow")
    dock = QDockWidget("Test Dock", window)
    dock.setObjectName("TestDock")
    dock.setWidget(QTextEdit())
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    window.resize(1024, 768)
    window.show()

    layout_file = tmp_path / "qt_layout.json"
    manager = StateManager(layout_file=layout_file)

    # Capture state
    manager.capture_window_state(window)
    assert manager.window_state.geometry_b64 != ""
    assert manager.window_state.state_b64 != ""
    manager.save()

    # Create new window and restore state
    new_window = QMainWindow()
    new_window.setObjectName("MainWindow")
    new_dock = QDockWidget("Test Dock", new_window)
    new_dock.setObjectName("TestDock")
    new_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, new_dock)
    new_window.resize(1024, 768)
    new_window.show()

    geom, state = manager.restore_window_state(new_window)
    assert geom is not None
    assert state is not None
    assert geom == QByteArray.fromBase64(manager.window_state.geometry_b64.encode("ascii"))
    window.close()
    new_window.close()
