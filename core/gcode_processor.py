from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class ProcessedJob:
    body_lines: List[str]
    original_source: str


def _strip_inline_comment(line: str) -> str:
    """Strip inline comments starting with ';'."""
    return line.split(";", 1)[0]


def _is_full_line_comment(line: str) -> bool:
    s = line.strip()
    return s.startswith("(") and s.endswith(")")


def _has_spindle_s(line: str) -> bool:
    """
    Return True if line contains an S word used as G-code (not inside comments).
    """
    if _is_full_line_comment(line):
        return False
    code = _strip_inline_comment(line).strip()
    if not code:
        return False
    for token in code.split():
        if token.startswith("S") and len(token) > 1:
            # S followed by number or sign/decimal
            ch = token[1]
            if ch.isdigit() or ch in "+-.":
                return True
    return False


def _has_m5(line: str) -> bool:
    """
    Return True if line contains an M5/M05 word used as G-code (not inside comments).
    """
    if _is_full_line_comment(line):
        return False
    code = _strip_inline_comment(line).strip().upper()
    if not code:
        return False
    for token in code.split():
        if token in ("M5", "M05"):
            return True
    return False


def extract_body(source: str) -> List[str]:
    """
    Extract the geometric body of a G-code program.

    Rules:
    - Header: all lines from the beginning up to and including the FIRST
      line that contains an S word (spindle speed) are considered header
      and removed. S inside bracket comments are ignored.
    - Footer: all lines from the last M5/M05 (used as code, not in comments)
      to the end of the file are considered footer and removed.
    """
    lines = source.splitlines()
    if not lines:
        return []

    header_end = -1
    for i, line in enumerate(lines):
        if _has_spindle_s(line):
            header_end = i
            break

    if header_end == -1:
        body_start = 0
    else:
        body_start = header_end + 1

    footer_start = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if _has_m5(lines[i]):
            footer_start = i
            break

    if footer_start < body_start:
        footer_start = len(lines)

    body = lines[body_start:footer_start]

    # Strip trailing empty lines for a cleaner editor view
    while body and not body[-1].strip():
        body.pop()

    return body or lines


def process_gcode_file(content: str) -> ProcessedJob:
    body = extract_body(content)
    return ProcessedJob(body_lines=body, original_source=content)
