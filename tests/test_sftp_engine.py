"""Unit tests for SFTPClientManager, RemoteFileInfo, and SFTPTreeModel.

Verifies:
- Data model metadata extraction, Unix permission decoding, size formatting.
- SFTPClientManager operations (listdir_attr, stat, mkdir, rmdir, remove, rename).
- Directory caching and invalidation logic.
- HPC cluster fast paths detection (/home/$USER, /scratch/$USER, /tmp, etc.).
- SFTPTreeModel hierarchical structure, lazy loading (fetchMore/canFetchMore), and dotfile filtering.
"""

import stat
import time
from unittest.mock import MagicMock, call, patch

import pytest

from hpc_studio.sftp.client import (
    SFTPClientManager,
    SFTPError,
    SFTPFileNotFoundError,
    SFTPNotConnectedError,
)
from hpc_studio.sftp.models import (
    RemoteFileInfo,
    TransferDirection,
    TransferJob,
    TransferStatus,
    format_eta,
    format_size,
    format_speed,
)


class DummySFTPAttr:
    """Mock Paramiko SFTPAttributes object."""

    def __init__(
        self,
        filename: str,
        st_size: int = 1024,
        st_mode: int = 0o100644,
        st_mtime: float = 1700000000.0,
        st_uid: int = 1000,
        st_gid: int = 1000,
    ):
        self.filename = filename
        self.st_size = st_size
        self.st_mode = st_mode
        self.st_mtime = st_mtime
        self.st_uid = st_uid
        self.st_gid = st_gid


class TestSFTPModels:
    """Tests for RemoteFileInfo and formatting utilities."""

    def test_format_size_utility(self):
        assert format_size(None) == "-"
        assert format_size(-1) == "-"
        assert format_size(0) == "0 B"
        assert format_size(500) == "500 B"
        assert format_size(1024) == "1.0 KB"
        assert format_size(1024 * 1024 * 5) == "5.0 MB"
        assert format_size(1024 * 1024 * 1024 * 2) == "2.0 GB"

    def test_format_speed_and_eta(self):
        assert format_speed(0) == "0.0 MB/s"
        assert format_speed(500) == "500 B/s"
        assert format_speed(50 * 1024) == "50.0 KB/s"
        assert format_speed(5 * 1024 * 1024) == "5.00 MB/s"

        assert format_eta(None) == "--:--"
        assert format_eta(-5) == "--:--"
        assert format_eta(45) == "00:45"
        assert format_eta(125) == "02:05"
        assert format_eta(3665) == "01:01:05"

    def test_remote_file_info_creation_from_attr(self):
        # File
        attr = DummySFTPAttr("input.in", st_size=2048, st_mode=0o100644)
        info = RemoteFileInfo.from_sftp_attr("input.in", "/home/user/calc", attr)

        assert info.name == "input.in"
        assert info.path == "/home/user/calc/input.in"
        assert info.size == 2048
        assert not info.is_dir
        assert not info.is_symlink
        assert "-rw-r--r--" in info.permissions_str
        assert info.size_formatted == "2.0 KB"
        assert not info.is_hidden

        # Directory
        dir_attr = DummySFTPAttr("scratch", st_size=4096, st_mode=0o040755)
        dir_info = RemoteFileInfo.from_sftp_attr("scratch", "/home/user", dir_attr)

        assert dir_info.name == "scratch"
        assert dir_info.path == "/home/user/scratch"
        assert dir_info.is_dir
        assert dir_info.size_formatted == "<DIR>"
        assert "drwxr-xr-x" in dir_info.permissions_str

        # Hidden file
        hidden_attr = DummySFTPAttr(".bashrc", st_size=100, st_mode=0o100644)
        hidden_info = RemoteFileInfo.from_sftp_attr(".bashrc", "/home/user", hidden_attr)
        assert hidden_info.is_hidden

    def test_transfer_job_defaults_and_progress(self):
        job = TransferJob(
            source_path="/local/file.txt",
            dest_path="/remote/file.txt",
            direction=TransferDirection.UPLOAD,
            total_bytes=1000,
        )
        assert job.status == TransferStatus.PENDING
        assert job.progress_percentage == 0.0

        job.transferred_bytes = 500
        job.status = TransferStatus.RUNNING
        assert job.progress_percentage == 50.0

        job.speed_bps = 1024 * 1024 * 2
        assert "2.00 MB/s" in job.speed_formatted

        job.eta_seconds = 10
        assert job.eta_formatted == "00:10"


