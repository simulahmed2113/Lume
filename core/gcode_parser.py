from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class GCodeStatement:
    line_number: int
    raw: str
    command: str
    params: Dict[str, float]
    comment: Optional[str] = None


@dataclass
class GCodeProgram:
    statements: List[GCodeStatement]


def parse_gcode(source: str) -> GCodeProgram:
    """
    Very simple G-code parser.

    - Keeps every line (no optimisation).
    - Extracts one `command` (e.g. G1, G01, G2, M3, etc).
    - Extracts all letter+number parameters: X, Y, Z, I, J, F, ...
    - Preserves original line numbers.
    """
    statements: List[GCodeStatement] = []

    lines = source.splitlines()
    for line_number, line in enumerate(lines, start=1):
        raw = line.rstrip("\n")

        # ---- split off comments: ; or (. )
        comment: Optional[str] = None
        code_part = raw

        # ; style
        semi_idx = code_part.find(";")
        if semi_idx != -1:
            comment = code_part[semi_idx + 1 :].strip()
            code_part = code_part[:semi_idx]

        # ( . ) style – take the first '(' as start of comment
        paren_idx = code_part.find("(")
        if paren_idx != -1:
            trailing = code_part[paren_idx + 1 :].strip()
            if trailing:
                comment = trailing if comment is None else f"{comment} ({trailing})"
            code_part = code_part[:paren_idx]

        code_part = code_part.strip()

        command = ""
        params: Dict[str, float] = {}

        if code_part:
            tokens = code_part.split()
            for tok in tokens:
                if not tok:
                    continue
                letter = tok[0].upper()
                rest = tok[1:]

                # Token must be like X12.3 or G01 or Y-5 etc
                if not rest:
                    continue

                # Try to interpret as float parameter
                # (we'll treat any letter+number as param first,
                # but G/M tokens become "command" if we don't yet have one)
                try:
                    value = float(rest)
                    is_number = True
                except ValueError:
                    is_number = False

                if is_number:
                    if letter in ("G", "M") and command == "":
                        # G / M token -> command (e.g. G1, G01, M3)
                        command = letter + rest
                    else:
                        # Coordinate / feed parameter
                        params[letter] = value
                else:
                    # Not numeric, ignore
                    continue

        stmt = GCodeStatement(
            line_number=line_number,
            raw=raw,
            command=command,
            params=params,
            comment=comment,
        )
        statements.append(stmt)

    return GCodeProgram(statements=statements)


# ---------------------------------------------------------------------------
# Compatibility alias – older code imports parse_gcode_text.
# ---------------------------------------------------------------------------

def parse_gcode_text(source: str) -> GCodeProgram:
    """Backward-compatible wrapper so older imports still work."""
    return parse_gcode(source)
