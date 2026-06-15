"""Tests for app/core/log_safe.scrub — log-injection sanitizer."""

from __future__ import annotations

from app.core.log_safe import scrub


def test_strips_newlines_and_carriage_returns():
    assert scrub("a\nb\rc") == "a b c"


def test_blocks_forged_log_line():
    # The classic log-injection payload must not survive as a second line.
    out = scrub("oops\nINFO:root:admin logged in")
    assert "\n" not in out and "\r" not in out
    assert out == "oops INFO:root:admin logged in"


def test_drops_other_control_chars():
    assert scrub("tab\tend") == "tab end"
    assert scrub("bell\x07x") == "bell x"


def test_non_str_values_are_coerced():
    assert scrub(True) == "True"
    assert scrub(42) == "42"
    assert scrub(ValueError("bad\nvalue")) == "bad value"


def test_printable_text_unchanged():
    assert scrub("ELEGOO PLA Galaxy Black") == "ELEGOO PLA Galaxy Black"
