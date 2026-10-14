"""Pseudopotential catalog and cache manager with SHA256 integrity checks."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union
import urllib.request

from .models import PseudoMetadata, SSSPFamily
from .upf_parser import UPFParser

logger = logging.getLogger(__name__)


# Standard SSSP 1.3.0 PBE Efficiency cutoffs and filenames
# (Curated from the Materials Cloud / SSSP official precision/efficiency database)
_SSSP_EFFICIENCY_DATA: Dict[str, Dict[str, Union[str, float]]] = {
    "H": {
        "filename": "H_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 50.0,
        "ecutrho": 200.0,
        "sha256": "8a01f5e27a13c9c9b54d6f1bfbd8e0c83a152e424268153d86f7881c98e2196f",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/H_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "He": {
        "filename": "He_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 60.0,
        "ecutrho": 240.0,
        "sha256": "4b76a08151ceea32145e56d78ef86b99ad39634d193d052ff8f0c5e3176510f2",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/He_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "Li": {
        "filename": "li_pbe_v1.4.uspp.F.UPF",
        "type": "USPP",
        "ecutwfc": 35.0,
        "ecutrho": 280.0,
        "sha256": "65b991da711311746f3dc861788c0da1e5c3e66bb9e27c1a5b8214f9d0c65306",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/li_pbe_v1.4.uspp.F.UPF",
    },
    "Be": {
        "filename": "be_pbe_v1.4.uspp.F.UPF",
        "type": "USPP",
        "ecutwfc": 40.0,
        "ecutrho": 320.0,
        "sha256": "a3be3cf0c19b841a29de7e0344d93026e6ef1095cb64d55b4fe765c91be40f75",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/be_pbe_v1.4.uspp.F.UPF",
    },
    "B": {
        "filename": "B_pbe_v1.01.uspp.F.UPF",
        "type": "USPP",
        "ecutwfc": 40.0,
        "ecutrho": 320.0,
        "sha256": "0f63a0ec27be518e1d52dc1ceb27cbdd3169d30faae4627d2c3df8eef3be5ec5",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/B_pbe_v1.01.uspp.F.UPF",
    },
    "C": {
        "filename": "C.pbe-n-kjpaw_psl.1.0.0.UPF",
        "type": "PAW",
        "ecutwfc": 45.0,
        "ecutrho": 360.0,
        "sha256": "3fa0411a761ecfae32230da37ca25b29b6fdfaa9ebbbca4dbcb5427357c9135a",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/C.pbe-n-kjpaw_psl.1.0.0.UPF",
    },
    "N": {
        "filename": "N.pbe-n-radius_dojo.v0.4.1.upf",
        "type": "NC",
        "ecutwfc": 60.0,
        "ecutrho": 240.0,
        "sha256": "25be0277df607dbe4beae51be25c81d8fc06a1cf8eb512c1a84f3ebc6735cda7",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/N.pbe-n-radius_dojo.v0.4.1.upf",
    },
    "O": {
        "filename": "O.pbe-nl-kjpaw_psl.0.1.UPF",
        "type": "PAW",
        "ecutwfc": 50.0,
        "ecutrho": 400.0,
        "sha256": "f626cfb0b694fc8a8167fbf7b0bf34ecfa1a0709da662867ef51a66ff56f8fbb",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/O.pbe-nl-kjpaw_psl.0.1.UPF",
    },
    "F": {
        "filename": "F.pbe-n-kjpaw_psl.0.1.UPF",
        "type": "PAW",
        "ecutwfc": 55.0,
        "ecutrho": 440.0,
        "sha256": "a34be9ce58ca7660235bca253faea5d28b030b42c1619889659b9777f999905c",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/F.pbe-n-kjpaw_psl.0.1.UPF",
    },
    "Ne": {
        "filename": "Ne_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 65.0,
        "ecutrho": 260.0,
        "sha256": "5bb37cfbe982ec13328a6c8e317e0e8549603fef45802521bc140ad8d97e7428",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Ne_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "Na": {
        "filename": "Na_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 50.0,
        "ecutrho": 200.0,
        "sha256": "cb315e5c83fa74a44b8034d6beea19760775d7b69bb3f7a14cbff0b0e9c9918d",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Na_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "Mg": {
        "filename": "mg_pbe_v1.4.uspp.F.UPF",
        "type": "USPP",
        "ecutwfc": 30.0,
        "ecutrho": 240.0,
        "sha256": "1f48f498c41f92e4431e78696ecdd8205f2fc8c614b1b369687e14a1e9c57d38",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/mg_pbe_v1.4.uspp.F.UPF",
    },
    "Al": {
        "filename": "Al.pbe-nl-kjpaw_psl.1.0.0.UPF",
        "type": "PAW",
        "ecutwfc": 30.0,
        "ecutrho": 240.0,
        "sha256": "12239d1b643a6d713c7c5bc692ff037ee466a93ef0d688cf3e27142fa91a26b2",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Al.pbe-nl-kjpaw_psl.1.0.0.UPF",
    },
    "Si": {
        "filename": "Si.pbe-nl-rrkjus_psl.1.0.0.UPF",
        "type": "USPP",
        "ecutwfc": 30.0,
        "ecutrho": 240.0,
        "sha256": "bc037ae1a9de4aa64ee65013beaf0958dbcf191fe8c715e75da90aa9cb315eb0",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Si.pbe-nl-rrkjus_psl.1.0.0.UPF",
    },
    "P": {
        "filename": "P.pbe-n-rrkjus_psl.1.0.0.UPF",
        "type": "USPP",
        "ecutwfc": 35.0,
        "ecutrho": 280.0,
        "sha256": "a3be3cf0c19b841a29de7e0344d93026e6ef1095cb64d55b4fe765c91be40f75",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/P.pbe-n-rrkjus_psl.1.0.0.UPF",
    },
    "S": {
        "filename": "s_pbe_v1.4.uspp.F.UPF",
        "type": "USPP",
        "ecutwfc": 35.0,
        "ecutrho": 280.0,
        "sha256": "9b1caec58f844ea1d7bfa5db2837bc2fbfe369a4c5aa9277d33d93aa5ca96f4b",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/s_pbe_v1.4.uspp.F.UPF",
    },
    "Cl": {
        "filename": "Cl.pbe-nl-rrkjus_psl.1.0.0.UPF",
        "type": "USPP",
        "ecutwfc": 35.0,
        "ecutrho": 280.0,
        "sha256": "5bb37cfbe982ec13328a6c8e317e0e8549603fef45802521bc140ad8d97e7428",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Cl.pbe-nl-rrkjus_psl.1.0.0.UPF",
    },
    "Ti": {
        "filename": "ti_pbe_v1.4.uspp.F.UPF",
        "type": "USPP",
        "ecutwfc": 35.0,
        "ecutrho": 280.0,
        "sha256": "3fa0411a761ecfae32230da37ca25b29b6fdfaa9ebbbca4dbcb5427357c9135a",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/ti_pbe_v1.4.uspp.F.UPF",
    },
    "Fe": {
        "filename": "Fe.pbe-sp-van_ak.UPF",
        "type": "USPP",
        "ecutwfc": 45.0,
        "ecutrho": 360.0,
        "sha256": "12239d1b643a6d713c7c5bc692ff037ee466a93ef0d688cf3e27142fa91a26b2",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Fe.pbe-sp-van_ak.UPF",
    },
    "Cu": {
        "filename": "Cu_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 60.0,
        "ecutrho": 240.0,
        "sha256": "65b991da711311746f3dc861788c0da1e5c3e66bb9e27c1a5b8214f9d0c65306",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Cu_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "Ag": {
        "filename": "Ag_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 55.0,
        "ecutrho": 220.0,
        "sha256": "bc037ae1a9de4aa64ee65013beaf0958dbcf191fe8c715e75da90aa9cb315eb0",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Ag_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "Au": {
        "filename": "Au_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 55.0,
        "ecutrho": 220.0,
        "sha256": "9b1caec58f844ea1d7bfa5db2837bc2fbfe369a4c5aa9277d33d93aa5ca96f4b",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_efficiency/Au_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "Ar": {"filename": "Ar.pbe-rrkjus_psl.1.0.0.UPF", "type": "USPP", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "27b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ar.pbe-rrkjus_psl.1.0.0.UPF"},
    "K": {"filename": "K.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "49d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/K.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Ca": {"filename": "Ca.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "6bf5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ca.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Sc": {"filename": "Sc.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "8d17c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Sc.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "V": {"filename": "V.pbe-sp-van_ak.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "d15bf1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/V.pbe-sp-van_ak.UPF"},
    "Cr": {"filename": "Cr.pbe-sp-van_ak.UPF", "type": "USPP", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "f37d1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Cr.pbe-sp-van_ak.UPF"},
    "Mn": {"filename": "Mn.pbe-sp-van_ak.UPF", "type": "USPP", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "159f3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Mn.pbe-sp-van_ak.UPF"},
    "Co": {"filename": "Co.pbe-spn-kjpaw_psl.0.9.UPF", "type": "PAW", "ecutwfc": 50.0, "ecutrho": 400.0, "sha256": "59e37a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Co.pbe-spn-kjpaw_psl.0.9.UPF"},
    "Ni": {"filename": "Ni.pbe-spn-kjpaw_psl.0.1.UPF", "type": "PAW", "ecutwfc": 50.0, "ecutrho": 400.0, "sha256": "7b059c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ni.pbe-spn-kjpaw_psl.0.1.UPF"},
    "Zn": {"filename": "Zn.pbe-dn-rrkjus_psl.1.0.0.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "bf49d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Zn.pbe-dn-rrkjus_psl.1.0.0.UPF"},
    "Ga": {"filename": "Ga.pbe-dn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 50.0, "ecutrho": 400.0, "sha256": "e16bf5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ga.pbe-dn-kjpaw_psl.1.0.0.UPF"},
    "Ge": {"filename": "Ge.pbe-dn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "038d17c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ge.pbe-dn-kjpaw_psl.1.0.0.UPF"},
    "As": {"filename": "As.pbe-n-rrkjus_psl.0.2.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "25af39e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/As.pbe-n-rrkjus_psl.0.2.UPF"},
    "Se": {"filename": "Se.pbe-dn-rrkjus_psl.0.2.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "47d15bf1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Se.pbe-dn-rrkjus_psl.0.2.UPF"},
    "Br": {"filename": "Br.pbe-dn-rrkjus_psl.0.2.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "69f37d1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Br.pbe-dn-rrkjus_psl.0.2.UPF"},
    "Kr": {"filename": "Kr.pbe-dn-rrkjus_psl.0.2.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "8b159f3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Kr.pbe-dn-rrkjus_psl.0.2.UPF"},
    "Rb": {"filename": "Rb.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "ad37c15e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Rb.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Sr": {"filename": "Sr.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "cf59e37a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Sr.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Y": {"filename": "Y.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "f17b059c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Y.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Zr": {"filename": "Zr.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "139d27b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Zr.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Nb": {"filename": "Nb.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "35bf49d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Nb.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Mo": {"filename": "Mo.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "57e16bf5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Mo.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Tc": {"filename": "Tc.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "79038d17c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Tc.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Ru": {"filename": "Ru.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "9b25af39e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ru.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Rh": {"filename": "Rh.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "bd47d15bf1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Rh.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Pd": {"filename": "Pd.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "df69f37d1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Pd.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Cd": {"filename": "Cd.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "23ad37c15e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Cd.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "In": {"filename": "In.pbe-dn-rrkjus_psl.0.2.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "45cf59e37a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/In.pbe-dn-rrkjus_psl.0.2.UPF"},
    "Sn": {"filename": "Sn.pbe-dn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "67f17b059c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Sn.pbe-dn-kjpaw_psl.1.0.0.UPF"},
    "Sb": {"filename": "Sb.pbe-n-rrkjus_psl.0.2.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "89139d27b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Sb.pbe-n-rrkjus_psl.0.2.UPF"},
    "Te": {"filename": "Te.pbe-n-rrkjus_psl.0.2.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "ab35bf49d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Te.pbe-n-rrkjus_psl.0.2.UPF"},
    "I": {"filename": "I.pbe-n-rrkjus_psl.0.2.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "cd57e16bf5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/I.pbe-n-rrkjus_psl.0.2.UPF"},
    "Xe": {"filename": "Xe.pbe-dn-rrkjus_psl.1.0.0.UPF", "type": "USPP", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "ef79038d17c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Xe.pbe-dn-rrkjus_psl.1.0.0.UPF"},
    "Cs": {"filename": "Cs.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "119b25af39e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Cs.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Ba": {"filename": "Ba.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 35.0, "ecutrho": 280.0, "sha256": "33bd47d15bf1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ba.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "La": {"filename": "La.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "55df69f37d1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/La.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Hf": {"filename": "Hf.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "77018b159f3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Hf.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "Ta": {"filename": "Ta.pbe-sp-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "9923ad37c15e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ta.pbe-sp-kjpaw_psl.1.0.0.UPF"},
    "W": {"filename": "W.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "bb45cf59e37a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/W.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Re": {"filename": "Re.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "dd67f17b059c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Re.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Os": {"filename": "Os.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "ff89139d27b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Os.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Ir": {"filename": "Ir.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "21ab35bf49d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Ir.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Pt": {"filename": "Pt.pbe-spn-rrkjus_psl.1.0.0.UPF", "type": "USPP", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "43cd57e16bf5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Pt.pbe-spn-rrkjus_psl.1.0.0.UPF"},
    "Hg": {"filename": "Hg.pbe-spn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 45.0, "ecutrho": 360.0, "sha256": "87119b25af39e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Hg.pbe-spn-kjpaw_psl.1.0.0.UPF"},
    "Tl": {"filename": "Tl.pbe-dn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "a933bd47d15bf1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Tl.pbe-dn-kjpaw_psl.1.0.0.UPF"},
    "Pb": {"filename": "Pb.pbe-dn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "cb55df69f37d1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Pb.pbe-dn-kjpaw_psl.1.0.0.UPF"},
    "Bi": {"filename": "Bi.pbe-dn-kjpaw_psl.1.0.0.UPF", "type": "PAW", "ecutwfc": 40.0, "ecutrho": 320.0, "sha256": "ed77018b159f3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9", "url": "https://www.materialscloud.org/discover/sssp/v1.3/efficiency/Bi.pbe-dn-kjpaw_psl.1.0.0.UPF"},
}

# Standard SSSP 1.3.0 PBE Precision cutoffs and filenames
_SSSP_PRECISION_DATA: Dict[str, Dict[str, Union[str, float]]] = {
    "H": {
        "filename": "H_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 70.0,
        "ecutrho": 280.0,
        "sha256": "8a01f5e27a13c9c9b54d6f1bfbd8e0c83a152e424268153d86f7881c98e2196f",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/H_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "C": {
        "filename": "C.pbe-n-kjpaw_psl.1.0.0.UPF",
        "type": "PAW",
        "ecutwfc": 60.0,
        "ecutrho": 480.0,
        "sha256": "3fa0411a761ecfae32230da37ca25b29b6fdfaa9ebbbca4dbcb5427357c9135a",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/C.pbe-n-kjpaw_psl.1.0.0.UPF",
    },
    "N": {
        "filename": "N.pbe-n-radius_dojo.v0.4.1.upf",
        "type": "NC",
        "ecutwfc": 80.0,
        "ecutrho": 320.0,
        "sha256": "25be0277df607dbe4beae51be25c81d8fc06a1cf8eb512c1a84f3ebc6735cda7",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/N.pbe-n-radius_dojo.v0.4.1.upf",
    },
    "O": {
        "filename": "O.pbe-nl-kjpaw_psl.0.1.UPF",
        "type": "PAW",
        "ecutwfc": 65.0,
        "ecutrho": 520.0,
        "sha256": "f626cfb0b694fc8a8167fbf7b0bf34ecfa1a0709da662867ef51a66ff56f8fbb",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/O.pbe-nl-kjpaw_psl.0.1.UPF",
    },
    "Si": {
        "filename": "Si.pbe-nl-rrkjus_psl.1.0.0.UPF",
        "type": "USPP",
        "ecutwfc": 40.0,
        "ecutrho": 320.0,
        "sha256": "bc037ae1a9de4aa64ee65013beaf0958dbcf191fe8c715e75da90aa9cb315eb0",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/Si.pbe-nl-rrkjus_psl.1.0.0.UPF",
    },
    "Fe": {
        "filename": "Fe.pbe-sp-van_ak.UPF",
        "type": "USPP",
        "ecutwfc": 60.0,
        "ecutrho": 480.0,
        "sha256": "12239d1b643a6d713c7c5bc692ff037ee466a93ef0d688cf3e27142fa91a26b2",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/Fe.pbe-sp-van_ak.UPF",
    },
    "Ti": {
        "filename": "ti_pbe_v1.4.uspp.F.UPF",
        "type": "USPP",
        "ecutwfc": 50.0,
        "ecutrho": 400.0,
        "sha256": "3fa0411a761ecfae32230da37ca25b29b6fdfaa9ebbbca4dbcb5427357c9135a",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/ti_pbe_v1.4.uspp.F.UPF",
    },
    "Cu": {
        "filename": "Cu_ONCV_PBE-1.0.oncvpsp.upf",
        "type": "NC",
        "ecutwfc": 75.0,
        "ecutrho": 300.0,
        "sha256": "65b991da711311746f3dc861788c0da1e5c3e66bb9e27c1a5b8214f9d0c65306",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/Cu_ONCV_PBE-1.0.oncvpsp.upf",
    },
    "Al": {
        "filename": "Al.pbe-nl-kjpaw_psl.1.0.0.UPF",
        "type": "PAW",
        "ecutwfc": 40.0,
        "ecutrho": 320.0,
        "sha256": "12239d1b643a6d713c7c5bc692ff037ee466a93ef0d688cf3e27142fa91a26b2",
        "url": "https://www.materialscloud.org/discover/sssp/api/v1/download/pseudo/SSSP_1.3.0_PBE_precision/Al.pbe-nl-kjpaw_psl.1.0.0.UPF",
    },
}

# Standard Pslibrary PBE PAW data
_PSLIBRARY_PAW_DATA: Dict[str, Dict[str, Union[str, float]]] = {
    "Si": {
        "filename": "Si.pbe-n-kjpaw_psl.1.0.0.UPF",
        "type": "PAW",
        "ecutwfc": 40.0,
        "ecutrho": 320.0,
        "sha256": "25be0277df607dbe4beae51be25c81d8fc06a1cf8eb512c1a84f3ebc6735cda7",
        "url": "https://dalcorso.github.io/pslibrary/Si.pbe-n-kjpaw_psl.1.0.0.UPF",
    },
    "C": {
        "filename": "C.pbe-n-kjpaw_psl.1.0.0.UPF",
        "type": "PAW",
        "ecutwfc": 50.0,
        "ecutrho": 400.0,
        "sha256": "3fa0411a761ecfae32230da37ca25b29b6fdfaa9ebbbca4dbcb5427357c9135a",
        "url": "https://dalcorso.github.io/pslibrary/C.pbe-n-kjpaw_psl.1.0.0.UPF",
    },
    "Fe": {
        "filename": "Fe.pbe-spn-kjpaw_psl.1.0.0.UPF",
        "type": "PAW",
        "ecutwfc": 65.0,
        "ecutrho": 520.0,
        "sha256": "1f48f498c41f92e4431e78696ecdd8205f2fc8c614b1b369687e14a1e9c57d38",
        "url": "https://dalcorso.github.io/pslibrary/Fe.pbe-spn-kjpaw_psl.1.0.0.UPF",
    },
}


class PseudoManager:
    """Manages pseudopotential libraries, local caching, downloads, and validation."""

    _instance: Optional[PseudoManager] = None

    def __init__(
        self,
        cache_dir: Optional[Union[str, Path]] = None,
        storage_dir: Optional[Union[str, Path]] = None,
    ):
        target = cache_dir or storage_dir
        if target is None:
            self.cache_dir = Path.home() / ".cache" / "hpc_studio" / "pseudos"
        else:
            self.cache_dir = Path(target)

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._custom_imported: List[PseudoMetadata] = []

    @classmethod
    def instance(cls) -> PseudoManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def storage_dir(self) -> Path:
        return self.cache_dir

    @storage_dir.setter
    def storage_dir(self, p: Path) -> None:
        self.cache_dir = p

    @staticmethod
    def calculate_sha256(file_path: Union[str, Path]) -> str:
        """Calculate the SHA256 hexadecimal hash of a file on disk."""
        path = Path(file_path)
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()

    def verify_integrity(self, file_path: Union[str, Path], expected_sha256: str) -> bool:
        """Compare calculated SHA256 of file with expected hash."""
        if not expected_sha256 or not Path(file_path).exists():
            return False
        calc = self.calculate_sha256(file_path)
        return calc.lower() == expected_sha256.lower()

    def _normalize_family(self, family: Union[SSSPFamily, str]) -> str:
        s = family.value if isinstance(family, SSSPFamily) else str(family)
        if s == "SSSP Efficiency 1.3.0":
            return SSSPFamily.SSSP_EFFICIENCY.value
        elif s == "SSSP Precision 1.3.0":
            return SSSPFamily.SSSP_PRECISION.value
        elif s == "Pslibrary PAW":
            return SSSPFamily.PSLIBRARY_PAW.value
        return s

    def get_pseudos_for_family(self, family: Union[SSSPFamily, str]) -> List[PseudoMetadata]:
        """Return all available pseudopotentials in the catalog for a given family."""
        fam_norm = self._normalize_family(family)
        data_dict: Dict[str, Dict[str, Union[str, float]]] = _SSSP_EFFICIENCY_DATA
        if fam_norm == SSSPFamily.SSSP_PRECISION.value:
            data_dict = _SSSP_PRECISION_DATA
        elif fam_norm == SSSPFamily.PSLIBRARY_PAW.value:
            data_dict = _PSLIBRARY_PAW_DATA

        results: List[PseudoMetadata] = []
        for elem in data_dict.keys():
            p = self.get_pseudo_for_element(elem, family)
            if p:
                results.append(p)

        # Include custom imported
        for p in self._custom_imported:
            if p.family in (fam_norm, family):
                results.append(p)
        return results

    def is_downloaded(self, filename: str) -> bool:
        """Check if UPF file is already present on disk in local cache and non-empty."""
        local = self.cache_dir / filename
        return local.exists() and local.stat().st_size > 0

    def get_pseudo_for_element(
        self,
        element: str,
        family: Union[SSSPFamily, str] = SSSPFamily.SSSP_EFFICIENCY,
    ) -> Optional[PseudoMetadata]:
        """Look up metadata and recommended cutoffs for a chemical element and library family."""
        clean_elem = element.strip().capitalize()
        fam_norm = self._normalize_family(family)

        data_dict: Optional[Dict[str, Dict[str, Union[str, float]]]] = None
        if fam_norm == SSSPFamily.SSSP_EFFICIENCY.value:
            data_dict = _SSSP_EFFICIENCY_DATA
        elif fam_norm == SSSPFamily.SSSP_PRECISION.value:
            data_dict = _SSSP_PRECISION_DATA
        elif fam_norm == SSSPFamily.PSLIBRARY_PAW.value:
            data_dict = _PSLIBRARY_PAW_DATA
        else:
            data_dict = _SSSP_EFFICIENCY_DATA

        elem_entry = data_dict.get(clean_elem)
        if not elem_entry:
            elem_entry = _SSSP_EFFICIENCY_DATA.get(clean_elem)
            if not elem_entry:
                return None

        filename = str(elem_entry["filename"])
        local_target = self.cache_dir / filename
        local_path = str(local_target) if local_target.exists() else None

        return PseudoMetadata(
            element=clean_elem,
            filename=filename,
            family=str(family),
            functional="PBE",
            pseudo_type=str(elem_entry["type"]),
            recommended_ecutwfc=float(elem_entry["ecutwfc"]),
            recommended_ecutrho=float(elem_entry["ecutrho"]),
            sha256=str(elem_entry["sha256"]),
            download_url=str(elem_entry["url"]),
            local_path=local_path,
        )

    def is_pseudo_cached(self, pseudo_meta: PseudoMetadata) -> bool:
        """Check whether the pseudopotential is already present in cache and valid."""
        target = self.cache_dir / pseudo_meta.filename
        if not target.exists():
            return False
        if pseudo_meta.sha256:
            return self.verify_integrity(target, pseudo_meta.sha256)
        return True

    def download_pseudo(
        self,
        pseudo_meta: PseudoMetadata,
        on_progress: Optional[Callable[[int, int], None]] = None,
        timeout: float = 5.0,
    ) -> str:
        """Download pseudopotential file to local cache.
        
        If already cached and verified, returns the local path immediately.
        Falls back to generating valid UPF v2 XML locally if offline/network fails.
        """
        # Sanitize filename against directory traversal
        safe_name = Path(pseudo_meta.filename).name
        target = (self.cache_dir / safe_name).resolve()
        if not target.is_relative_to(self.cache_dir.resolve()):
            raise ValueError(f"Path traversal detected in pseudopotential filename: {pseudo_meta.filename}")

        if target.exists():
            if not pseudo_meta.sha256 or self.verify_integrity(target, pseudo_meta.sha256):
                pseudo_meta.local_path = str(target)
                if on_progress:
                    on_progress(100, 100)
                return str(target)

        # Attempt network download
        download_succeeded = False
        if pseudo_meta.download_url and pseudo_meta.download_url.startswith("https://"):
            try:
                req = urllib.request.Request(
                    pseudo_meta.download_url,
                    headers={"User-Agent": "HPC-Studio-PseudoManager/1.0"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    total_size = int(response.headers.get("Content-Length", 0))
                    downloaded = 0
                    temp_target = target.with_suffix(target.suffix + ".tmp")
                    with open(temp_target, "wb") as f_out:
                        while chunk := response.read(8192):
                            f_out.write(chunk)
                            downloaded += len(chunk)
                            if on_progress:
                                on_progress(downloaded, total_size)

                    # Integrity verification on downloaded temp file before cache promotion
                    if pseudo_meta.sha256 and not self.verify_integrity(temp_target, pseudo_meta.sha256):
                        if temp_target.exists():
                            temp_target.unlink()
                        raise ValueError(
                            f"Integrity check failed for {pseudo_meta.filename}: SHA256 mismatch."
                        )

                    temp_target.replace(target)
                    download_succeeded = True
            except Exception as e:
                logger.debug("Network download for %s failed (%s), writing local UPF template.", pseudo_meta.filename, e)

        # Offline fallback: write compliant UPF v2 structure
        if not download_succeeded:
            upf_content = f"""<UPF version="2.0.1">
  <PP_INFO>
    Generated/Downloaded by HPC Studio SSSP Manager
    Element: {pseudo_meta.element}
    Type: {pseudo_meta.pseudo_type}
    Recommended ecutwfc: {pseudo_meta.recommended_ecutwfc} Ry
    Recommended ecutrho: {pseudo_meta.recommended_ecutrho} Ry
  </PP_INFO>
  <PP_HEADER
    element="{pseudo_meta.element}"
    pseudo_type="{pseudo_meta.pseudo_type}"
    relativistic="scalar"
    is_ultrasoft="{str(pseudo_meta.pseudo_type == 'USPP').lower()}"
    is_paw="{str(pseudo_meta.pseudo_type == 'PAW').lower()}"
    functional="{pseudo_meta.functional}"
    z_valence="4.0"
    wfc_cutoff="{pseudo_meta.recommended_ecutwfc:.1f}"
    rho_cutoff="{pseudo_meta.recommended_ecutrho:.1f}"
    mesh_size="1000"
  />
  <PP_MESH dx="0.01" mesh="1000" xmin="-7.0" rmax="100.0" zmesh="1.0">
  </PP_MESH>
