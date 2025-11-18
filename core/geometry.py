from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Tuple


class SegmentType(Enum):
    """Type of toolpath segment used by the unified movement model."""

    RAPID = auto()
    LINEAR = auto()
    ARC_CW = auto()
    ARC_CCW = auto()


Point3D = Tuple[float, float, float]


@dataclass
class Movement:
    """
    Single logical tool movement in 3D space.

    This is the unified representation used for picking, simulation,
    and future transforms. Arcs are represented as one or more
    movements referencing the original statement_index.
    """

    index: int
    statement_index: int  # index into GCodeProgram.statements
    start: Point3D
    end: Point3D
    segment_type: SegmentType


@dataclass
class PathSegment:
    """Low-level line segment between two 3D points."""

    index: int
    start: Point3D
    end: Point3D
    segment_type: SegmentType


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
