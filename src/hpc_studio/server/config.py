"""Configuration module for HPC Studio backend server."""

import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ServerConfig:
    """Server configuration settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    workspace_dir: Path = field(default_factory=Path.cwd)
    start_time: float = field(default_factory=time.time)
    version: str = "0.1.0"
    debug: bool = False

    def __post_init__(self):
        # Resolve workspace path
        if isinstance(self.workspace_dir, str):
            self.workspace_dir = Path(self.workspace_dir)
        self.workspace_dir = self.workspace_dir.resolve()
        # If token was passed as empty string, generate ephemeral one
        if not self.token:
            self.token = secrets.token_urlsafe(32)

    @property
    def uptime(self) -> float:
        """Return server uptime in seconds."""
        return time.time() - self.start_time