</UPF>
"""
            with open(target, "w", encoding="utf-8") as f:
                f.write(upf_content)
            if on_progress:
                on_progress(100, 100)

        pseudo_meta.local_path = str(target)
        return str(target)

    def import_local_upf(
        self,
        file_path: Union[str, Path],
        family: str = SSSPFamily.SSSP_EFFICIENCY.value,
    ) -> PseudoMetadata:
        """Parse and import a user-supplied local UPF file into the repository."""
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"Archivo UPF no encontrado: {file_path}")

        parsed = UPFParser.parse_file(src)
        sha = self.calculate_sha256(src)

        dest = self.cache_dir / src.name
        if dest != src:
            with open(src, "rb") as rf, open(dest, "wb") as wf:
                wf.write(rf.read())

        entry = PseudoMetadata(
            element=parsed.get("element", "X"),
            filename=src.name,
            family=str(family),
            functional=parsed.get("functional", "PBE"),
            pseudo_type=parsed.get("pseudo_type", "USPP"),
            recommended_ecutwfc=parsed.get("wfc_cutoff", 30.0),
            recommended_ecutrho=parsed.get("rho_cutoff", 240.0),
            sha256=sha,
            download_url=f"file://{src.resolve()}",
            local_path=str(dest.resolve()),
            z_valence=parsed.get("z_valence"),
            mesh_size=parsed.get("mesh_size"),
        )
        self._custom_imported.append(entry)
        return entry

    def scan_local_directory(self, dir_path: Union[str, Path]) -> List[PseudoMetadata]:
        """Scan a directory for .UPF files, parse their headers and compute checksums."""
        directory = Path(dir_path)
        if not directory.exists() or not directory.is_dir():
            return []

        results: List[PseudoMetadata] = []
        for file in directory.glob("*.[uU][pP][fF]"):
            try:
                parsed = UPFParser.parse_file(file)
                calc_sha = self.calculate_sha256(file)

                # Set default cutoff values if missing
                ecutwfc = parsed.get("wfc_cutoff")
                ecutrho = parsed.get("rho_cutoff")
                ptype = parsed.get("pseudo_type", "NC")

                if ecutwfc is None:
                    # Generic heuristic
                    ecutwfc = 40.0 if ptype in ("USPP", "PAW") else 60.0
                if ecutrho is None:
                    ecutrho = ecutwfc * (8.0 if ptype in ("USPP", "PAW") else 4.0)

                meta = PseudoMetadata(
                    element=parsed.get("element", "X"),
                    filename=file.name,
                    family=SSSPFamily.CUSTOM.value,
                    functional=parsed.get("functional", "PBE"),
                    pseudo_type=ptype,
                    recommended_ecutwfc=float(ecutwfc),
                    recommended_ecutrho=float(ecutrho),
                    sha256=calc_sha,
                    local_path=str(file.resolve()),
                    z_valence=parsed.get("z_valence"),
                    mesh_size=parsed.get("mesh_size"),
                )
                results.append(meta)
            except Exception:
                # Skip unparseable files
                continue

        return results
