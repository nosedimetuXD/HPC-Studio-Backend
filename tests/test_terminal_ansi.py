"""Unit tests for ANSI escape sequence parser and terminal styling engine.

Sprint 1.4 test suite for HPC Studio Linux.
"""

from __future__ import annotations

import pytest

try:
    from PySide6.QtGui import QFont, QTextCharFormat
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False
    QFont = None
    QTextCharFormat = None

from hpc_studio.terminal.ansi import (
    ANSIChunk,
    ANSIParser,
    STANDARD_COLORS_16,
    TerminalColor,
    get_256_color,
    strip_ansi,
)


# ==============================================================================
# Tests for TerminalColor
# ==============================================================================


def test_terminal_color_creation_and_clamping():
    """Verify RGB values are clamped within 0-255."""
    c = TerminalColor(300, -50, 128)
    assert c.r == 255
    assert c.g == 0
    assert c.b == 128
    assert c.to_rgb_tuple() == (255, 0, 128)
    assert c.to_hex() == "#ff0080"


def test_terminal_color_from_hex():
    """Verify construction from hex strings."""
    c1 = TerminalColor.from_hex("#12abef")
    assert c1 == TerminalColor(0x12, 0xAB, 0xEF)

    c2 = TerminalColor.from_hex("00ff00")
    assert c2 == TerminalColor(0, 255, 0)

    with pytest.raises(ValueError):
        TerminalColor.from_hex("invalid")


def test_terminal_color_from_ansi():
    """Verify construction from standard 16 ANSI codes."""
    # Standard 0-7
    assert TerminalColor.from_ansi(0) == STANDARD_COLORS_16[0]
    assert TerminalColor.from_ansi(1) == STANDARD_COLORS_16[1]  # Red
    assert TerminalColor.from_ansi(31) == STANDARD_COLORS_16[1]  # Red fg
    assert TerminalColor.from_ansi(41) == STANDARD_COLORS_16[1]  # Red bg

    # Bright 8-15
    assert TerminalColor.from_ansi(8) == STANDARD_COLORS_16[8]
    assert TerminalColor.from_ansi(91) == STANDARD_COLORS_16[9]  # Bright red fg
    assert TerminalColor.from_ansi(101) == STANDARD_COLORS_16[9]  # Bright red bg

    with pytest.raises(ValueError):
        TerminalColor.from_ansi(999)


@pytest.mark.skipif(not PYSIDE_AVAILABLE, reason="PySide6 is not installed")
def test_terminal_color_to_qcolor():
    """Verify conversion to PySide6 QColor."""
    c = TerminalColor(10, 20, 30)
    qcol = c.to_qcolor()
    assert qcol.red() == 10
    assert qcol.green() == 20
    assert qcol.blue() == 30


def test_get_256_color_palette():
    """Verify 256-color palette indexing and formula boundaries."""
    # First 16 match standard palette
    for i in range(16):
        assert get_256_color(i) == STANDARD_COLORS_16[i]

    # 6x6x6 color cube: 16 + 36*r + 6*g + b
    # Index 16: (0, 0, 0)
    assert get_256_color(16) == TerminalColor(0, 0, 0)
    # Index 196: r=5, g=0, b=0 -> (255, 0, 0)
    assert get_256_color(196) == TerminalColor(255, 0, 0)
    # Index 231: r=5, g=5, b=5 -> (255, 255, 255)
    assert get_256_color(231) == TerminalColor(255, 255, 255)

    # Grayscale ramp: 232 - 255 (gray = 8 + 10 * step)
    c232 = get_256_color(232)
    assert c232 == TerminalColor(8, 8, 8)
    c255 = get_256_color(255)
    assert c255 == TerminalColor(238, 238, 238)

    with pytest.raises(ValueError):
        get_256_color(256)
    with pytest.raises(ValueError):
        get_256_color(-1)


# ==============================================================================
# Tests for ANSIChunk
# ==============================================================================


