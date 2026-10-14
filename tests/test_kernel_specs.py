"""Unit tests for Jupyter kernel specification discovery."""

import json
from pathlib import Path
import sys
import tempfile

from hpc_studio.notebook.kernel_spec import (
    KernelSpec,
    find_kernel_specs,
    get_kernel_spec,
    _get_search_paths,
    _get_default_python_kernel_spec,
)


def test_kernel_spec_dataclass():
    spec = KernelSpec(
        name="test_kernel",
        display_name="Test Kernel Display",
        language="python",
        argv=["python", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        env={"TEST_VAR": "1"},
        resource_dir="/tmp/test",
    )
    assert spec.name == "test_kernel"
    assert spec.display_name == "Test Kernel Display"
    assert spec.language == "python"
    assert spec.argv[0] == "python"
    assert spec.env["TEST_VAR"] == "1"
    assert spec.resource_dir == "/tmp/test"


def test_default_python_kernel_spec():
    default_spec = _get_default_python_kernel_spec()
    assert default_spec.name == "python3"
    assert default_spec.language == "python"
    assert len(default_spec.argv) >= 5
    assert "{connection_file}" in default_spec.argv[-1]


def test_find_kernel_specs_includes_python3():
    specs = find_kernel_specs()
    assert isinstance(specs, dict)
    assert "python3" in specs
    py3 = specs["python3"]
    assert py3.language == "python"
    assert any("{connection_file}" in arg for arg in py3.argv)


def test_get_kernel_spec_existing_and_missing():
    py3 = get_kernel_spec("python3")
    assert py3 is not None
    assert py3.name == "python3"

    missing = get_kernel_spec("non_existent_kernel_xyz_123")
    assert missing is None


def test_custom_kernel_spec_discovery(monkeypatch, tmp_path):
    # Create mock kernels directory
    mock_kernels_dir = tmp_path / "kernels"
    mock_kernels_dir.mkdir()

    bash_kernel = mock_kernels_dir / "bash"
    bash_kernel.mkdir()
    bash_spec = {
        "argv": ["bash", "-m", "bash_kernel", "-f", "{connection_file}"],
        "display_name": "Bash Kernel",
        "language": "bash",
    }
    with open(bash_kernel / "kernel.json", "w", encoding="utf-8") as f:
        json.dump(bash_spec, f)

    # Patch _get_search_paths
    monkeypatch.setattr(
        "hpc_studio.notebook.kernel_spec._get_search_paths",
        lambda: [mock_kernels_dir],
    )

    specs = find_kernel_specs()
    assert "bash" in specs
    assert specs["bash"].display_name == "Bash Kernel"
    assert specs["bash"].language == "bash"
    # Ensure fallback python3 is still provided
    assert "python3" in specs
