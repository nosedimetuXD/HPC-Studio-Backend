"""Kernel specification discovery and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional


@dataclass
class KernelSpec:
    """Specification of an installed or virtual environment Jupyter kernel."""
    name: str
    display_name: str
    language: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    resource_dir: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _get_search_paths() -> list[Path]:
    """Get standard Jupyter kernelspec discovery directories."""
    paths: list[Path] = []

    # 1. User kernels directory
    paths.append(Path.home() / ".local" / "share" / "jupyter" / "kernels")

    # 2. Virtual environment / sys.prefix directory
    prefix_path = Path(sys.prefix) / "share" / "jupyter" / "kernels"
    if prefix_path not in paths:
        paths.append(prefix_path)

    # 3. Known virtualenv path if distinct
    venv_fallback = Path("/home/nosedimetuxd/.cache/hpc_studio_venv/share/jupyter/kernels")
    if venv_fallback not in paths:
        paths.append(venv_fallback)

    # 4. System paths
    paths.append(Path("/usr/local/share/jupyter/kernels"))
    paths.append(Path("/usr/share/jupyter/kernels"))

    return paths


def _get_default_python_kernel_spec() -> KernelSpec:
    """Create a default Python 3 kernel spec pointing to current or project venv."""
    venv_python = Path("/home/nosedimetuxd/.cache/hpc_studio_venv/bin/python")
    if venv_python.exists():
        py_exec = str(venv_python)
    else:
        py_exec = sys.executable

    return KernelSpec(
        name="python3",
        display_name="Python 3 (HPC Studio)",
        language="python",
        argv=[py_exec, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        env={},
        resource_dir="",
        metadata={"fallback": True},
    )


def find_kernel_specs() -> dict[str, KernelSpec]:
    """Discover all available Jupyter kernel specifications.

    Searches standard directories:
    - ~/.local/share/jupyter/kernels
    - sys.prefix/share/jupyter/kernels
    - /usr/local/share/jupyter/kernels
    - /usr/share/jupyter/kernels

    Returns a mapping of kernel_name -> KernelSpec.
    Always includes at least a default 'python3' kernel spec.
    """
    specs: dict[str, KernelSpec] = {}

    for search_dir in _get_search_paths():
        if not search_dir.is_dir():
            continue

        try:
            for item in sorted(search_dir.iterdir()):
                if not item.is_dir():
                    continue

                spec_file = item / "kernel.json"
                if not spec_file.is_file():
                    continue

                kernel_name = item.name
                if kernel_name in specs:
                    # Already found in higher priority path
                    continue

                try:
                    with open(spec_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    argv = data.get("argv", [])
                    # Normalize python executable if needed:
                    # If argv[0] is just "python", replace with sys.prefix or project python if it matches
                    display_name = data.get("display_name", kernel_name)
                    language = data.get("language", "python")
                    env = data.get("env", {})
                    metadata = data.get("metadata", {})

                    # If argv starts with 'python', resolve to absolute interpreter in sys.prefix if possible
                    if argv and argv[0] == "python":
                        py_bin = Path(sys.prefix) / "bin" / "python"
                        if py_bin.exists():
                            argv = [str(py_bin)] + argv[1:]
                        else:
                            fallback_bin = Path("/home/nosedimetuxd/.cache/hpc_studio_venv/bin/python")
                            if fallback_bin.exists():
                                argv = [str(fallback_bin)] + argv[1:]

                    specs[kernel_name] = KernelSpec(
                        name=kernel_name,
                        display_name=display_name,
                        language=language,
                        argv=argv,
                        env=env,
                        resource_dir=str(item),
                        metadata=metadata,
                    )
                except Exception:
                    continue
        except Exception:
            continue

    if "python3" not in specs:
        specs["python3"] = _get_default_python_kernel_spec()

    return specs


def get_kernel_spec(name: str) -> Optional[KernelSpec]:
    """Retrieve a specific kernel specification by name, or None if not found."""
    specs = find_kernel_specs()
    if name in specs:
        return specs[name]
    if name == "python3":
        return _get_default_python_kernel_spec()
    return None
