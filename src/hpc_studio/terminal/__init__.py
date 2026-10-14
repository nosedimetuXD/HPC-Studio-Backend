"""Terminal backend engine and ANSI parser subsystem for HPC Studio Linux.

Sprint 1.4 module providing PTY terminal backends (LocalPTYBackend, SSHPtyBackend)
and a robust ANSI/VT100 escape sequence parser and color formatting engine.
"""

from __future__ import annotations

from .ansi import (
    ANSIChunk,
    ANSIParser,
    STANDARD_COLORS_16,
    TerminalColor,
    get_256_color,
    strip_ansi,
)
from .backend import (
    LocalPTYBackend,
    SSHPtyBackend,
    TerminalBackend,
)

__all__ = [
    "TerminalBackend",
    "LocalPTYBackend",
    "SSHPtyBackend",
    "ANSIParser",
    "ANSIChunk",
    "TerminalColor",
    "strip_ansi",
    "get_256_color",
    "STANDARD_COLORS_16",
]