def test_ansi_chunk_style_dict_and_tuple():
    """Verify serialization to style dict and structured tuple."""
    chunk = ANSIChunk(
        text="Hello",
        fg_color=TerminalColor(255, 0, 0),
        bold=True,
        underline=True,
    )
    s_dict = chunk.to_style_dict()
    assert s_dict["fg_color"] == "#ff0000"
    assert s_dict["bg_color"] is None
    assert s_dict["bold"] is True
    assert s_dict["underline"] is True
    assert s_dict["reverse"] is False

    text, retrieved_dict = chunk.to_tuple()
    assert text == "Hello"
    assert retrieved_dict == s_dict


@pytest.mark.skipif(not PYSIDE_AVAILABLE, reason="PySide6 is not installed")
def test_ansi_chunk_to_char_format():
    """Verify conversion to PySide6 QTextCharFormat with font attributes and colors."""
    chunk = ANSIChunk(
        text="Test Format",
        fg_color=TerminalColor(205, 0, 0),
        bg_color=TerminalColor(0, 0, 238),
        bold=True,
        underline=True,
        italic=True,
        strikethrough=True,
    )
    fmt = chunk.to_char_format()
    assert isinstance(fmt, QTextCharFormat)
    assert fmt.fontWeight() == QFont.Weight.Bold
    assert fmt.fontUnderline() is True
    assert fmt.fontItalic() is True
    assert fmt.fontStrikeOut() is True
    assert fmt.foreground().color().red() == 205
    assert fmt.background().color().blue() == 238


@pytest.mark.skipif(not PYSIDE_AVAILABLE, reason="PySide6 is not installed")
def test_ansi_chunk_reverse_video():
    """Verify reverse video swaps foreground and background colors in QTextCharFormat."""
    fg = TerminalColor(100, 100, 100)
    bg = TerminalColor(200, 200, 200)
    chunk = ANSIChunk(text="Inverted", fg_color=fg, bg_color=bg, reverse=True)
    fmt = chunk.to_char_format()

    # In reverse video, displayed foreground is original background
    assert fmt.foreground().color().red() == 200
    assert fmt.background().color().red() == 100


# ==============================================================================
# Tests for strip_ansi helper
# ==============================================================================


def test_strip_ansi():
    """Verify stripping of various ANSI codes and OSC title sequences."""
    raw = "\x1b[31;1mHello\x1b[0m \x1b]0;Title\x07World\x1b[2J!"
    assert strip_ansi(raw) == "Hello World!"


# ==============================================================================
# Tests for ANSIParser
# ==============================================================================


def test_plain_text():
    """Verify parsing plain text with no escape sequences."""
    parser = ANSIParser()
    chunks = parser.parse("HPC Studio Scientific Workbench")
    assert len(chunks) == 1
    assert chunks[0].text == "HPC Studio Scientific Workbench"
    assert chunks[0].fg_color is None
    assert chunks[0].bg_color is None
    assert chunks[0].bold is False


def test_standard_16_foreground_and_background_colors():
    """Verify standard ANSI foreground (30-37) and background (40-47) colors."""
    parser = ANSIParser()
    # Red foreground, Blue background
    chunks = parser.parse("\x1b[31mRed\x1b[44mRedOnBlue\x1b[0mNormal")
    assert len(chunks) == 3

    assert chunks[0].text == "Red"
    assert chunks[0].fg_color == STANDARD_COLORS_16[1]  # Red
    assert chunks[0].bg_color is None

    assert chunks[1].text == "RedOnBlue"
    assert chunks[1].fg_color == STANDARD_COLORS_16[1]  # Red persists
    assert chunks[1].bg_color == STANDARD_COLORS_16[4]  # Blue

    assert chunks[2].text == "Normal"
    assert chunks[2].fg_color is None
    assert chunks[2].bg_color is None


