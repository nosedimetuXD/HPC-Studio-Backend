"""SFTP Engine and Asynchronous File Transfer Package for HPC Studio Linux.

Exports:
- RemoteFileInfo: Dataclass for remote filesystem objects.
- SFTPClientManager: Paramiko SFTPClient wrapper with caching and fast path detection.
- TransferJob: Dataclass for tracking asynchronous transfer lifecycle.
- TransferDirection: Enum (UPLOAD, DOWNLOAD).
- TransferStatus: Enum (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED).
- TransferQueueManager: Asynchronous transfer queue manager.
- SFTPTreeModel: QAbstractItemModel with lazy loading for QTreeView.
- SFTPTreeItem: Tree item node representation.
- Format utilities: format_size, format_speed, format_eta.
"""

from .client import (
    SFTPClientManager,
    SFTPError,
    SFTPFileNotFoundError,
    SFTPNotConnectedError,
)
from .models import (
    RemoteFileInfo,
    TransferDirection,
    TransferJob,
    TransferStatus,
    format_eta,
    format_size,
    format_speed,
)
from .transfer_queue import (
    SpeedTracker,
    TransferQueueManager,
    TransferWorker,
    TransferWorkerSignals,
)

__all__ = [
    "RemoteFileInfo",
    "SFTPClientManager",
    "SFTPError",
    "SFTPFileNotFoundError",
    "SFTPNotConnectedError",
    "TransferJob",
    "TransferDirection",
    "TransferStatus",
    "TransferQueueManager",
    "TransferWorker",
    "TransferWorkerSignals",
    "SpeedTracker",
    "format_size",
    "format_speed",
    "format_eta",
]
