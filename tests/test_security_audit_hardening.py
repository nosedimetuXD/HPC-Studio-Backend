"""Security audit hardening regression tests.

Verifies fixes and mitigations for:
1. SlurmClient shell/command injection validation (CWE-78).
2. SlurmScriptGenerator double-quote escaping and metacharacter validation (CWE-78).
3. FairArchivePackager path traversal, Zip Slip, and TarBomb mitigations (CWE-22, CWE-409).
4. Jupyter wire protocol HMAC signature verification bypass mitigation (CWE-347).
5. Rich notebook output HTML sanitization and unsafe URL filtering (CWE-79).
"""

import io
import json
import os
from pathlib import Path
import tarfile
import pytest

from hpc_studio.aiida.fair_exporter import FairArchivePackager
from hpc_studio.notebook.local_kernel import deserialize_wire_msg, serialize_wire_msg
from hpc_studio.slurm.client import SlurmClient
from hpc_studio.slurm.generator import SlurmBatchConfig, SlurmScriptGenerator
from hpc_studio.notebook.models import _sanitize_html



class TestSlurmClientSecurity:
    """Validate that SlurmClient rejects injection attempts."""

    def test_cancel_job_rejects_injection(self):
        client = SlurmClient(ssh_manager=None)
        with pytest.raises(ValueError, match="Invalid Slurm job ID"):
            client.cancel_job("1001; rm -rf /")

        with pytest.raises(ValueError, match="Invalid Slurm job ID"):
            client.cancel_job("1001 && whoami")

        with pytest.raises(ValueError, match="Invalid Slurm job ID"):
            client.cancel_job("1001`id`")

    def test_cancel_job_rejects_malicious_signal(self):
        client = SlurmClient(ssh_manager=None)
        with pytest.raises(ValueError, match="Invalid signal name"):
            client.cancel_job("1001", signal="KILL; cat /etc/shadow")

    def test_hold_and_release_rejects_injection(self):
        client = SlurmClient(ssh_manager=None)
        with pytest.raises(ValueError, match="Invalid Slurm job ID"):
            client.hold_job("1001 | cat")

        with pytest.raises(ValueError, match="Invalid Slurm job ID"):
            client.release_job("1001$(id)")

    def test_get_job_details_rejects_injection(self):
        client = SlurmClient(ssh_manager=None)
        with pytest.raises(ValueError, match="Invalid Slurm job ID"):
            client.get_job_details("1001; reboot")

    def test_get_jobs_rejects_injection(self, monkeypatch):
        mock_ssh = pytest.importorskip("unittest.mock").MagicMock()
        mock_ssh.is_connected = True
        client = SlurmClient(ssh_manager=mock_ssh)

        with pytest.raises(ValueError, match="Invalid username"):
            client.get_jobs(user="victim; id")

        with pytest.raises(ValueError, match="Invalid partition"):
            client.get_jobs(partition="standard & echo hacked")

        with pytest.raises(ValueError, match="Invalid job state"):
            client.get_jobs(states=["RUNNING; evil"])


class TestSlurmGeneratorSecurity:
    """Validate that SlurmScriptGenerator sanitizes/escapes values."""

    def test_work_dir_escaping(self):
        config = SlurmBatchConfig(
            work_dir='/scratch/user"; evil_cmd; #'
        )
        script = SlurmScriptGenerator.generate(config)
        # Double quotes must be escaped as \"
        assert r'cd "/scratch/user\"; evil_cmd; #"' in script

    def test_env_var_name_validation(self):
        config = SlurmBatchConfig(
            env_vars={"MALICIOUS=VAR": "value"}
        )
        with pytest.raises(ValueError, match="Invalid environment variable name"):
            SlurmScriptGenerator.generate(config)

    def test_output_file_injection_rejection(self):
        config = SlurmBatchConfig(
            output_file="out.log; rm -rf /"
        )
        with pytest.raises(ValueError, match="Dangerous shell characters"):
            SlurmScriptGenerator.generate(config)

    def test_executable_injection_rejection(self):
        config = SlurmBatchConfig(
            executable="pw.x && cat /etc/passwd"
        )
        with pytest.raises(ValueError, match="Dangerous shell characters"):
            SlurmScriptGenerator.generate(config)


