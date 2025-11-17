from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
import uuid

from core.gcode_parser import GCodeProgram
from core.geometry_builder import ToolpathGeometry, ProgramIndex


Color = Tuple[float, float, float, float]


@dataclass
class GCodeJob:
    """
    Single imported G-code job.

    Fields are deliberately simple so we can mutate them in-place after
    editing G-code in the editor (reparse_job).
    """

    name: str
    path: Optional[Path] = None

    # Full text of the G-code file (as originally imported / last edited)
    original_source: str = ""

    # Parsed program + derived geometry
    program: Optional[GCodeProgram] = None
    geometry: Optional[ToolpathGeometry] = None
    program_index: Optional[ProgramIndex] = None

    # UI / project metadata
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    visible: bool = True
    color: Color = (0.9, 0.9, 0.9, 1.0)

    def display_name(self) -> str:
        """Text used in the Project tree."""
        return self.name


@dataclass
class Project:
    """
    Very small project model: just a name + a list of jobs.
    """

    name: str
    jobs: List[GCodeJob] = field(default_factory=list)

    def add_job(self, job: GCodeJob) -> None:
        """
        Add a job to the project and assign it a colour from a small palette.
        """
        palette: List[Color] = [
            (0.1, 0.7, 1.0, 1.0),  # cyan-blue
            (1.0, 0.6, 0.1, 1.0),  # orange
            (0.4, 1.0, 0.4, 1.0),  # green
            (1.0, 0.4, 0.8, 1.0),  # pink
            (1.0, 1.0, 0.3, 1.0),  # yellow
        ]
        idx = len(self.jobs) % len(palette)
        job.color = palette[idx]
        self.jobs.append(job)

    def get_job_by_id(self, job_id: str) -> Optional[GCodeJob]:
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None