def test_bright_colors():
    """Verify bright foreground (90-97) and bright background (100-107) colors."""
    parser = ANSIParser()
    chunks = parser.parse("\x1b[91mBrightRed\x1b[102mOnBrightGreen\x1b[0m")
    assert len(chunks) == 2

    assert chunks[0].text == "BrightRed"
    assert chunks[0].fg_color == STANDARD_COLORS_16[9]

    assert chunks[1].text == "OnBrightGreen"
    assert chunks[1].fg_color == STANDARD_COLORS_16[9]
    assert chunks[1].bg_color == STANDARD_COLORS_16[10]


def test_default_color_resets():
    """Verify code 39 (default fg) and code 49 (default bg)."""
    parser = ANSIParser()
    chunks = parser.parse("\x1b[31;42mColor\x1b[39mDefaultFG\x1b[49mDefaultBG")
    assert len(chunks) == 3

    assert chunks[0].fg_color is not None
    assert chunks[0].bg_color is not None

    assert chunks[1].fg_color is None
    assert chunks[1].bg_color is not None

    assert chunks[2].fg_color is None
    assert chunks[2].bg_color is None


def test_256_colors_xterm():
    """Verify 256-color extended escape sequences (38;5;N and 48;5;N)."""
    parser = ANSIParser()
    chunks = parser.parse("\x1b[38;5;196mColor196\x1b[48;5;21mOnColor21\x1b[0m")
    assert len(chunks) == 2

    assert chunks[0].text == "Color196"
    assert chunks[0].fg_color == get_256_color(196)
    assert chunks[0].bg_color is None

    assert chunks[1].text == "OnColor21"
    assert chunks[1].fg_color == get_256_color(196)
    assert chunks[1].bg_color == get_256_color(21)


def test_24bit_truecolor():
    """Verify 24-bit TrueColor escape sequences (38;2;R;G;B and 48;2;R;G;B)."""
    parser = ANSIParser()
    chunks = parser.parse("\x1b[38;2;120;140;160mTrueColorFG\x1b[48;2;10;20;30mTrueColorBG\x1b[0m")
    assert len(chunks) == 2

    assert chunks[0].fg_color == TerminalColor(120, 140, 160)
    assert chunks[0].bg_color is None

    assert chunks[1].fg_color == TerminalColor(120, 140, 160)
    assert chunks[1].bg_color == TerminalColor(10, 20, 30)


def test_text_styles_and_attributes():
    """Verify bold, dim, italic, underline, reverse, strikethrough, and resets."""
    parser = ANSIParser()
    chunks = parser.parse("\x1b[1;4;7mBoldUnderlineReverse\x1b[22mNormalIntensity\x1b[24mNoUnderline\x1b[27mNoReverse")
    assert len(chunks) == 4

    # Chunk 0: bold, underline, reverse
    assert chunks[0].bold is True
    assert chunks[0].underline is True
    assert chunks[0].reverse is True

    # Chunk 1: bold off (22)
    assert chunks[1].bold is False
    assert chunks[1].underline is True
    assert chunks[1].reverse is True

    # Chunk 2: underline off (24)
    assert chunks[2].bold is False
    assert chunks[2].underline is False
    assert chunks[2].reverse is True

    # Chunk 3: reverse off (27)
    assert chunks[3].bold is False
    assert chunks[3].underline is False
    assert chunks[3].reverse is False


def test_strikethrough_and_dim():
    """Verify strikethrough (9), dim (2), and resets."""
    parser = ANSIParser()
    chunks = parser.parse("\x1b[2;9mDimStrike\x1b[29mNoStrike\x1b[22mNoDim")
    assert len(chunks) == 3

    assert chunks[0].dim is True
    assert chunks[0].strikethrough is True

    assert chunks[1].dim is True
    assert chunks[1].strikethrough is False

    assert chunks[2].dim is False
    assert chunks[2].strikethrough is False


