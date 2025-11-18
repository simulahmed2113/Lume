# core/geometry_builder.py
#
# Build simple toolpath geometry from parsed G-code WITHOUT
# any optimisation, rounding or simplification.
#
# - Every motion command (G0/G00, G1/G01, G2/G02, G3/G03) becomes
#   one or more segments, in order.
# - Linear moves (G0/G1) -> 1 segment.
# - Arcs (G2/G3) -> small linear segments along the arc.
#
# This geometry is what the viewer uses for drawing. The idea is:
# if the G-code already approximates arcs with lots of small moves,
# we just draw those moves directly and don't touch them.

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import math

from core.gcode_parser import GCodeProgram, GCodeStatement
from core.geometry import ProgramIndex


Point3D = Tuple[float, float, float]


@dataclass
class ToolpathSegment:
    start: Point3D
    end: Point3D


@dataclass
class ToolpathGeometry:
    segments: List[ToolpathSegment]


# ---------------------------------------------------------------------------


def build_geometry_and_index(
    program: GCodeProgram,
    *,
    arc_subdiv_max_angle_deg: float = 10.0,
) -> Tuple[ToolpathGeometry, ProgramIndex]:
    """
    Convert a parsed GCodeProgram into ToolpathGeometry + ProgramIndex.

    IMPORTANT:
    - We DO NOT simplify or merge segments.
    - We DO NOT round coordinates.
    - For linear moves we produce exactly one segment per statement.
    - For arcs we interpolate with small segments using center mode (I/J).
    """

    segments: List[ToolpathSegment] = []
    stmt_to_segs: Dict[int, List[int]] = {}
    seg_to_stmt: Dict[int, int] = {}

    # Simple modal state: absolute vs relative; position in XYZ.
    absolute = True  # assume G90 by default
    x, y, z = 0.0, 0.0, 0.0

    # XY-plane arcs (G17) only – which is what your PCB files use.
    for stmt_index, stmt in enumerate(program.statements):
        cmd = stmt.command.upper() if hasattr(stmt, "command") else ""
        params = getattr(stmt, "params", {})  # dict like {"X":..., "Y":..., "I":...}

        if cmd in ("G90",):  # absolute
            absolute = True
            continue
        if cmd in ("G91",):  # incremental
            absolute = False
            continue

        # Position updates: figure target XYZ from modal state + params
        def get_target(
            cur_x: float, cur_y: float, cur_z: float
        ) -> Point3D:
            tx = cur_x
            ty = cur_y
            tz = cur_z

            if "X" in params:
                tx = (
                    cur_x + float(params["X"])
                    if not absolute
                    else float(params["X"])
                )
            if "Y" in params:
                ty = (
                    cur_y + float(params["Y"])
                    if not absolute
                    else float(params["Y"])
                )
            if "Z" in params:
                tz = (
                    cur_z + float(params["Z"])
                    if not absolute
                    else float(params["Z"])
                )

            return tx, ty, tz

        # -------------------------- linear / rapid ---------------------
        if cmd in ("G0", "G00", "G1", "G01"):
            nx, ny, nz = get_target(x, y, z)
            if (nx, ny, nz) != (x, y, z):
                seg_index = len(segments)
                seg = ToolpathSegment(start=(x, y, z), end=(nx, ny, nz))
                segments.append(seg)
                stmt_to_segs.setdefault(stmt_index, []).append(seg_index)
                seg_to_stmt[seg_index] = stmt_index
            x, y, z = nx, ny, nz
            continue

        # ----------------------------- arcs ----------------------------
        if cmd in ("G2", "G02", "G3", "G03"):
            # Very common in PCB isolation routes.
            # We assume XY-plane arcs using I,J offsets (centre mode).
            nx, ny, nz = get_target(x, y, z)
            cw = cmd in ("G2", "G02")

            # Default: no movement if we don't have enough info
            if ("I" not in params and "J" not in params) or (nx == x and ny == y):
                # Fallback: treat as straight line
                seg_index = len(segments)
                seg = ToolpathSegment(start=(x, y, z), end=(nx, ny, nz))
                segments.append(seg)
                stmt_to_segs.setdefault(stmt_index, []).append(seg_index)
                seg_to_stmt[seg_index] = stmt_index
                x, y, z = nx, ny, nz
                continue

            cx = x + float(params.get("I", 0.0))
            cy = y + float(params.get("J", 0.0))

            # radii (for sanity, but not enforced hard)
            rs = math.hypot(x - cx, y - cy)
            re = math.hypot(nx - cx, ny - cy)
            r = (rs + re) * 0.5 if (rs > 0 and re > 0) else max(rs, re)

            # start and end angles
            ang0 = math.atan2(y - cy, x - cx)
            ang1 = math.atan2(ny - cy, nx - cx)

            # sweep
            if cw:
                if ang1 >= ang0:
                    ang1 -= 2.0 * math.pi
            else:
                if ang1 <= ang0:
                    ang1 += 2.0 * math.pi

            sweep = ang1 - ang0  # signed
            total_angle = abs(sweep)

            # number of segments based on max angle per segment
            max_ang = math.radians(max(1.0, min(arc_subdiv_max_angle_deg, 45.0)))
            steps = max(2, int(math.ceil(total_angle / max_ang)))

            last_x, last_y, last_z = x, y, z

            for i in range(1, steps + 1):
                t = i / steps
                theta = ang0 + sweep * t
                px = cx + r * math.cos(theta)
                py = cy + r * math.sin(theta)
                pz = z + (nz - z) * t  # simple linear Z along arc

                seg_index = len(segments)
                seg = ToolpathSegment(
                    start=(last_x, last_y, last_z),
                    end=(px, py, pz),
                )
                segments.append(seg)
                stmt_to_segs.setdefault(stmt_index, []).append(seg_index)
                seg_to_stmt[seg_index] = stmt_index

                last_x, last_y, last_z = px, py, pz

            x, y, z = nx, ny, nz
            continue

        # Everything else: ignore for geometry (feeds, units, etc.)

    geometry = ToolpathGeometry(segments=segments)
    index = ProgramIndex(
        statement_to_segments=stmt_to_segs,
        segment_to_statement=seg_to_stmt,
    )
    return geometry, index
