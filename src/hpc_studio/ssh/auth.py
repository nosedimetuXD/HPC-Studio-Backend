"""SSH authentication and credential manager for HPC Studio Linux.

Provides integration with local ssh-agent, multi-cipher private key loading
(Ed25519, RSA, ECDSA), and safe in-memory volatile handling of passphrases
without persisting secrets to disk (RNF-03).
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import List, Optional, Union

import paramiko
from paramiko.agent import Agent

logger = logging.getLogger(__name__)


class SSHAuthError(Exception):
    """Base exception for SSH authentication and key loading errors."""


class PassphraseRequiredError(SSHAuthError):
    """Raised when an encrypted private key requires a passphrase or the passphrase is invalid."""


class KeyLoadError(SSHAuthError):
    """Raised when a private key file cannot be read or parsed."""


class VolatileCredentialStore:
    """Thread-safe, strictly in-memory storage for authentication passphrases.

    Complies with RNF-03: No secrets, passwords, or passphrases are ever written
    to disk, temp files, or logs.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._passphrases: dict[str, str] = {}

    def get_passphrase(self, identifier: str) -> Optional[str]:
        """Retrieve passphrase for a key path or host alias."""
        with self._lock:
            return self._passphrases.get(identifier)

    def set_passphrase(self, identifier: str, passphrase: str) -> None:
        """Store passphrase in volatile memory only."""
        with self._lock:
            self._passphrases[identifier] = passphrase

    def remove_passphrase(self, identifier: str) -> bool:
        """Remove a specific passphrase from volatile memory."""
        with self._lock:
            return self._passphrases.pop(identifier, None) is not None

    def has_passphrase(self, identifier: str) -> bool:
        """Check if a passphrase exists in volatile memory."""
        with self._lock:
            return identifier in self._passphrases

    def clear(self) -> None:
        """Clear all secrets from memory."""
        with self._lock:
            self._passphrases.clear()

    def __repr__(self) -> str:
        with self._lock:
            return f"<VolatileCredentialStore [PROTECTED] entries={len(self._passphrases)}>"

    def __str__(self) -> str:
        return "<VolatileCredentialStore [PROTECTED]>"


class SSHAuthManager:
    """Manages credentials, local SSH Agent integration, and private key loaders."""

    STANDARD_KEY_NAMES = (
        "id_ed25519",
        "id_ecdsa",
        "id_rsa",
        "id_dsa",
    )

    def __init__(self, credential_store: Optional[VolatileCredentialStore] = None) -> None:
        self.credential_store = credential_store or VolatileCredentialStore()

    def is_agent_available(self) -> bool:
        """Check if local ssh-agent is running and reachable via SSH_AUTH_SOCK."""
        sock_path = os.environ.get("SSH_AUTH_SOCK")
        if not sock_path:
            return False
        p = Path(sock_path)
        if not p.exists():
            return False
        try:
            if p.is_file() or p.is_dir():
                return False
        except OSError:
            pass

        try:
            agent = Agent()
            # Verify connectivity by querying keys
            agent.get_keys()
            return True
        except Exception as exc:
            logger.debug("ssh-agent unavailable or refused connection: %s", exc)
            return False

    def get_agent(self) -> Optional[Agent]:
        """Return a connected paramiko.agent.Agent instance, or None if unavailable."""
        if not self.is_agent_available():
            return None
        try:
            return Agent()
        except Exception as exc:
            logger.debug("Failed to initialize Agent: %s", exc)
            return None

    def get_agent_keys(self) -> List[paramiko.PKey]:
        """Retrieve public keys loaded into the active local ssh-agent."""
        agent = self.get_agent()
        if not agent:
            return []
        try:
            return list(agent.get_keys())
        except Exception as exc:
            logger.warning("Error reading keys from ssh-agent: %s", exc)
            return []

    def load_private_key(
        self,
        key_path: Union[str, Path],
        passphrase: Optional[str] = None,
    ) -> paramiko.PKey:
        """Load and decrypt a private key (Ed25519, RSA, or ECDSA).

        If passphrase is not provided, looks up in the volatile credential store.
        Raises:
            FileNotFoundError: If the key file does not exist.
            PassphraseRequiredError: If passphrase is missing or incorrect.
            KeyLoadError: If the key file cannot be loaded or format is unsupported.
        """
        path = Path(key_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"SSH private key file not found: {path}")

        # Check permissions on POSIX
        if hasattr(os, "getuid"):
            try:
                st = path.stat()
                if (st.st_mode & 0o077) != 0:
                    logger.warning(
                        "SSH private key %s has unsafe permissions (%s). Should be 0o600.",
                        path,
                        oct(st.st_mode & 0o777),
                    )
            except OSError:
                pass

        effective_passphrase = passphrase
        if effective_passphrase is None:
            effective_passphrase = self.credential_store.get_passphrase(str(path))


        key_classes = (
            paramiko.Ed25519Key,
            paramiko.RSAKey,
            paramiko.ECDSAKey,
        )

        last_password_required: Optional[Exception] = None
        last_ssh_error: Optional[Exception] = None

        for key_cls in key_classes:
            try:
                return key_cls.from_private_key_file(
                    str(path),
                    password=effective_passphrase,
                )
            except paramiko.PasswordRequiredException as err:
                last_password_required = err
            except paramiko.SSHException as err:
                err_msg = str(err).lower()
                if "passphrase" in err_msg or "password" in err_msg or "decrypt" in err_msg:
                    last_password_required = err
                else:
                    last_ssh_error = err
            except Exception as err:
                last_ssh_error = err

        if last_password_required is not None:
            raise PassphraseRequiredError(
                f"Passphrase required or incorrect for key: {path}"
            ) from last_password_required

        raise KeyLoadError(
            f"Failed to load SSH private key from {path}: {last_ssh_error}"
        ) from last_ssh_error

    def get_candidate_keys(
        self, search_dirs: Optional[List[Union[str, Path]]] = None
    ) -> List[Path]:
        """Find existing standard SSH private keys in ~/.ssh or custom directories."""
        dirs = [Path(d).expanduser().resolve() for d in search_dirs] if search_dirs else [Path.home() / ".ssh"]
        candidates: List[Path] = []

        for d in dirs:
            if not d.is_dir():
                continue
            for name in self.STANDARD_KEY_NAMES:
                key_file = d / name
                if key_file.is_file():
                    candidates.append(key_file)

        return candidates

    def store_passphrase(self, identifier: str, passphrase: str) -> None:
        """Store passphrase in volatile in-memory store."""
        self.credential_store.set_passphrase(identifier, passphrase)

    def get_passphrase(self, identifier: str) -> Optional[str]:
        """Retrieve passphrase from volatile in-memory store."""
        return self.credential_store.get_passphrase(identifier)

    def clear_passphrases(self) -> None:
        """Wipe all volatile in-memory passphrases."""
        self.credential_store.clear()
