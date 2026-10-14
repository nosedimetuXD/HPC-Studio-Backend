"""SFTP Client Manager wrapping Paramiko SFTPClient with directory caching and cluster paths.

Provides:
- SFTPClientManager: Wrapper on top of paramiko.SFTPClient.
- Operations: listdir_attr, stat, mkdir, rmdir, remove, rename, exists.
- In-memory directory caching with TTL to optimize cluster navigation.
- HPC cluster fast paths detection: /home/$USER, /scratch/$USER, /tmp, /work/$USER.
"""

from __future__ import annotations

import logging
import posixpath
import stat
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import paramiko

from .models import RemoteFileInfo

logger = logging.getLogger(__name__)


class SFTPError(Exception):
    """Base exception for SFTP operations."""


class SFTPNotConnectedError(SFTPError):
    """Raised when SFTP operations are requested while client is not connected."""


class SFTPFileNotFoundError(SFTPError):
    """Raised when a remote file or directory does not exist."""


class SFTPClientManager:
    """High-level wrapper around paramiko.SFTPClient with caching and HPC awareness."""

    def __init__(
        self,
        sftp_client: Optional[paramiko.SFTPClient] = None,
        cache_ttl_seconds: float = 30.0,
        cluster_username: Optional[str] = None,
    ) -> None:
        self._sftp: Optional[paramiko.SFTPClient] = sftp_client
        self._cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Tuple[float, List[RemoteFileInfo]]] = {}
        self._cluster_username = cluster_username

    @property
    def is_connected(self) -> bool:
        """True if the underlying SFTP client is connected and transport active."""
        if self._sftp is None:
            return False
        # paramiko.SFTPClient wraps a Channel
        channel = getattr(self._sftp, "get_channel", lambda: None)()
        if channel is None:
            return True  # May be a mock object or transport-less test client
        return not channel.is_closed()

    @property
    def raw_client(self) -> Optional[paramiko.SFTPClient]:
        """Direct access to Paramiko SFTPClient instance."""
        return self._sftp

    def set_client(
        self,
        sftp_client: Optional[paramiko.SFTPClient],
        cluster_username: Optional[str] = None,
    ) -> None:
        """Assign an active SFTP client session and invalidate existing cache."""
        self._sftp = sftp_client
        if cluster_username:
            self._cluster_username = cluster_username
        self.clear_cache()

    def clear_cache(self, path: Optional[str] = None) -> None:
        """Clear cached directory listings. If path is provided, clear only that entry."""
        if path is not None:
            norm_path = self.normalize_path(path)
            self._cache.pop(norm_path, None)
        else:
            self._cache.clear()

    @staticmethod
    def normalize_path(path: str) -> str:
        """Normalize remote POSIX path."""
        if not path:
            return "/"
        # Ensure path begins with /
        norm = posixpath.normpath(path)
        if not norm.startswith("/"):
            norm = "/" + norm
        return norm

    def get_cluster_fast_paths(self) -> List[Dict[str, str]]:
        """Return well-known HPC directory shortcuts based on cluster username."""
        username = self._cluster_username or "user"
        paths = [
            {"name": "Home", "path": f"/home/{username}", "icon": "home"},
            {"name": "Scratch", "path": f"/scratch/{username}", "icon": "scratch"},
            {"name": "Work", "path": f"/work/{username}", "icon": "folder"},
            {"name": "Tmp", "path": "/tmp", "icon": "temp"},
        ]
        return paths

    def _ensure_connected(self) -> paramiko.SFTPClient:
        """Raise error if client is not available."""
        if self._sftp is None:
            raise SFTPNotConnectedError("SFTP client is not connected.")
        return self._sftp

    def listdir_attr(
        self,
        path: str = ".",
        use_cache: bool = True,
    ) -> List[RemoteFileInfo]:
        """List directory contents returning RemoteFileInfo items, sorted directories-first."""
        sftp = self._ensure_connected()
        norm_path = self.normalize_path(path)

        # Check cache
        now = time.monotonic()
        if use_cache and norm_path in self._cache:
            timestamp, cached_items = self._cache[norm_path]
            if now - timestamp < self._cache_ttl:
                return list(cached_items)

        try:
            raw_attrs = sftp.listdir_attr(norm_path)
        except IOError as exc:
            # Typically FileNotFoundError or PermissionError from SFTP
            err_code = getattr(exc, "errno", None)
            if str(exc).lower().find("no such file") != -1 or err_code == 2:
                raise SFTPFileNotFoundError(f"Directory not found: {norm_path}") from exc
            raise SFTPError(f"Failed to list directory {norm_path}: {exc}") from exc
        except Exception as exc:
            raise SFTPError(f"Unexpected error listing {norm_path}: {exc}") from exc

        items: List[RemoteFileInfo] = []
        for attr in raw_attrs:
            raw_name = getattr(attr, "filename", None) or str(attr)
            if raw_name in (".", ".."):
                continue

            # Security check: Sanitize and reject malicious filenames from remote SFTP (Path Traversal)
            safe_name = posixpath.basename(raw_name.replace("\\", "/"))
            if not safe_name or safe_name in (".", "..") or "\x00" in raw_name:
                logger.warning("Skipping malicious/invalid remote filename %r in directory %s", raw_name, norm_path)
                continue

            if safe_name != raw_name:
                logger.warning("Sanitized remote path traversal entry: %r -> %r in %s", raw_name, safe_name, norm_path)

            item = RemoteFileInfo.from_sftp_attr(name=safe_name, parent_path=norm_path, attr=attr)
            items.append(item)


        # Sort: directories first (alphabetical), then files (alphabetical)
        items.sort(key=lambda x: (not x.is_dir, x.name.lower()))

        # Store in cache
        self._cache[norm_path] = (now, items)
        return items

    def stat(self, path: str) -> RemoteFileInfo:
        """Get attributes and metadata for a specific remote path."""
        sftp = self._ensure_connected()
        norm_path = self.normalize_path(path)

        try:
            attr = sftp.stat(norm_path)
            name = posixpath.basename(norm_path) or "/"
            parent = posixpath.dirname(norm_path)
            return RemoteFileInfo.from_sftp_attr(name=name, parent_path=parent, attr=attr)
        except IOError as exc:
            if str(exc).lower().find("no such file") != -1 or getattr(exc, "errno", None) == 2:
                raise SFTPFileNotFoundError(f"Remote file not found: {norm_path}") from exc
            raise SFTPError(f"Failed to stat remote path {norm_path}: {exc}") from exc
        except Exception as exc:
            raise SFTPError(f"Unexpected error stating {norm_path}: {exc}") from exc

    def exists(self, path: str) -> bool:
        """Check whether remote file or directory exists."""
        try:
            self.stat(path)
            return True
        except (SFTPFileNotFoundError, SFTPError):
            return False

    def is_dir(self, path: str) -> bool:
        """Check whether remote path is a directory."""
        try:
            info = self.stat(path)
            return info.is_dir
        except Exception:
            return False

    def mkdir(self, path: str, mode: int = 0o755) -> None:
        """Create remote directory and invalidate parent cache."""
        sftp = self._ensure_connected()
        norm_path = self.normalize_path(path)
        try:
            sftp.mkdir(norm_path, mode=mode)
            # Invalidate parent cache
            parent = posixpath.dirname(norm_path)
            self.clear_cache(parent)
        except Exception as exc:
            raise SFTPError(f"Failed to create remote directory {norm_path}: {exc}") from exc

    def makedirs(self, path: str, mode: int = 0o755) -> None:
        """Recursively create remote directory hierarchy."""
        norm_path = self.normalize_path(path)
        parts = norm_path.strip("/").split("/")
        current = ""
        for part in parts:
            current += "/" + part
            if not self.exists(current):
                self.mkdir(current, mode=mode)

    def rmdir(self, path: str) -> None:
        """Remove empty remote directory and invalidate parent cache."""
        sftp = self._ensure_connected()
        norm_path = self.normalize_path(path)
        try:
            sftp.rmdir(norm_path)
            parent = posixpath.dirname(norm_path)
            self.clear_cache(parent)
            self.clear_cache(norm_path)
        except Exception as exc:
            raise SFTPError(f"Failed to remove directory {norm_path}: {exc}") from exc

    def remove(self, path: str) -> None:
        """Remove a remote file and invalidate parent cache."""
        sftp = self._ensure_connected()
        norm_path = self.normalize_path(path)
        try:
            sftp.remove(norm_path)
            parent = posixpath.dirname(norm_path)
            self.clear_cache(parent)
        except Exception as exc:
            raise SFTPError(f"Failed to remove file {norm_path}: {exc}") from exc

    def rename(self, oldpath: str, newpath: str) -> None:
        """Rename or move a remote file/directory."""
        sftp = self._ensure_connected()
        norm_old = self.normalize_path(oldpath)
        norm_new = self.normalize_path(newpath)
        try:
            sftp.rename(norm_old, norm_new)
            self.clear_cache(posixpath.dirname(norm_old))
            self.clear_cache(posixpath.dirname(norm_new))
        except Exception as exc:
            raise SFTPError(f"Failed to rename {norm_old} -> {norm_new}: {exc}") from exc

    def close(self) -> None:
        """Close SFTP client and purge cache."""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception as exc:
                logger.debug("Error closing sftp client: %s", exc)
            self._sftp = None
        self.clear_cache()