class TestFairArchivePackagerSecurity:
    """Validate FairArchivePackager path traversal, Zip Slip, and TarBomb mitigations."""

    def test_create_archive_rejects_path_traversal(self, tmp_path):
        packager = FairArchivePackager()
        sample = tmp_path / "data.txt"
        sample.write_text("dummy", encoding="utf-8")
        out_archive = tmp_path / "out.tar.gz"

        with pytest.raises(ValueError, match="Path Traversal attempt"):
            packager.create_archive(
                output_tar_gz=str(out_archive),
                files_to_bundle={"../../etc/shadow": str(sample)},
                metadata={},
            )

        with pytest.raises(ValueError, match="Path Traversal attempt"):
            packager.create_archive(
                output_tar_gz=str(out_archive),
                files_to_bundle={"/absolute/path": str(sample)},
                metadata={},
            )

    def test_safe_extract_archive(self, tmp_path):
        packager = FairArchivePackager()
        sample = tmp_path / "calc.in"
        sample.write_text("&CONTROL /", encoding="utf-8")
        archive = tmp_path / "bundle.tar.gz"

        packager.create_archive(
            output_tar_gz=str(archive),
            files_to_bundle={"inputs/calc.in": str(sample)},
            metadata={"title": "Test Extraction"},
        )

        extract_dst = tmp_path / "extracted"
        extracted_files = packager.extract_archive(str(archive), str(extract_dst))

        assert len(extracted_files) >= 2  # metadata.json and inputs/calc.in
        extracted_calc = extract_dst / "inputs" / "calc.in"
        assert extracted_calc.exists()
        assert extracted_calc.read_text(encoding="utf-8") == "&CONTROL /"

    def test_extract_archive_rejects_zip_slip(self, tmp_path):
        packager = FairArchivePackager()
        malicious_tar = tmp_path / "malicious.tar.gz"

        # Construct a malicious tar containing ../escape.txt
        with tarfile.open(str(malicious_tar), "w:gz") as tar:
            data = b"malicious payload"
            ti = tarfile.TarInfo(name="../escape.txt")
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))

        extract_dst = tmp_path / "safe_jail"
        with pytest.raises(ValueError, match="Path traversal"):
            packager.extract_archive(str(malicious_tar), str(extract_dst), validate_manifest=False)

    def test_extract_archive_tarbomb_limit(self, tmp_path):
        packager = FairArchivePackager()
        bomb_tar = tmp_path / "bomb.tar.gz"

        # Create tar with 100 bytes
        with tarfile.open(str(bomb_tar), "w:gz") as tar:
            data = b"X" * 100
            ti = tarfile.TarInfo(name="big.txt")
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))

        extract_dst = tmp_path / "bomb_out"
        # Set max_total_size to 50 bytes
        with pytest.raises(ValueError, match="TarBomb mitigation"):
            packager.extract_archive(
                str(bomb_tar),
                str(extract_dst),
                validate_manifest=False,
                max_total_size=50,
            )


class TestJupyterHMACSecurity:
    """Validate Jupyter wire protocol HMAC signature checking."""

    def test_deserialize_rejects_missing_signature_when_key_set(self):
        # Serialize valid frames
        frames = serialize_wire_msg(
            msg_type="execute_request",
            content={"code": "1+1"},
            key="super-secret-key",
            session_id="session-1",
        )

        # Forge message with empty signature
        idx = frames.index(b"<IDS|MSG>")
        forged_frames = list(frames)
        forged_frames[idx + 1] = b""  # Empty signature

        with pytest.raises(ValueError, match="signature verification failed|signature is missing"):
            deserialize_wire_msg(forged_frames, key="super-secret-key")

    def test_deserialize_accepts_valid_signature(self):
        frames = serialize_wire_msg(
            msg_type="execute_request",
            content={"code": "1+1"},
            key="super-secret-key",
            session_id="session-1",
        )
        _, header, _, _, content = deserialize_wire_msg(frames, key="super-secret-key")
        assert header["msg_type"] == "execute_request"
        assert content["code"] == "1+1"


class TestHtmlSanitizationSecurity:
    """Validate HTML sanitization against XSS in cell output rendering."""

    def test_script_tag_stripped(self):
        dirty = "<b>Hello</b><script>alert(1)</script>"
        clean = _sanitize_html(dirty)
        assert "<script>" not in clean
        assert "alert(1)" not in clean

    def test_unclosed_script_tag_stripped(self):
        dirty = "<script src='http://evil.com/hook.js'>"
        clean = _sanitize_html(dirty)
        assert "<script" not in clean

    def test_event_handler_stripped(self):
        dirty = "<svg/onload=alert(1)>"
        clean = _sanitize_html(dirty)
        assert "onload" not in clean

    def test_javascript_and_file_urls_stripped(self):
        dirty = '<a href="javascript:alert(1)">Click</a> <a href="file:///etc/passwd">Passwd</a>'
        clean = _sanitize_html(dirty)
        assert "javascript:" not in clean
        assert "file:" not in clean
