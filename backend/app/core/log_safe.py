"""Helper for safely logging untrusted values.

Upstream API responses and exception text can contain newlines or control
characters. Logging them verbatim lets an attacker forge or inject extra log
lines (CWE-117, log injection). ``scrub`` flattens any value to a single
printable log token before it reaches the logger.
"""

from __future__ import annotations


def scrub(value: object) -> str:
    """Flatten ``value`` to a single-line, control-char-free string.

    Replaces CR/LF with spaces and drops any remaining non-printable
    characters so untrusted text can't break out of its log line.
    """
    text = str(value).replace("\r", " ").replace("\n", " ")
    return "".join(ch if (ch.isprintable() or ch == " ") else " " for ch in text)
