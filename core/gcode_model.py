from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional


class Units(Enum):
    MM = "mm"
    INCH = "inch"


class DistanceMode(Enum):
    ABSOLUTE = "G90"
    RELATIVE = "G91"


class CommandType(Enum):
    MOTION = auto()
    MODE_CHANGE = auto()
    SPINDLE = auto()
    DWELL = auto()
    COMMENT = auto()
    OTHER = auto()
    UNSUPPORTED = auto()


@dataclass
class ModalState:
    """Represents the modal G-code state at a particular point in the program.

    This is intentionally minimal for Feature 1; we will extend it for
    later features (planes, coolant, etc.).
    """

    units: Units = Units.MM
    distance_mode: DistanceMode = DistanceMode.ABSOLUTE
    wcs: str = "G54"
    feed_rate: Optional[float] = None
    spindle_on: bool = False
    spindle_speed: Optional[float] = None

    # Effective tool position in mm (absolute in machine space)
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class GCodeImportWarning:
    """Represents an issue found during G-code import that the user should see."""

    line_number: int
    message: str


@dataclass
class GCodeStatement:
    """Parsed representation of a single line of G-code, including its modal context."""

    line_number: int
    raw_text: str
    words: Dict[str, float] = field(default_factory=dict)
    comment: str | None = None
    command_type: CommandType = CommandType.OTHER
    g_code: Optional[str] = None
    m_code: Optional[str] = None
    is_supported: bool = True
    warnings: List[str] = field(default_factory=list)

    # Effective coordinates in mm after applying modal state
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None


@dataclass
class GCodeMetadata:
    """Aggregate metadata for a G-code program."""

    min_x: Optional[float] = None
    max_x: Optional[float] = None
    min_y: Optional[float] = None
    max_y: Optional[float] = None
    min_z: Optional[float] = None
    max_z: Optional[float] = None
    line_count: int = 0
    motion_count: int = 0

    def update_bounds(self, x: Optional[float], y: Optional[float], z: Optional[float]) -> None:
        if x is not None:
            self.min_x = x if self.min_x is None else min(self.min_x, x)
            self.max_x = x if self.max_x is None else max(self.max_x, x)
        if y is not None:
            self.min_y = y if self.min_y is None else min(self.min_y, y)
            self.max_y = y if self.max_y is None else max(self.max_y, y)
        if z is not None:
            self.min_z = z if self.min_z is None else min(self.min_z, z)
            self.max_z = z if self.max_z is None else max(self.max_z, z)


@dataclass
class GCodeProgram:
    """Full representation of a G-code file with statements and metadata."""

    statements: List[GCodeStatement]
    modal_states: List[ModalState]
    metadata: GCodeMetadata
    import_warnings: List[GCodeImportWarning] = field(default_factory=list)
