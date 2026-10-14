"""FAIR-compliant archive packager and validator for HPC Studio calculations."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import posixpath
import tarfile
import tempfile
from typing import Any, Optional

from .models import ProvenanceGraph


class FairArchivePackager:
    """Packaging and validation utility for FAIR-compliant computational archives."""

    @staticmethod
    def calculate_sha256(file_path: str) -> str:
        """Calculate the SHA-256 hexadecimal hash for a given file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def create_archive(
        self,
        output_tar_gz: str,
        files_to_bundle: dict[str, str],
        metadata: dict[str, Any],
        graph: Optional[ProvenanceGraph] = None,
    ) -> str:
        """Create a FAIR-compliant .tar.gz archive.

        Args:
            output_tar_gz: Destination file path for the .tar.gz archive.
            files_to_bundle: Mapping of archive internal relative path to source file path.
                             Example: {"inputs/calc.in": "/path/to/calc.in"}
            metadata: Dublin Core / DataCite compliant metadata dict.
                      Expected keys: title, authors, description, chemical_formula, license, software, etc.
            graph: Optional ProvenanceGraph instance to bundle in the archive.

        Returns:
            The absolute path of the created archive.
        """
        output_path = Path(output_tar_gz).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        manifest: list[dict[str, Any]] = []
        for arc_name, src_path in files_to_bundle.items():
            if not arc_name or not isinstance(arc_name, str):
                raise ValueError("Archive entry name must be a non-empty string.")
            if "\x00" in arc_name:
                raise ValueError("Archive entry path cannot contain null bytes.")
            norm_arc = posixpath.normpath(arc_name.replace("\\", "/"))
            if norm_arc.startswith("/") or norm_arc.startswith("..") or norm_arc == ".":
                raise ValueError(f"Insecure archive entry path (Path Traversal attempt): {arc_name!r}")

            if not os.path.exists(src_path):
                raise FileNotFoundError(f"Source file not found: {src_path}")
            checksum = self.calculate_sha256(src_path)
            file_size = os.path.getsize(src_path)
            manifest.append(
                {
                    "path": norm_arc,
                    "sha256": checksum,
                    "size_bytes": file_size,
                }
            )

        # Assemble metadata conforming to DataCite/Dublin Core standards
        metadata_content: dict[str, Any] = {
            "title": metadata.get("title", "Computational Materials Calculation"),
            "creators": metadata.get("authors", metadata.get("creators", ["HPC Studio User"])),
            "description": metadata.get("description", ""),
            "chemical_formula": metadata.get("chemical_formula", ""),
            "license": metadata.get("license", "CC-BY-4.0"),
            "software": metadata.get("software", "Quantum ESPRESSO"),
            "publisher": metadata.get("publisher", "HPC Studio"),
            "schema_version": "http://datacite.org/schema/kernel-4",
            "files": manifest,
        }

        # Include custom metadata fields if provided
        for key, val in metadata.items():
            if key not in metadata_content and key not in ("authors",):
                metadata_content[key] = val

        # If a provenance graph is supplied, serialize it into metadata
        if graph is not None:
            metadata_content["provenance_graph"] = graph.to_dict()

        with tempfile.TemporaryDirectory() as tmp_dir:
            meta_path = os.path.join(tmp_dir, "metadata.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata_content, f, indent=2, ensure_ascii=False)

            # Write .tar.gz archive
            with tarfile.open(str(output_path), "w:gz") as tar:
                # Add metadata.json at root of archive
                tar.add(meta_path, arcname="metadata.json")

                # Add all user files
                for arc_name, src_path in files_to_bundle.items():
                    tar.add(src_path, arcname=arc_name)

        return str(output_path)

    def validate_archive(self, archive_path: str) -> tuple[bool, list[str]]:
        """Validate an archive's integrity and FAIR compliance against metadata.json.

        Checks:
          1. Archive file exists and is a valid tar.gz.
          2. Archive contains a root `metadata.json`.
          3. `metadata.json` is valid JSON and contains the `files` manifest.
          4. All files in manifest exist inside the archive.
          5. SHA-256 checksum of each extracted file matches manifest hash.

        Returns:
            Tuple of (is_valid, list_of_errors).
        """
        errors: list[str] = []
        archive_file = Path(archive_path)

        if not archive_file.exists():
            return False, [f"Archive does not exist: {archive_path}"]

        if not tarfile.is_tarfile(str(archive_file)):
            return False, [f"File is not a valid tar archive: {archive_path}"]

        try:
            with tarfile.open(str(archive_file), "r:gz") as tar:
                tar_names = tar.getnames()

                # Check for metadata.json
                meta_member = None
                for member in tar.getmembers():
                    if member.name == "metadata.json" or member.name == "./metadata.json":
                        meta_member = member
                        break

                if not meta_member:
                    errors.append("Archive missing 'metadata.json' at root.")
                    return False, errors

                # TarBomb / Memory exhaustion mitigation on metadata.json
                if meta_member.size > 10 * 1024 * 1024:
                    errors.append("Archive 'metadata.json' exceeds safe size limit (10 MB).")
                    return False, errors

                meta_file = tar.extractfile(meta_member)
                if meta_file is None:
                    errors.append("Unable to extract 'metadata.json' from archive.")
                    return False, errors

                try:
                    meta_data = json.loads(meta_file.read().decode("utf-8"))
                except Exception as e:
                    errors.append(f"Invalid JSON in 'metadata.json': {str(e)}")
                    return False, errors

                manifest = meta_data.get("files")
                if manifest is None or not isinstance(manifest, list):
                    errors.append("'metadata.json' missing valid 'files' manifest list.")
                    return False, errors

                # Check for malicious or dangerous members in tar
                for m in tar.getmembers():
                    norm_m = posixpath.normpath(m.name.replace("\\", "/"))
                    if norm_m.startswith("/") or norm_m.startswith(".."):
                        errors.append(f"Archive contains insecure path traversal member: '{m.name}'")
                        return False, errors
                    if m.isdev() or m.isfifo():
                        errors.append(f"Archive contains dangerous special device file: '{m.name}'")
                        return False, errors

                # Validate each file against SHA-256
                for entry in manifest:
                    file_path = entry.get("path")
                    expected_sha = entry.get("sha256")

                    if not file_path:
                        errors.append("Manifest entry missing 'path'.")
                        continue

                    # Normalize paths (remove leading ./ if present)
                    matched_member = None
                    for m in tar.getmembers():
                        norm_m = m.name.lstrip("./")
                        norm_f = file_path.lstrip("./")
                        if norm_m == norm_f:
                            matched_member = m
                            break

                    if not matched_member:
                        errors.append(f"Manifest file '{file_path}' not found in archive.")
                        continue

                    extracted = tar.extractfile(matched_member)
                    if extracted is None:
                        errors.append(f"Could not read archived file '{file_path}'.")
                        continue

                    hasher = hashlib.sha256()
                    while chunk := extracted.read(65536):
                        hasher.update(chunk)
                    computed_sha = hasher.hexdigest()

                    if expected_sha and computed_sha != expected_sha:
                        errors.append(
                            f"Checksum mismatch for '{file_path}': expected {expected_sha}, computed {computed_sha}"
                        )

        except Exception as e:
            errors.append(f"Corrupted or unreadable archive: {str(e)}")

        is_valid = len(errors) == 0
        return is_valid, errors

    def extract_archive(
        self,
        archive_path: str,
        destination_dir: str,
        validate_manifest: bool = True,
        max_total_size: int = 2 * 1024 * 1024 * 1024,  # 2 GB limit (TarBomb mitigation)
        max_files: int = 10000,                         # 10,000 files limit
    ) -> list[str]:
        """Safely extract a FAIR .tar.gz archive with strict path traversal, symlink, and TarBomb mitigations.

        Mitigations enforced:
          - Path Traversal (Zip Slip / Tar Traversal): blocks members containing '../' or absolute paths.
          - Confinement check: ensures all target paths stay within destination directory.
          - Symlink hijacking: blocks symlinks or hardlinks resolving outside destination directory.
          - TarBomb / DoS protection: enforces max_total_size and max_files limits.
          - Special file rejection: blocks device nodes (block, character) and FIFOs.
          - Integrity: optionally verifies SHA-256 checksums against metadata.json manifest.

        Args:
            archive_path: File path of the .tar.gz archive to extract.
            destination_dir: Target directory path to extract files into.
            validate_manifest: Whether to run validate_archive prior to extracting.
            max_total_size: Maximum allowable cumulative uncompressed size in bytes.
            max_files: Maximum allowable number of files in the archive.

        Returns:
            List of extracted file paths.
        """
        archive_file = Path(archive_path).resolve()
        if not archive_file.exists():
            raise FileNotFoundError(f"Archive file not found: {archive_path}")

        if validate_manifest:
            is_valid, errors = self.validate_archive(str(archive_file))
            if not is_valid:
                raise ValueError(f"Archive failed FAIR validation: {'; '.join(errors)}")

        dest_dir = Path(destination_dir).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        extracted_paths: list[str] = []
        cumulative_size = 0
        file_count = 0

        with tarfile.open(str(archive_file), "r:gz") as tar:
            for member in tar.getmembers():
                file_count += 1
                if file_count > max_files:
                    raise ValueError(
                        f"TarBomb mitigation: Archive contains more than {max_files} files."
                    )

                cumulative_size += member.size
                if cumulative_size > max_total_size:
                    raise ValueError(
                        f"TarBomb mitigation: Cumulative uncompressed size exceeds {max_total_size} bytes."
                    )

                if member.isdev() or member.isfifo():
                    raise ValueError(
                        f"Security rejection: Dangerous special device file '{member.name}' in archive."
                    )

                norm_name = posixpath.normpath(member.name.replace("\\", "/"))
                if norm_name.startswith("/") or norm_name.startswith("..") or "\x00" in member.name:
                    raise ValueError(
                        f"Path traversal detected in archive member name: {member.name!r}"
                    )

                target_path = (dest_dir / norm_name).resolve()
                try:
                    target_path.relative_to(dest_dir)
                except ValueError:
                    raise ValueError(
                        f"Path traversal detected: {member.name!r} attempts to escape target directory {dest_dir}"
                    )

                # Check symlink destination
                if member.issym() or member.islnk():
                    link_target = member.linkname.replace("\\", "/")
                    if link_target.startswith("/") or "\x00" in link_target:
                        raise ValueError(f"Insecure absolute symlink target: {member.linkname!r}")
                    resolved_link = (target_path.parent / link_target).resolve()
                    try:
                        resolved_link.relative_to(dest_dir)
                    except ValueError:
                        raise ValueError(
                            f"Symlink traversal detected: {member.name} -> {member.linkname} escapes {dest_dir}"
                        )

                # Safe extraction
                if member.isdir():
                    target_path.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    extracted_file = tar.extractfile(member)
                    if extracted_file is not None:
                        with open(target_path, "wb") as out_f:
                            while chunk := extracted_file.read(65536):
                                out_f.write(chunk)
                        try:
                            os.chmod(target_path, 0o600)
                        except OSError:
                            pass
                        extracted_paths.append(str(target_path))

        return extracted_paths
