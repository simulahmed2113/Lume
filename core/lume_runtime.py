from __future__ import annotations

from core.gcode_processor import process_gcode_file
from core.project_model import GCodeJob


HEADER_TEMPLATE = """G53
G0 Z0
G0 X0 Y0
G92 X{offset_x:.2f} Y{offset_y:.2f} Z{offset_z:.2f}
G54
G0 Z5.0
S13900 M3
G4 P2.5
"""

FOOTER_TEMPLATE = """G53
G0 Z0
M5
"""


def build_final_gcode(job: GCodeJob) -> str:
    """
    Build the final Lume G-code for a job by:

    - taking the imported source,
    - extracting the geometric body (stripping existing header/footer),
    - wrapping it with the Lume HEADER_TEMPLATE / FOOTER_TEMPLATE,
    - and inserting the current XYZ offsets into the G92 command.
    """
    source = job.original_source or ""
    processed = process_gcode_file(source)
    body = "\n".join(processed.body_lines)

    header = HEADER_TEMPLATE.format(
        offset_x=job.offset_x,
        offset_y=job.offset_y,
        offset_z=job.offset_z,
    )

    parts = [header]
    if body:
        parts.append(body)
    parts.append(FOOTER_TEMPLATE)

    return "\n".join(part.rstrip("\n") for part in parts if part)
