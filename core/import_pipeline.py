from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from core.gcode_parser import parse_gcode, GCodeProgram
from core.geometry_builder import build_geometry_and_index, ToolpathGeometry
from core.geometry import ProgramIndex, Movement, SegmentType, Point3D
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


def _build_movements_and_vertices(
    program: GCodeProgram,
    geometry: ToolpathGeometry,
    index: ProgramIndex,
) -> Tuple[List[Movement], List[Point3D]]:
    movements: List[Movement] = []
    vertices: List[Point3D] = []

    for seg_index, seg in enumerate(geometry.segments):
        stmt_index = index.segment_to_statement.get(seg_index, -1)
        if stmt_index < 0 or stmt_index >= len(program.statements):
            continue

        stmt = program.statements[stmt_index]
        cmd = (stmt.command or "").upper()

        if cmd in ("G0", "G00"):
            seg_type = SegmentType.RAPID
        elif cmd in ("G1", "G01"):
            seg_type = SegmentType.LINEAR
        elif cmd in ("G2", "G02"):
            seg_type = SegmentType.ARC_CW
        elif cmd in ("G3", "G03"):
            seg_type = SegmentType.ARC_CCW
        else:
            # Non-motion statements should not usually produce segments,
            # but fall back to LINEAR if they do.
            seg_type = SegmentType.LINEAR

        mv = Movement(
            index=len(movements),
            statement_index=stmt_index,
            start=seg.start,
            end=seg.end,
            segment_type=seg_type,
        )
        movements.append(mv)

        vertices.append(seg.start)
        vertices.append(seg.end)

    return movements, vertices


def import_gcode_file(path: Path) -> GCodeJob:
    """Read a .nc file and return a fully-populated GCodeJob."""
    source = path.read_text(encoding="utf-8", errors="ignore")
    program, geometry, index = _build_for_source(source)
    movements, vertices = _build_movements_and_vertices(program, geometry, index)

    job = GCodeJob(
        name=path.name,
        path=path,
        original_source=source,
        program=program,
        geometry=geometry,
        program_index=index,
    )
    job.movements = movements
    job.vertices = vertices
    return job


def reparse_job(job: GCodeJob, new_source: str) -> None:
    """
    Re-parse a job after editing in the G-code editor.
    This regenerates program, geometry, index, movements and vertices in-place.
    """
    program, geometry, index = _build_for_source(new_source)
    movements, vertices = _build_movements_and_vertices(program, geometry, index)

    job.original_source = new_source
    job.program = program
    job.geometry = geometry
    job.program_index = index
    job.movements = movements
    job.vertices = vertices