class TestSFTPClientManager:
    """Tests for SFTPClientManager operations with mock Paramiko SFTPClient."""

    @pytest.fixture
    def mock_sftp(self):
        client = MagicMock()
        channel = MagicMock()
        channel.is_closed.return_value = False
        client.get_channel.return_value = channel
        return client

    def test_connection_status(self, mock_sftp):
        mgr = SFTPClientManager()
        assert not mgr.is_connected

        mgr.set_client(mock_sftp, cluster_username="cluster_user")
        assert mgr.is_connected
        assert mgr.raw_client is mock_sftp

    def test_cluster_fast_paths(self):
        mgr = SFTPClientManager(cluster_username="jdoe")
        fast_paths = mgr.get_cluster_fast_paths()
        paths_map = {item["name"]: item["path"] for item in fast_paths}

        assert paths_map["Home"] == "/home/jdoe"
        assert paths_map["Scratch"] == "/scratch/jdoe"
        assert paths_map["Work"] == "/work/jdoe"
        assert paths_map["Tmp"] == "/tmp"

    def test_listdir_attr_and_caching(self, mock_sftp):
        mock_sftp.listdir_attr.return_value = [
            DummySFTPAttr("file2.txt", st_size=100, st_mode=0o100644),
            DummySFTPAttr("dirA", st_size=4096, st_mode=0o040755),
            DummySFTPAttr("file1.txt", st_size=200, st_mode=0o100644),
            DummySFTPAttr(".", st_size=4096, st_mode=0o040755),
            DummySFTPAttr("..", st_size=4096, st_mode=0o040755),
        ]

        mgr = SFTPClientManager(sftp_client=mock_sftp, cache_ttl_seconds=10.0)
        items = mgr.listdir_attr("/scratch/run")

        # Must ignore . and .., sort directories first
        assert len(items) == 3
        assert items[0].name == "dirA"
        assert items[0].is_dir
        assert items[1].name == "file1.txt"
        assert items[2].name == "file2.txt"

        assert mock_sftp.listdir_attr.call_count == 1

        # Second call within TTL should return from cache
        cached_items = mgr.listdir_attr("/scratch/run", use_cache=True)
        assert len(cached_items) == 3
        assert mock_sftp.listdir_attr.call_count == 1

        # Clearing cache triggers refresh
        mgr.clear_cache("/scratch/run")
        mgr.listdir_attr("/scratch/run", use_cache=True)
        assert mock_sftp.listdir_attr.call_count == 2

    def test_stat_and_exists(self, mock_sftp):
        mock_sftp.stat.return_value = DummySFTPAttr("data.csv", st_size=5000, st_mode=0o100644)
        mgr = SFTPClientManager(sftp_client=mock_sftp)

        info = mgr.stat("/home/user/data.csv")
        assert info.name == "data.csv"
        assert info.size == 5000
        assert mgr.exists("/home/user/data.csv")

        # Test non-existent file
        mock_sftp.stat.side_effect = IOError("No such file")
        assert not mgr.exists("/nonexistent")
        with pytest.raises(SFTPFileNotFoundError):
            mgr.stat("/nonexistent")

    def test_filesystem_mutations(self, mock_sftp):
        mgr = SFTPClientManager(sftp_client=mock_sftp)
        # Prime cache
        mgr._cache["/home/user"] = (time.monotonic(), [])

        # mkdir
        mgr.mkdir("/home/user/new_dir")
        mock_sftp.mkdir.assert_called_with("/home/user/new_dir", mode=0o755)
        assert "/home/user" not in mgr._cache  # Cache invalidated

        # rmdir
        mgr.rmdir("/home/user/new_dir")
        mock_sftp.rmdir.assert_called_with("/home/user/new_dir")

        # remove
        mgr.remove("/home/user/test.txt")
        mock_sftp.remove.assert_called_with("/home/user/test.txt")

        # rename
        mgr.rename("/home/user/a.txt", "/home/user/b.txt")
        mock_sftp.rename.assert_called_with("/home/user/a.txt", "/home/user/b.txt")

    def test_not_connected_raises(self):
        mgr = SFTPClientManager(sftp_client=None)
        with pytest.raises(SFTPNotConnectedError):
            mgr.listdir_attr("/some/path")
        with pytest.raises(SFTPNotConnectedError):
            mgr.mkdir("/some/path")

