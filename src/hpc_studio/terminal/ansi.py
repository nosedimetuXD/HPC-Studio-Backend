"""ANSI and VT100 escape sequence parser and styling engine for HPC Studio Linux.

Sprint 1.4 terminal subsystem component. Provides high-performance parsing of
ANSI escape codes, 16 standard colors, 256-color xterm palette, 24-bit TrueColor,
text styling attributes (bold, dim, italic, underline, reverse, strikethrough),
and seamless translation into PySide6 QTextCharFormat structures or style tuples.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

try:
    from PySide6.QtGui import QColor, QFont, QTextCharFormat
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


@dataclass(frozen=True)
class TerminalColor:
    """Represents an RGB color used in terminal text rendering."""

    r: int
    g: int
    b: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "r", max(0, min(255, int(self.r))))
        object.__setattr__(self, "g", max(0, min(255, int(self.g))))
        object.__setattr__(self, "b", max(0, min(255, int(self.b))))

    def to_rgb_tuple(self) -> Tuple[int, int, int]:
        """Return RGB as a 3-tuple (r, g, b)."""
        return (self.r, self.g, self.b)

    def to_hex(self) -> str:
        """Format as #RRGGBB hex string."""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def to_qcolor(self) -> Any:
        """Convert to PySide6.QtGui.QColor."""
        if not PYSIDE6_AVAILABLE:
            raise RuntimeError("PySide6 is required to create a QColor instance.")
        return QColor(self.r, self.g, self.b)

    @classmethod
    def from_rgb(cls, r: int, g: int, b: int) -> TerminalColor:
        """Construct from red, green, blue integer values (0-255)."""
        return cls(r=r, g=g, b=b)

    @classmethod
    def from_hex(cls, hex_str: str) -> TerminalColor:
        """Construct from hex string e.g. '#ff00aa' or 'ff00aa'."""
        s = hex_str.lstrip("#")
        if len(s) != 6:
            raise ValueError(f"Invalid hex color string: {hex_str}")
        return cls(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))

    @classmethod
    def from_ansi(cls, code: int) -> TerminalColor:
        """Construct from standard 16-color ANSI code (30-37, 90-97, 40-47, 100-107, or 0-15)."""
        if 0 <= code <= 15:
            return STANDARD_COLORS_16[code]
        if 30 <= code <= 37:
            return STANDARD_COLORS_16[code - 30]
        if 90 <= code <= 97:
            return STANDARD_COLORS_16[code - 90 + 8]
        if 40 <= code <= 47:
            return STANDARD_COLORS_16[code - 40]
        if 100 <= code <= 107:
            return STANDARD_COLORS_16[code - 100 + 8]
        raise ValueError(f"Unknown standard ANSI color code: {code}")

    @classmethod
    def from_256(cls, index: int) -> TerminalColor:
        """Construct from xterm 256-color palette index (0-255)."""
        return get_256_color(index)


# Standard 16 ANSI Color Palette (VGA / Xterm standard)
STANDARD_COLORS_16: Dict[int, TerminalColor] = {
    0: TerminalColor(0, 0, 0),        # 0: Black
    1: TerminalColor(205, 0, 0),      # 1: Red
    2: TerminalColor(0, 205, 0),      # 2: Green
    3: TerminalColor(205, 205, 0),    # 3: Yellow
    4: TerminalColor(0, 0, 238),      # 4: Blue
    5: TerminalColor(205, 0, 205),    # 5: Magenta
    6: TerminalColor(0, 205, 205),    # 6: Cyan
    7: TerminalColor(229, 229, 229),  # 7: White
    8: TerminalColor(127, 127, 127),  # 8: Bright Black / Gray
    9: TerminalColor(255, 0, 0),      # 9: Bright Red
    10: TerminalColor(0, 255, 0),     # 10: Bright Green
    11: TerminalColor(255, 255, 0),   # 11: Bright Yellow
    12: TerminalColor(92, 92, 255),   # 12: Bright Blue
    13: TerminalColor(255, 0, 255),   # 13: Bright Magenta
    14: TerminalColor(0, 255, 255),   # 14: Bright Cyan
    15: TerminalColor(255, 255, 255), # 15: Bright White
}

