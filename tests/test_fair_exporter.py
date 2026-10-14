"""Unit tests for FAIR archive packager and validator."""

import json
import os
from pathlib import Path
import tarfile
import tempfile
import pytest

from hpc_studio.aiida.fair_exporter import FairArchivePackager
from hpc_studio.aiida.models import (
    DAGNode,
    NodeType,
    ProvenanceGraph,
)


def test_calculate_sha256(tmp_path):
    packager = FairArchivePackager()
    sample_file = tmp_path / "test.txt"
    sample_file.write_text("Hello FAIR materials data!", encoding="utf-8")

    checksum = packager.calculate_sha256(str(sample_file))
    assert isinstance(checksum, str)
    assert len(checksum) == 64  # SHA-256 is 64 hex characters


def test_create_archive_and_metadata_structure(tmp_path):
    packager = FairArchivePackager()

    # Create dummy files to bundle
    in_file = tmp_path / "pw.in"
    in_file.write_text("&CONTROL calculation='scf' /", encoding="utf-8")
    out_file = tmp_path / "pw.out"
    out_file.write_text("JOB DONE.", encoding="utf-8")

    archive_dst = tmp_path / "bundle.tar.gz"

    metadata = {
        "title": "Silicon SCF benchmark",
        "authors": ["Researcher One", "Researcher Two"],
        "description": "FAIR dataset for Si diamond structure",
        "chemical_formula": "Si2",
        "license": "CC-BY-4.0",
        "software": "Quantum ESPRESSO 7.0",
    }

    graph = ProvenanceGraph()
    graph.add_node(DAGNode(node_id=1, uuid="u1", node_type=NodeType.STRUCTURE, label="Si"))

    archive_path = packager.create_archive(
        output_tar_gz=str(archive_dst),
        files_to_bundle={
            "inputs/pw.in": str(in_file),
            "outputs/pw.out": str(out_file),
        },
        metadata=metadata,
        graph=graph,
    )

    assert os.path.exists(archive_path)
    assert archive_path == str(archive_dst.resolve())

    # Verify tar content directly
    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
        assert "metadata.json" in names
        assert "inputs/pw.in" in names
        assert "outputs/pw.out" in names

        # Inspect metadata.json
        meta_extracted = tar.extractfile("metadata.json")
        assert meta_extracted is not None
        meta_json = json.loads(meta_extracted.read().decode("utf-8"))

        assert meta_json["title"] == "Silicon SCF benchmark"
        assert meta_json["chemical_formula"] == "Si2"
        assert meta_json["license"] == "CC-BY-4.0"
        assert "files" in meta_json
        assert len(meta_json["files"]) == 2

        # Check sha256 checksums in manifest
        in_manifest = [f for f in meta_json["files"] if f["path"] == "inputs/pw.in"][0]
        assert in_manifest["sha256"] == packager.calculate_sha256(str(in_file))

        # Check provenance graph serialized in metadata
        assert "provenance_graph" in meta_json
        assert len(meta_json["provenance_graph"]["nodes"]) == 1


def test_validate_archive_success(tmp_path):
    packager = FairArchivePackager()

    data_file = tmp_path / "calc.in"
    data_file.write_text("&CONTROL /", encoding="utf-8")
    archive_dst = tmp_path / "valid.tar.gz"

    packager.create_archive(
        output_tar_gz=str(archive_dst),
        files_to_bundle={"calc.in": str(data_file)},
        metadata={"title": "Valid Run"},
    )

    is_valid, errors = packager.validate_archive(str(archive_dst))
    assert is_valid is True
    assert len(errors) == 0


def test_validate_archive_tampered_fails(tmp_path):
    packager = FairArchivePackager()

    data_file = tmp_path / "calc.in"
    data_file.write_text("original content", encoding="utf-8")
    archive_dst = tmp_path / "tampered.tar.gz"

    packager.create_archive(
        output_tar_gz=str(archive_dst),
        files_to_bundle={"calc.in": str(data_file)},
        metadata={"title": "To be tampered"},
    )

    # Tamper with archive: create a new tar where calc.in is modified but metadata.json keeps old sha256
    with tarfile.open(str(archive_dst), "r:gz") as original_tar:
        meta_file = original_tar.extractfile("metadata.json")
        assert meta_file is not None
        meta_bytes = meta_file.read()

    corrupt_tar_dst = tmp_path / "corrupted.tar.gz"
    tampered_file = tmp_path / "tampered_calc.in"
    tampered_file.write_text("tampered content", encoding="utf-8")

    meta_tmp = tmp_path / "saved_meta.json"
    meta_tmp.write_bytes(meta_bytes)

    with tarfile.open(str(corrupt_tar_dst), "w:gz") as tar:
        tar.add(str(meta_tmp), arcname="metadata.json")
        tar.add(str(tampered_file), arcname="calc.in")

    is_valid, errors = packager.validate_archive(str(corrupt_tar_dst))
    assert is_valid is False
    assert any("Checksum mismatch" in err for err in errors)


def test_validate_archive_missing_metadata(tmp_path):
    packager = FairArchivePackager()
    empty_tar = tmp_path / "empty.tar.gz"
    with tarfile.open(str(empty_tar), "w:gz") as tar:
        pass

    is_valid, errors = packager.validate_archive(str(empty_tar))
    assert is_valid is False
    assert any("missing 'metadata.json'" in err for err in errors)
