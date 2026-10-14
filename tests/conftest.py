"""Pytest configuration and headless fixtures for HPC Studio backend testing."""

from __future__ import annotations

from contextlib import contextmanager
import time
from typing import Any, Callable

import pytest


class HeadlessQtBot:
    """Headless test helper providing wait, waitUntil, and waitSignal."""

    def wait(self, ms: int) -> None:
        time.sleep(ms / 1000.0)

    def waitUntil(self, callback: Callable[[], bool], timeout: int = 5000) -> None:
        start_time = time.monotonic()
        timeout_sec = timeout / 1000.0
        while not callback():
            if time.monotonic() - start_time > timeout_sec:
                raise TimeoutError(f"waitUntil timed out after {timeout} ms")
            time.sleep(0.01)

    @contextmanager
    def waitSignal(self, signal: Any, timeout: int = 5000) -> Any:
        fired = []

        def handler(*args: Any) -> None:
            fired.append(args)

        signal.connect(handler)
        try:
            yield
            start_time = time.monotonic()
            timeout_sec = timeout / 1000.0
            while not fired:
                if time.monotonic() - start_time > timeout_sec:
                    raise TimeoutError(f"waitSignal timed out after {timeout} ms")
                time.sleep(0.01)
        finally:
            signal.disconnect(handler)


@pytest.fixture
def qtbot() -> HeadlessQtBot:
    """Fixture simulating qtbot for headless signal and async event testing."""
    return HeadlessQtBot()


@pytest.fixture
def qapp() -> Any:
    """Fixture simulating qapp event loop for headless execution."""
    class DummyQApp:
        def processEvents(self) -> None:
            pass

    return DummyQApp()