# 6x6x6 color cube component steps
_CUBE_STEPS: Tuple[int, ...] = (0, 95, 135, 175, 215, 255)


def get_256_color(index: int) -> TerminalColor:
    """Return the TerminalColor corresponding to index 0-255 in the xterm 256-color palette."""
    if not (0 <= index <= 255):
        raise ValueError(f"256-color index must be between 0 and 255, got {index}")

    if index < 16:
        return STANDARD_COLORS_16[index]

    if index < 232:
        idx = index - 16
        r = _CUBE_STEPS[idx // 36]
        g = _CUBE_STEPS[(idx % 36) // 6]
        b = _CUBE_STEPS[idx % 6]
        return TerminalColor(r, g, b)

    # Grayscale ramp: 24 steps from 232 to 255 (value: 8 + 10 * step)
    gray = 8 + (index - 232) * 10
    return TerminalColor(gray, gray, gray)


@dataclass
class ANSIChunk:
    """A segment of text accompanied by its active terminal formatting and styling."""

    text: str
    fg_color: Optional[TerminalColor] = None
    bg_color: Optional[TerminalColor] = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
    strikethrough: bool = False

    def to_style_dict(self) -> Dict[str, Any]:
        """Convert style attributes to a plain dictionary."""
        return {
            "fg_color": self.fg_color.to_hex() if self.fg_color else None,
            "bg_color": self.bg_color.to_hex() if self.bg_color else None,
            "bold": self.bold,
            "dim": self.dim,
            "italic": self.italic,
            "underline": self.underline,
            "reverse": self.reverse,
            "strikethrough": self.strikethrough,
        }

    def to_tuple(self) -> Tuple[str, Dict[str, Any]]:
        """Return structured tuple (text, style_dict)."""
        return (self.text, self.to_style_dict())

    def to_char_format(
        self,
        default_fg: Optional[TerminalColor] = None,
        default_bg: Optional[TerminalColor] = None,
    ) -> Any:
        """Convert chunk attributes to a PySide6 QTextCharFormat."""
        if not PYSIDE6_AVAILABLE:
            raise RuntimeError("PySide6 is required to generate a QTextCharFormat.")

        fmt = QTextCharFormat()

        fg = self.fg_color or default_fg
        bg = self.bg_color or default_bg

        # When reverse video is active, foreground and background swap
        if self.reverse:
            fg, bg = bg, fg

        if fg is not None:
            if self.dim:
                # Dim color: slightly desaturated or alpha-reduced
                dim_qcolor = QColor(fg.r, fg.g, fg.b, 160)
                fmt.setForeground(dim_qcolor)
            else:
                fmt.setForeground(fg.to_qcolor())

        if bg is not None:
            fmt.setBackground(bg.to_qcolor())

        if self.bold:
            fmt.setFontWeight(QFont.Weight.Bold)

        if self.underline:
            fmt.setFontUnderline(True)

        if self.italic:
            fmt.setFontItalic(True)

        if self.strikethrough:
            fmt.setFontStrikeOut(True)

        return fmt


# Regular expression to match ANSI escape sequences for stripping
ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1b     # ESC
    (?:
        \[   # CSI
        [0-?]*  # Parameter bytes
        [ -/]*  # Intermediate bytes
        [@-~]   # Final byte
    |
        \]   # OSC
        [^\x07\x1b]* # Content
        (?:\x07|\x1b\\) # BEL or ST
    |
        [@-Z\\-_] # Fe escape sequences
    )
    """,
    re.VERBOSE,
)


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences, CSI controls, and OSC strings from text."""
    return ANSI_ESCAPE_RE.sub("", text)


# Security limits for stream parsing
MAX_BUFFER_LENGTH = 4096
MAX_OSC_LENGTH = 1024
MAX_CSI_LENGTH = 256
MAX_SGR_PARAMS = 32
MAX_TITLE_LENGTH = 128


def _sanitize_terminal_title(title: str, max_length: int = MAX_TITLE_LENGTH) -> str:
    """Sanitize terminal window title to prevent ANSI/control sequence injection and DoS."""
    if not title:
        return ""
    # Strip non-printable ASCII and control characters
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", title)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:max_length]


class ANSIParser:
    """Stateful ANSI / VT100 terminal stream parser.

    Maintains active styling state across chunks, parses 16-color, 256-color,
    and 24-bit TrueColor SGR codes, tracks font attributes, and handles screen
    and cursor control sequences.
    """

    def __init__(self) -> None:
        # Styling state
        self._fg_color: Optional[TerminalColor] = None
        self._bg_color: Optional[TerminalColor] = None
        self._bold: bool = False
        self._dim: bool = False
        self._italic: bool = False
        self._underline: bool = False
        self._reverse: bool = False
        self._strikethrough: bool = False

        # Incomplete escape sequence buffer for streaming
        self._buffer: str = ""

        # Control callbacks
        self.on_clear_screen: Optional[Callable[[], None]] = None
        self.on_clear_line: Optional[Callable[[int], None]] = None  # 0: to end, 1: to start, 2: all
        self.on_cursor_position: Optional[Callable[[int, int], None]] = None  # (row, col)
        self.on_title_changed: Optional[Callable[[str], None]] = None
        self.on_bell: Optional[Callable[[], None]] = None

    def reset_format(self) -> None:
        """Reset all active font styles and colors to defaults."""
        self._fg_color = None
        self._bg_color = None
        self._bold = False
        self._dim = False
        self._italic = False
        self._underline = False
        self._reverse = False
        self._strikethrough = False

    def reset(self) -> None:
        """Reset both formatting and internal stream buffer."""
        self.reset_format()
        self._buffer = ""

    def feed(self, text: str) -> List[ANSIChunk]:
        """Feed a string of terminal output into the parser and return styled chunks.

        If an escape sequence is incomplete at the end of the input, it is buffered
        until the next feed() call.
        """
        data = self._buffer + text
        self._buffer = ""
        chunks: List[ANSIChunk] = []
        current_text: List[str] = []

        def flush_text() -> None:
            if current_text:
                chunk_str = "".join(current_text)
                chunks.append(
                    ANSIChunk(
                        text=chunk_str,
                        fg_color=self._fg_color,
                        bg_color=self._bg_color,
                        bold=self._bold,
                        dim=self._dim,
                        italic=self._italic,
                        underline=self._underline,
                        reverse=self._reverse,
                        strikethrough=self._strikethrough,
                    )
                )
                current_text.clear()

        i = 0
        n = len(data)

        while i < n:
            ch = data[i]

            # Bell control character
            if ch == "\x07":
                if self.on_bell:
                    self.on_bell()
                i += 1
                continue

            # Start of Escape Sequence
            if ch == "\x1b":
                # Check if we have enough characters or if at end of buffer
                if i + 1 >= n:
                    # Incomplete sequence at boundary
                    self._buffer = data[i:]
                    break

                next_ch = data[i + 1]

                # --- 1. CSI: Control Sequence Introducer (\x1b[) ---
                if next_ch == "[":
                    # Scan for final byte (ASCII 0x40 to 0x7E: '@' through '~')
                    j = i + 2
                    while j < n and not (0x40 <= ord(data[j]) <= 0x7E):
                        if j - i > MAX_CSI_LENGTH:
                            break
                        j += 1

                    if j >= n or j - i > MAX_CSI_LENGTH:
                        if j - i > MAX_CSI_LENGTH:
                            # Drop corrupt or oversized CSI sequence to prevent buffer exhaustion
                            i += 2
                            continue
                        # Sequence is incomplete; buffer and wait for next feed if within limit
                        if len(data) - i > MAX_BUFFER_LENGTH:
                            self._buffer = ""
                        else:
                            self._buffer = data[i:]
                        break

                    final_byte = data[j]
                    param_str = data[i + 2 : j]

                    # Flush any accumulated plain text before applying control
                    flush_text()

                    self._handle_csi(param_str, final_byte)
                    i = j + 1
                    continue

                # --- 2. OSC: Operating System Command (\x1b]) ---
                elif next_ch == "]":
                    # Scan for terminator: BEL (\x07) or ST (\x1b\\)
                    j = i + 2
                    found_term = False
                    term_len = 0

                    while j < n:
                        if j - i > MAX_OSC_LENGTH:
                            break
                        if data[j] == "\x07":
                            found_term = True
                            term_len = 1
                            break
                        if data[j : j + 2] == "\x1b\\":
                            found_term = True
                            term_len = 2
                            break
                        j += 1

                    if not found_term:
                        # Incomplete OSC sequence or sequence exceeded MAX_OSC_LENGTH
                        if j - i > MAX_OSC_LENGTH or len(data) - i > MAX_BUFFER_LENGTH:
                            # Drop corrupt or oversized OSC sequence
                            i += 2
                            continue
                        self._buffer = data[i:]
                        break

                    osc_content = data[i + 2 : j]
                    flush_text()
                    self._handle_osc(osc_content)
                    i = j + term_len
                    continue

                # --- 3. Character Set Designation (e.g. \x1b(B) ---
                elif next_ch in ("(", ")", "*", "+"):
                    if i + 2 < n:
                        i += 3
                        continue
                    else:
                        self._buffer = data[i:]
                        break

                # --- 4. Other 2-char escape sequences (e.g. \x1bM, \x1b7, \x1b8, \x1bc) ---
                else:
                    flush_text()
                    if next_ch == "c":
                        # RIS: Reset to Initial State
                        self.reset_format()
                    i += 2
                    continue

            # Normal printable character or standard control (e.g. \r, \n, \t, \b)
            current_text.append(ch)
            i += 1

        flush_text()
        return chunks

    def parse(self, text: str) -> List[ANSIChunk]:
        """Convenience alias for feed(text)."""
        return self.feed(text)

    def parse_to_formats(self, text: str) -> List[Tuple[str, Any]]:
        """Parse text and return a list of tuples containing (text, QTextCharFormat)."""
        chunks = self.feed(text)
        return [(c.text, c.to_char_format()) for c in chunks]

    def parse_to_tuples(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Parse text and return a list of structured tuples (text, style_dict)."""
        chunks = self.feed(text)
        return [c.to_tuple() for c in chunks]

    @classmethod
    def parse_string(cls, text: str) -> List[ANSIChunk]:
        """Statelessly parse a standalone string and return styled chunks."""
        parser = cls()
        return parser.feed(text)

    # --------------------------------------------------------------------------
    # CSI and OSC Sequence Handlers
    # --------------------------------------------------------------------------

    def _handle_csi(self, param_str: str, final_byte: str) -> None:
        """Process a completed CSI escape sequence."""
        if final_byte == "m":
            # SGR: Select Graphic Rendition
            self._handle_sgr(param_str)
        elif final_byte == "J":
            # ED: Erase in Display (Clear Screen)
            mode = int(param_str) if param_str.isdigit() else 0
            if self.on_clear_screen and mode in (0, 1, 2, 3):
                self.on_clear_screen()
        elif final_byte == "K":
            # EL: Erase in Line
            mode = int(param_str) if param_str.isdigit() else 0
            if self.on_clear_line:
                self.on_clear_line(mode)
        elif final_byte in ("H", "f"):
            # CUP / HVP: Cursor Position
            if self.on_cursor_position:
                coords = [int(p) if p.isdigit() else 1 for p in param_str.split(";") if p]
                row = max(1, min(10000, coords[0])) if len(coords) > 0 else 1
                col = max(1, min(10000, coords[1])) if len(coords) > 1 else 1
                self.on_cursor_position(row, col)

    def _handle_osc(self, content: str) -> None:
        """Process an Operating System Command (e.g. window title setting).

        Ignores OSC 52 (clipboard access) and other dangerous OSC codes,
        and sanitizes window titles to prevent terminal injection and spoofing.
        """
        # Formats: '0;title' or '2;title'
        if ";" in content:
            cmd, title = content.split(";", 1)
            if cmd in ("0", "1", "2"):
                clean_title = _sanitize_terminal_title(title)
                if clean_title and self.on_title_changed:
                    self.on_title_changed(clean_title)

    def _handle_sgr(self, param_str: str) -> None:
        """Process SGR parameters for colors, styles, and font attributes."""
        if not param_str:
            self.reset_format()
            return

        # SGR parameters can be separated by ';' or ':'
        normalized = param_str.replace(":", ";")
        parts = [p.strip() for p in normalized.split(";") if p.strip()][:MAX_SGR_PARAMS]

        if not parts:
            self.reset_format()
            return

        idx = 0
        total = len(parts)

        while idx < total:
            try:
                code = int(parts[idx])
            except ValueError:
                idx += 1
                continue

            if code == 0:
                self.reset_format()

            # Font Attributes
            elif code == 1:
                self._bold = True
            elif code == 2:
                self._dim = True
            elif code == 3:
                self._italic = True
            elif code == 4:
                self._underline = True
            elif code == 7:
                self._reverse = True
            elif code == 9:
                self._strikethrough = True
            elif code in (21, 22):
                # 21: Bold off (or double underline), 22: Normal intensity (bold off & dim off)
                self._bold = False
                self._dim = False
            elif code == 23:
                self._italic = False
            elif code == 24:
                self._underline = False
            elif code == 27:
                self._reverse = False
            elif code == 29:
                self._strikethrough = False

            # Standard Foreground Colors (30-37)
            elif 30 <= code <= 37:
                self._fg_color = STANDARD_COLORS_16[code - 30]

            # Extended Foreground Color (38)
            elif code == 38:
                color, consumed = self._parse_extended_color(parts[idx + 1 :])
                if color is not None:
                    self._fg_color = color
                idx += consumed

            # Default Foreground Color
            elif code == 39:
                self._fg_color = None

            # Standard Background Colors (40-47)
            elif 40 <= code <= 47:
                self._bg_color = STANDARD_COLORS_16[code - 40]

            # Extended Background Color (48)
            elif code == 48:
                color, consumed = self._parse_extended_color(parts[idx + 1 :])
                if color is not None:
                    self._bg_color = color
                idx += consumed

            # Default Background Color
            elif code == 49:
                self._bg_color = None

            # High Intensity (Bright) Foreground Colors (90-97)
            elif 90 <= code <= 97:
                self._fg_color = STANDARD_COLORS_16[code - 90 + 8]

            # High Intensity (Bright) Background Colors (100-107)
            elif 100 <= code <= 107:
                self._bg_color = STANDARD_COLORS_16[code - 100 + 8]

            idx += 1

    def _parse_extended_color(
        self, sub_parts: List[str]
    ) -> Tuple[Optional[TerminalColor], int]:
        """Parse extended color arguments (mode 5: 256 colors, mode 2: 24-bit TrueColor).

        Returns (color, number_of_items_consumed).
        """
        if not sub_parts:
            return (None, 0)

        try:
            mode = int(sub_parts[0])
            if mode == 5 and len(sub_parts) >= 2:
                # 38;5;N or 48;5;N -> index in 256-color palette
                color_idx = int(sub_parts[1])
                return (get_256_color(color_idx), 2)
            elif mode == 2 and len(sub_parts) >= 4:
                # 38;2;R;G;B or 48;2;R;G;B
                r = int(sub_parts[1])
                g = int(sub_parts[2])
                b = int(sub_parts[3])
                return (TerminalColor(r, g, b), 4)
        except (ValueError, IndexError):
            pass

        return (None, 1)
