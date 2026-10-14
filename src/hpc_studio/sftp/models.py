"""Data models and value objects for SFTP file operations and transfer queue management.

Provides:
- RemoteFileInfo: Dataclass for remote filesystem metadata (name, size, is_dir, permissions, mtime).
- TransferDirection: Enum (UPLOAD, DOWNLOAD).
- TransferStatus: Enum (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED).
- TransferJob: Dataclass for transfer status, speed tracking, ETA formatting.
- Utility formatters for file sizes, transfer speed, and elapsed/ETA time.
"""

from __future__ import annotations

import posixpath
import stat
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TransferDirection(str, Enum):
    """Direction of the file transfer."""

    UPLOAD = "upload"
    DOWNLOAD = "download"


class TransferStatus(str, Enum):
    """Lifecycle status of a transfer job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def format_size(size_bytes: Optional[int]) -> str:
    """Format raw byte counts into human-readable strings (B, KB, MB, GB, TB)."""
    if size_bytes is None or size_bytes < 0:
        return "-"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    units = ["KB", "MB", "GB", "TB", "PB"]
    val = float(size_bytes)
    for unit in units:
        val /= 1024.0
        if val < 1024.0 or unit == units[-1]:
            return f"{val:.1f} {unit}"
    return f"{val:.1f} PB"


def format_speed(bps: float) -> str:
    """Format speed in bytes/sec into human-readable MB/s or KB/s."""
    if bps <= 0:
        return "0.0 MB/s"
    if bps < 1024:
        return f"{bps:.0f} B/s"
    mbps = bps / (1024 * 1024)
    if mbps >= 0.1:
        return f"{mbps:.2f} MB/s"
    kbps = bps / 1024
    return f"{kbps:.1f} KB/s"


def format_eta(seconds: Optional[float]) -> str:
    """Format remaining seconds into human-readable HH:MM:SS or mm:ss."""
    if seconds is None or seconds < 0 or seconds > 86400 * 7:  # more than a week or undefined
        return "--:--"
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


@dataclass
class RemoteFileInfo:
    """Metadata representing a file or directory on the remote SFTP host."""

    name: str
    path: str
    size: int = 0
    is_dir: bool = False
    is_symlink: bool = False
    mtime: Optional[float] = None
    permissions: Optional[int] = None
    owner_uid: Optional[int] = None
    group_gid: Optional[int] = None

    @classmethod
    def from_sftp_attr(cls, name: str, parent_path: str, attr: object) -> RemoteFileInfo:
        """Construct RemoteFileInfo from Paramiko SFTPAttributes or mock object with sanitization."""
        # Sanitize filename against Path Traversal and illegal characters
        clean_name = posixpath.basename(name.replace("\\", "/"))
        if not clean_name or clean_name in (".", "..") or "\x00" in name:
            # Fallback for root or dot cases while preventing traversal
            clean_name = name.replace("\x00", "").strip() or "unnamed"

        # Clean parent path formatting
        norm_parent = parent_path.rstrip("/")
        if not norm_parent:
            full_path = f"/{clean_name}"
        else:
            full_path = f"{norm_parent}/{clean_name}"


        st_mode = getattr(attr, "st_mode", 0) or 0
        st_size = getattr(attr, "st_size", 0) or 0
        st_mtime = getattr(attr, "st_mtime", None)
        st_uid = getattr(attr, "st_uid", None)
        st_gid = getattr(attr, "st_gid", None)

        is_dir = stat.S_ISDIR(st_mode) if st_mode else False
        is_symlink = stat.S_ISLNK(st_mode) if st_mode else False

        return cls(
            name=clean_name,
            path=full_path,
            size=st_size,
            is_dir=is_dir,
            is_symlink=is_symlink,
            mtime=float(st_mtime) if st_mtime is not None else None,
            permissions=st_mode,
            owner_uid=st_uid,
            group_gid=st_gid,
        )

    @property
    def permissions_str(self) -> str:
        """Format UNIX permission bits into standard string (e.g. drwxr-xr-x or -rw-r--r--)."""
        if self.permissions is None:
            return "drwxr-xr-x" if self.is_dir else "-rw-r--r--"
        try:
            return stat.filemode(self.permissions)
        except Exception:
            return "-rw-r--r--"

    @property
    def size_formatted(self) -> str:
        """Human-readable size format."""
        if self.is_dir:
            return "<DIR>"
        return format_size(self.size)

    @property
    def mtime_formatted(self) -> str:
        """Formatted modification timestamp."""
        if self.mtime is None:
            return "-"
        try:
            dt = datetime.fromtimestamp(self.mtime)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "-"

    @property
    def is_hidden(self) -> bool:
        """True if the filename starts with a period (dotfile/dotfolder)."""
        return self.name.startswith(".")


@dataclass
class TransferJob:
    """State tracking for an individual or aggregate transfer task."""

    source_path: str
    dest_path: str
    direction: TransferDirection
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    total_bytes: int = 0
    transferred_bytes: int = 0
    status: TransferStatus = TransferStatus.PENDING
    speed_bps: float = 0.0
    eta_seconds: Optional[float] = None
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    is_directory: bool = False

    @property
    def progress_percentage(self) -> float:
        """Percentage completed (0.0 to 100.0)."""
        if self.total_bytes <= 0:
            return 100.0 if self.status == TransferStatus.COMPLETED else 0.0
        return min(100.0, max(0.0, (self.transferred_bytes / self.total_bytes) * 100.0))

    @property
    def speed_formatted(self) -> str:
        """Human-readable speed string (e.g. '12.45 MB/s')."""
        if self.status != TransferStatus.RUNNING:
            return "0.0 MB/s"
        return format_speed(self.speed_bps)

    @property
    def eta_formatted(self) -> str:
        """Human-readable remaining time string (e.g. '01:23')."""
        if self.status != TransferStatus.RUNNING:
            return "--:--"
        return format_eta(self.eta_seconds)

    @property
    def transferred_size_formatted(self) -> str:
        """Human-readable transferred bytes (e.g. '12.5 MB')."""
        return format_size(self.transferred_bytes)

    @property
    def total_size_formatted(self) -> str:
        """Human-readable total bytes (e.g. '100.0 MB')."""
        return format_size(self.total_bytes)
