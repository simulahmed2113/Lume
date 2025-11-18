# Feature 02: Viewer & Editor

## Overview

Feature 02 defines the NC Viewer-style plotting surface and the FlatCAM-inspired
layout for inspecting projects. It covers the 3D and 2D visualisations,
continuous coordinate readout, and the editable G-code panel that stays in sync
with whatever is shown in the viewer.

## Current Behavior

- The current build already draws imported toolpaths in both 3D isometric and
  top-down views, including the dynamic XY grid and RGB axis helpers.
- The project tree, viewer canvas, and editor panel follow a FlatCAM-like
  arrangement that keeps related controls grouped together.
- Selecting code in the editor highlights the matching segments in the viewer,
  and clicking visible geometry can focus the corresponding text line.

## Requirements

### Visualization

- Maintain both an NC Viewer-style 3D viewport and a precise 2D projection.
- Keep the XY grid responsive to zoom level and show clear axis indicators
  (X = red, Y = green, Z = blue).
- Display a continuous XY coordinate readout for the mouse cursor.

### UI Integration

- Keep the project tree, viewer, and G-code editor arranged so users can drag
  between jobs while seeing the live drawing.
- Ensure the structure mirrors the workflow described in `docs/10_current-implementation.md`.

### Interaction & Mapping

- Selecting a line in the editor must always highlight its segments in the
  viewer, even across multiple jobs.
- Picking geometry in the viewer should focus the matching line in the editor,
  using the shared program index supplied by Feature 01.
- Hover, selection, and snapping logic must behave identically in both 3D and 2D
  modes so that resume-from-click and per-point operations remain predictable.

## Edge Cases / Limitations

- Vertices are not yet rendered as discrete points, so per-point snapping and
  highlighting remain approximate.
- Mouse coordinate readout sometimes lags behind cursor motion in dense jobs;
  this needs tuning before live streaming reuses the same signals.

## Future Improvements

1. Render individual toolpath points (e.g. small dots) so hover feedback can
   target exact locations and feed back into the editor.
2. Finish the always-on coordinate readout so the user can rely on it when
   jogging or selecting resume positions.
3. Harden the selection mapping so it stays robust once live simulation (Feature
   03) temporarily disables hover/select states.
