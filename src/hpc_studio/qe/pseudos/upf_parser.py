"""Parser for Quantum ESPRESSO Unified Pseudopotential Format (.UPF) headers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Union
import xml.etree.ElementTree as ET


class UPFParser:
    """Parser for UPF (v1 and v2) pseudopotential headers.
    
    Extracts chemical element, pseudo type (USPP, NC, PAW, SL), exchange-correlation
    functional, valence charge, grid/mesh size, and cutoff energies when available.
    """

    @classmethod
    def parse_file(cls, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Parse a UPF file from disk and return its extracted metadata."""
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        return cls.parse_content(content, filename=path.name)

    @classmethod
    def parse_content(cls, content: str, filename: str = "") -> Dict[str, Any]:
        """Parse UPF file contents from string (handling both UPF v1 and UPF v2)."""
        content_stripped = content.strip()
        # UPF v2 is XML based and either contains <UPF or <PP_HEADER ... attr=...
        is_v2 = bool(re.search(r"<UPF\b", content_stripped, re.IGNORECASE) or
                     re.search(r"<PP_HEADER\s+[A-Za-z0-9_]+\s*=", content_stripped, re.IGNORECASE))

        if is_v2:
            metadata = cls._parse_v2(content_stripped)
        else:
            metadata = cls._parse_v1(content_stripped)

        # If element or functional wasn't detected, try inferring from filename
        if (not metadata.get("element") or not metadata.get("functional")) and filename:
            cls._enrich_from_filename(metadata, filename)

        # Normalize pseudo_type
        ptype = metadata.get("pseudo_type", "").upper()
        if "PAW" in ptype:
            metadata["pseudo_type"] = "PAW"
        elif "US" in ptype or "USPP" in ptype or "VDB" in ptype:
            metadata["pseudo_type"] = "USPP"
        elif "NC" in ptype or "NORM" in ptype:
            metadata["pseudo_type"] = "NC"
        elif "SL" in ptype or "SEMILOCAL" in ptype:
            metadata["pseudo_type"] = "SL"
        else:
            metadata["pseudo_type"] = ptype or "NC"

        return metadata

    @classmethod
    def _parse_v2(cls, content: str) -> Dict[str, Any]:
        """Parse UPF v2 XML-like format."""
        meta: Dict[str, Any] = {
            "version": 2,
            "element": "",
            "pseudo_type": "",
            "functional": "",
            "z_valence": None,
            "mesh_size": None,
            "wfc_cutoff": None,
            "rho_cutoff": None,
        }

        # First try to extract <PP_HEADER ...> tag and its attributes or inner text
        header_match = re.search(r"<PP_HEADER\b([^>]*)>(.*?)</PP_HEADER>", content, re.DOTALL | re.IGNORECASE)
        attrs_str = ""
        body_str = ""

        if header_match:
            attrs_str = header_match.group(1)
            body_str = header_match.group(2).strip()
        else:
            # Self-closing or unclosed <PP_HEADER ... />
            single_match = re.search(r"<PP_HEADER\b([^>]*)/?>", content, re.IGNORECASE)
            if single_match:
                attrs_str = single_match.group(1)

        # Parse XML attributes from attrs_str: key="val" or key='val'
        if attrs_str:
            attr_pattern = re.finditer(r'([A-Za-z0-9_]+)\s*=\s*["\']([^"\']*)["\']', attrs_str)
            for m in attr_pattern:
                k = m.group(1).lower()
                v = m.group(2).strip()
                if k == "element":
                    meta["element"] = v.capitalize()
                elif k == "pseudo_type":
                    meta["pseudo_type"] = v.upper()
                elif k == "functional":
                    meta["functional"] = v.upper()
                elif k in ("z_valence", "z_val"):
                    try:
                        meta["z_valence"] = float(v)
                    except ValueError:
                        pass
                elif k in ("mesh_size", "mesh"):
                    try:
                        meta["mesh_size"] = int(float(v))
                    except ValueError:
                        pass
                elif k in ("wfc_cutoff", "ecutwfc", "suggested_ecutwfc"):
                    try:
                        meta["wfc_cutoff"] = float(v)
                    except ValueError:
                        pass
                elif k in ("rho_cutoff", "ecutrho", "suggested_ecutrho"):
                    try:
                        meta["rho_cutoff"] = float(v)
                    except ValueError:
                        pass

        # If fields are missing in attributes, check body of PP_HEADER (UPF v2 sometimes writes line-by-line inside tag)
        if body_str:
            lines = [l.strip() for l in body_str.splitlines() if l.strip()]
            for line in lines:
                # E.g. "Element: Si" or "z_valence = 4.0" or standard positional v1 lines inside v2
                m_kv = re.match(r"^([A-Za-z0-9_\s]+)[:=]\s*([^\s!#]+)", line)
                if m_kv:
                    k_name = m_kv.group(1).strip().lower().replace(" ", "_")
                    val_str = m_kv.group(2).strip()
                    if "element" in k_name and not meta["element"]:
                        meta["element"] = val_str.capitalize()
                    elif "type" in k_name and not meta["pseudo_type"]:
                        meta["pseudo_type"] = val_str.upper()
                    elif "functional" in k_name and not meta["functional"]:
                        meta["functional"] = val_str.upper()
                    elif "valence" in k_name and meta["z_valence"] is None:
                        try:
                            meta["z_valence"] = float(val_str)
                        except ValueError:
                            pass
                    elif "mesh" in k_name and meta["mesh_size"] is None:
                        try:
                            meta["mesh_size"] = int(float(val_str))
                        except ValueError:
                            pass
                    elif "wfc" in k_name and meta["wfc_cutoff"] is None:
                        try:
                            meta["wfc_cutoff"] = float(val_str)
                        except ValueError:
                            pass
                    elif "rho" in k_name and meta["rho_cutoff"] is None:
                        try:
                            meta["rho_cutoff"] = float(val_str)
                        except ValueError:
                            pass

        # Look for suggested cutoffs or mesh in separate tags if still None
        if meta["wfc_cutoff"] is None:
            wfc_tag = re.search(r"<PP_WFC_CUTOFF\b[^>]*>\s*([0-9\.\+\-eE]+)\s*</PP_WFC_CUTOFF>", content, re.IGNORECASE)
            if wfc_tag:
                try:
                    meta["wfc_cutoff"] = float(wfc_tag.group(1))
                except ValueError:
                    pass

        if meta["rho_cutoff"] is None:
            rho_tag = re.search(r"<PP_RHO_CUTOFF\b[^>]*>\s*([0-9\.\+\-eE]+)\s*</PP_RHO_CUTOFF>", content, re.IGNORECASE)
            if rho_tag:
                try:
                    meta["rho_cutoff"] = float(rho_tag.group(1))
                except ValueError:
                    pass

        if meta["mesh_size"] is None:
            mesh_tag = re.search(r"<PP_MESH\b[^>]*size=[\"'](\d+)[\"']", content, re.IGNORECASE)
            if mesh_tag:
                try:
                    meta["mesh_size"] = int(mesh_tag.group(1))
                except ValueError:
                    pass

        return meta

    @classmethod
    def _parse_v1(cls, content: str) -> Dict[str, Any]:
        """Parse UPF v1 format."""
        meta: Dict[str, Any] = {
            "version": 1,
            "element": "",
            "pseudo_type": "",
            "functional": "",
            "z_valence": None,
            "mesh_size": None,
            "wfc_cutoff": None,
            "rho_cutoff": None,
        }

        # Locate <PP_HEADER> block
        header_match = re.search(r"<PP_HEADER>(.*?)</PP_HEADER>", content, re.DOTALL | re.IGNORECASE)
        if not header_match:
            # Maybe the whole top of the file before <PP_MESH> is header
            header_text = content[:2000]
        else:
            header_text = header_match.group(1)

        raw_lines = [l.strip() for l in header_text.splitlines() if l.strip()]

        for line in raw_lines:
            lower = line.lower()
            # Check for comments or labels like "Element: C" or "Z valence"
            if "element" in lower:
                tokens = line.split()
                if len(tokens) >= 1:
                    val = tokens[0] if tokens[0].lower() != "element" else (tokens[1] if len(tokens) > 1 else "")
                    val = re.sub(r"[:=]", "", val).strip()
                    if val and not meta["element"]:
                        meta["element"] = val.capitalize()
            if "valence" in lower or "zval" in lower or "z_val" in lower:
                m_num = re.search(r"([0-9]+\.?[0-9]*)", line)
                if m_num and meta["z_valence"] is None:
                    try:
                        meta["z_valence"] = float(m_num.group(1))
                    except ValueError:
                        pass
            if "functional" in lower or "dft" in lower:
                # Check for standard functional names anywhere in the line
                m_fn = re.search(r"\b(PBE|PBESOL|PZ|LDA|BLYP|PW91|SCAN)\b", line, re.IGNORECASE)
                if m_fn and not meta["functional"]:
                    meta["functional"] = m_fn.group(1).upper()
                else:
                    tokens = line.split()
                    if len(tokens) >= 1:
                        val = tokens[0] if tokens[0].lower() not in ("functional", "dft") else (tokens[1] if len(tokens) > 1 else "")
                        val = re.sub(r"[:=]", "", val).strip()
                        if val and not meta["functional"]:
                            meta["functional"] = val.upper()
            if any(pt in lower for pt in ["uspp", "ultrasoft", "paw", "norm-conserving", " nc"]):
                if "PAW" in line.upper() and not meta["pseudo_type"]:
                    meta["pseudo_type"] = "PAW"
                elif ("US" in line.upper() or "ULTRASOFT" in line.upper()) and not meta["pseudo_type"]:
                    meta["pseudo_type"] = "USPP"
                elif ("NC" in line.upper() or "NORM" in line.upper()) and not meta["pseudo_type"]:
                    meta["pseudo_type"] = "NC"
            if "mesh" in lower:
                m_mesh = re.search(r"(\d+)", line)
                if m_mesh and meta["mesh_size"] is None:
                    try:
                        meta["mesh_size"] = int(m_mesh.group(1))
                    except ValueError:
                        pass
            if "cutoff" in lower:
                # E.g. "0.000000 0.000000 Suggested cutoff for wfc and rho: 30.0 240.0"
                # Look for numbers after ':' or after 'cutoff'
                parts = re.split(r"[:=]", line, maxsplit=1)
                search_text = parts[1] if len(parts) > 1 else line
                nums = re.findall(r"([0-9]+\.?[0-9]*)", search_text)
                if len(nums) >= 2:
                    try:
                        if meta["wfc_cutoff"] is None:
                            meta["wfc_cutoff"] = float(nums[0])
                        if meta["rho_cutoff"] is None:
                            meta["rho_cutoff"] = float(nums[1])
                    except ValueError:
                        pass
                elif len(nums) == 1:
                    try:
                        if "wfc" in lower and meta["wfc_cutoff"] is None:
                            meta["wfc_cutoff"] = float(nums[0])
                        elif "rho" in lower and meta["rho_cutoff"] is None:
                            meta["rho_cutoff"] = float(nums[0])
                    except ValueError:
                        pass

        # Standard UPF v1 positional line format if keywords weren't present:
        # Line 0: version number (e.g. 0 or 1)
        # Line 1: element symbol (e.g. Si)
        # Line 2: pseudo type (e.g. US, NC, PAW)
        # Line 3: non-linear core correction (T/F)
        # Line 4: exchange-correlation functional (e.g. SLA  PW   PBX PBC)
        # Line 5: Z valence
        if len(raw_lines) >= 6:
            # Check if line 1 looks like chemical symbol
            cand_sym = raw_lines[1].split()[0]
            if re.match(r"^[A-Z][a-z]?$", cand_sym) and not meta["element"]:
                meta["element"] = cand_sym.capitalize()
            cand_type = raw_lines[2].split()[0].upper()
            if not meta["pseudo_type"]:
                meta["pseudo_type"] = cand_type
            if not meta["functional"]:
                meta["functional"] = raw_lines[4].strip().upper()
            if meta["z_valence"] is None:
                try:
                    meta["z_valence"] = float(raw_lines[5].split()[0])
                except (ValueError, IndexError):
                    pass

        return meta

    @classmethod
    def _enrich_from_filename(cls, meta: Dict[str, Any], filename: str) -> None:
        """Infer element, functional, or pseudo type from filename convention."""
        # Typical QE pseudo naming:
        # Si.pbe-n-kjpaw_psl.1.0.0.UPF
        # C.pbe-rrkjus.UPF
        # O_pbe_v1.2.uspp.F.UPF
        parts = re.split(r"[\._\-]", filename)
        if not meta.get("element") and parts:
            first = parts[0].capitalize()
            if re.match(r"^[A-Z][a-z]?$", first):
                meta["element"] = first

        fn_upper = filename.upper()
        if not meta.get("functional"):
            if "PBE" in fn_upper:
                meta["functional"] = "PBE"
            elif "PBESOL" in fn_upper:
                meta["functional"] = "PBESOL"
            elif "LDA" in fn_upper or "PZ" in fn_upper:
                meta["functional"] = "PZ"
            elif "BLYP" in fn_upper:
                meta["functional"] = "BLYP"

        if not meta.get("pseudo_type"):
            if "PAW" in fn_upper:
                meta["pseudo_type"] = "PAW"
            elif "USPP" in fn_upper or "RRKJUS" in fn_upper or "US" in fn_upper:
                meta["pseudo_type"] = "USPP"
            elif "NC" in fn_upper or "ONCVPSP" in fn_upper:
                meta["pseudo_type"] = "NC"
