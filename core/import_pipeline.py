from __future__ import annotations

from pathlib import Path
from typing import Tuple

from core.gcode_parser import parse_gcode, GCodeProgram
from core.geometry_builder import build_geometry_and_index, ToolpathGeometry
from core.geometry import ProgramIndex
from core.project_model import GCodeJob


def _build_for_source(source: str) -> Tuple[GCodeProgram, ToolpathGeometry, ProgramIndex]:
    """
    Parse raw G-code text and build geometry + index.

    No optimisation, no header/footer, just:
    text -> GCodeProgram -> ToolpathGeometry + ProgramIndex
    """
    program = parse_gcode(source)
    geometry, index = build_geometry_and_index(program)
    return program, geometry, index


def import_gcode_file(path: Path) -> GCodeJob:
    """Read a .nc file and return a fully-populated GCodeJob."""
    source = path.read_text(encoding="utf-8", errors="ignore")
    program, geometry, index = _build_for_source(source)

    job = GCodeJob(
        name=path.name,
        path=path,
        original_source=source,
        program=program,
        geometry=geometry,
        program_index=index,
    )
    return job


def reparse_job(job: GCodeJob, new_source: str) -> None:
    """
    Re-parse a job after editing in the G-code editor.
    This regenerates program, geometry and index in-place.
    """
    program, geometry, index = _build_for_source(new_source)

    job.original_source = new_source
    job.program = program
    job.geometry = geometry
    job.program_index = index
