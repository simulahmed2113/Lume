# Feature 08: Reference Point Detection

## Overview

Feature 08 focuses on drilling and tracking fiducial holes that feed into the
affine alignment workflow (Feature 07). It generates a small drill job,
captures the resulting machine coordinates, and stores them so the alignment
profile can compute accurate transforms.

## Current Behavior

- This workflow is not implemented; operators currently drill fiducials in CAM
  or by hand and manually note the coordinates.

## Requirements

### Drill Job Generation

- Allow users to pick 3-4 reference points directly from the viewer, then
  produce a dedicated drilling job that can be run immediately.
- Ensure drill depth, feed, and spindle settings are safe defaults because the
  holes will be used repeatedly.

### Coordinate Capture

- Provide a simple wizard that walks through each drilled hole so the operator
  can jog to it and record the actual machine coordinates.
- Store the design-space position alongside the measured machine-space values
  for use by Feature 07.

## Edge Cases / Limitations

- There is no single source of truth for fiducials, which makes it difficult to
  guarantee that both sides of a board reference the same points.
- Without a guided capture process it is easy to mix up the order of points,
  producing inverted or flipped transforms later.

## Future Improvements

1. Show a live indicator in the viewer for the currently selected fiducial so
   the operator confirms the right hole is being measured.
2. Allow exporting the fiducial set as part of the project state so the same
   references can be reused in future jobs.