def test_empty_sgr_reset():
    """Verify bare \x1b[m acts as reset."""
    parser = ANSIParser()
    chunks = parser.parse("\x1b[1;31mStyled\x1b[mReset")
    assert len(chunks) == 2
    assert chunks[0].bold is True
    assert chunks[0].fg_color is not None
    assert chunks[1].bold is False
    assert chunks[1].fg_color is None


def test_streaming_buffer_split_escape():
    """Verify incomplete escape sequence split across feed() calls is buffered properly."""
    parser = ANSIParser()

    # Feed 1: Ends right in the middle of CSI sequence "\x1b[3"
    c1 = parser.feed("Start text \x1b[3")
    assert len(c1) == 1
    assert c1[0].text == "Start text "

    # Feed 2: Completes the sequence "1mRed text\x1b[0m"
    c2 = parser.feed("1mRed text\x1b[0m")
    assert len(c2) == 1
    assert c2[0].text == "Red text"
    assert c2[0].fg_color == STANDARD_COLORS_16[1]


def test_screen_and_line_clear_callbacks():
    """Verify clear screen and clear line escape sequences trigger callbacks."""
    parser = ANSIParser()
    clear_screen_calls = []
    clear_line_modes = []

    parser.on_clear_screen = lambda: clear_screen_calls.append(True)
    parser.on_clear_line = lambda mode: clear_line_modes.append(mode)

    chunks = parser.parse("Before\x1b[2JAfterScreenClear\x1b[KAfterLineClear")
    assert len(clear_screen_calls) == 1
    assert clear_line_modes == [0]
    assert len(chunks) == 3
    assert chunks[0].text == "Before"
    assert chunks[1].text == "AfterScreenClear"
    assert chunks[2].text == "AfterLineClear"


def test_cursor_position_and_bell_callbacks():
    """Verify cursor position (CUP) and bell (\x07) callbacks."""
    parser = ANSIParser()
    cursor_positions = []
    bell_calls = []

    parser.on_cursor_position = lambda r, c: cursor_positions.append((r, c))
    parser.on_bell = lambda: bell_calls.append(True)

    parser.parse("\x1b[12;34H\x07Hello\x1b[HWorld")
    assert cursor_positions == [(12, 34), (1, 1)]
    assert len(bell_calls) == 1


def test_osc_title_changed_callback():
    """Verify OSC 0 and OSC 2 window title change callbacks."""
    parser = ANSIParser()
    titles = []
    parser.on_title_changed = lambda t: titles.append(t)

    # OSC 0 with BEL terminator
    parser.parse("\x1b]0;Cluster Controller CN-01\x07Text")
    assert titles == ["Cluster Controller CN-01"]

    # OSC 2 with ST terminator (\x1b\\)
    parser.parse("\x1b]2;Slurm Worker Job 42\x1b\\More Text")
    assert titles == ["Cluster Controller CN-01", "Slurm Worker Job 42"]


def test_parse_to_formats_and_tuples():
    """Verify parse_to_formats and parse_to_tuples convenience helpers."""
    parser = ANSIParser()
    raw = "\x1b[1;32mGreenBold\x1b[0m"

    tuples = parser.parse_to_tuples(raw)
    assert len(tuples) == 1
    text, style = tuples[0]
    assert text == "GreenBold"
    assert style["bold"] is True
    assert style["fg_color"] == STANDARD_COLORS_16[2].to_hex()

    if PYSIDE_AVAILABLE:
        parser.reset()
        fmts = parser.parse_to_formats(raw)
        assert len(fmts) == 1
        text, char_fmt = fmts[0]
        assert text == "GreenBold"
        assert isinstance(char_fmt, QTextCharFormat)
        assert char_fmt.fontWeight() == QFont.Weight.Bold


def test_stateless_parse_string():
    """Verify ANSIParser.parse_string helper."""
    chunks = ANSIParser.parse_string("\x1b[34mBlue\x1b[0m")
    assert len(chunks) == 1
    assert chunks[0].text == "Blue"
    assert chunks[0].fg_color == STANDARD_COLORS_16[4]
