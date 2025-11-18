from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ProgramIndex:
    """Maps between program statements and geometry segments."""

    # statement index (0-based) -> list of segment indices
    statement_to_segments: Dict[int, List[int]] = field(default_factory=dict)
    # segment index -> statement index
    segment_to_statement: Dict[int, int] = field(default_factory=dict)

    def add_link(self, statement_index: int, segment_index: int) -> None:
        self.segment_to_statement[segment_index] = statement_index
        self.statement_to_segments.setdefault(statement_index, []).append(segment_index)
