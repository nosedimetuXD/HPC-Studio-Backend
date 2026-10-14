"""SSH authentication, configuration parsing, client session, and async workers.

Sprint 1.2 backend module for HPC Studio Linux.
"""

from __future__ import annotations

from .auth import (
    KeyLoadError,
    PassphraseRequiredError,
    SSHAuthError,
    SSHAuthManager,
    VolatileCredentialStore,
)
from .client import (
    CommandResult,
    ConnectionState,
    SSHClientError,
    SSHClientManager,
    SSHCommandTimeoutError,
    SSHConnectionError,
    SSHNotConnectedError,
)
from .config_parser import SSHConfigParser, SSHHostEntry
from .worker import SSHCommandWorker, SSHConnectionWorker, SSHDisconnectionWorker

__all__ = [
    "SSHConfigParser",
    "SSHHostEntry",
    "SSHAuthManager",
    "VolatileCredentialStore",
    "SSHAuthError",
    "PassphraseRequiredError",
    "KeyLoadError",
    "SSHClientManager",
    "ConnectionState",
    "CommandResult",
    "SSHClientError",
    "SSHConnectionError",
    "SSHNotConnectedError",
    "SSHCommandTimeoutError",
    "SSHConnectionWorker",
    "SSHDisconnectionWorker",
    "SSHCommandWorker",
]
