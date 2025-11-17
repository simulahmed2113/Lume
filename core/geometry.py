from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Tuple


class SegmentType(Enum):
    """Type of toolpath segment, used for colouring / future filtering."""

    RAPID = auto()
    LINEAR = auto()
    ARC_CW = auto()
    ARC_CCW = auto()


Point3D = Tuple[float, float, float]


@dataclass
class PathSegment:
    """Single toolpath segment between two 3D points."""

    index: int
    job_id: str
    statement_index: int  # index into GCodeProgram.statements
    start: Point3D
    end: Point3D
    segment_type: SegmentType = SegmentType.LINEAR


@dataclass
class GeometryData:
    """All segments for a given GCodeProgram / job."""

    segments: List[PathSegment] = field(default_factory=list)


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
