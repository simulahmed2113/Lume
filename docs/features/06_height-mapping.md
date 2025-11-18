# Feature 06: Height Mapping

## Overview

Feature 06 introduces the Z mesh / auto-leveling workflow. It records measured
surface heights across the work area and warps future cutting moves so the tool
maintains a consistent depth even if the PCB is bowed or tilted.

## Current Behavior

- The concept is designed but not implemented. The existing viewer and parser
  can hold the mesh data, yet no remapping is performed on outgoing movements.

## Requirements

### Mesh Acquisition

- Probe the board or import a mesh file that specifies Z offsets over a grid.
- Provide visual feedback showing which cells have been measured and whether
  the density is sufficient for the upcoming job.

### Toolpath Remapping

- Combine the base Z offset (Feature 01) with per-cell corrections to produce a
  new Z for every movement.
- Insert additional interpolation points when a segment crosses mesh boundaries
  so the controller receives smooth transitions.
- Keep XY coordinates untouched so alignment features (Feature 07) can run
  before or after height correction.

## Edge Cases / Limitations

- Without point-density checks it is easy to run with an undersampled mesh,
  leading to sudden jumps in the corrected toolpath.
- There is no preview that shows the warped geometry, making it hard for users
  to validate the interpolated depth.

## Future Improvements

1. Integrate the remapping logic from `docs/features/09_g-code-remapping.md`
   once it is production ready.
2. Add a mesh heat map overlay in the viewer so missing samples are obvious
   before cutting starts.
