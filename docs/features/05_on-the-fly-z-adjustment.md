# Feature 05: On-the-Fly Z Adjustment

## Overview

Feature 05 covers both global and incremental Z offsets that can be applied
after a job has been imported. It manipulates Z values without regenerating the
entire program, so users can compensate for tool changes or surface drift while
the rest of the job stays intact.

## Current Behavior

- The workflow is not implemented; Z offsets are still baked into the
  preamble/header when the user edits the file manually.

## Requirements

### Adjustment Modes

- Allow a one-shot global offset (e.g. re-zeroing after a tool change) that
  applies to all remaining movements.
- Apply incremental, per-command corrections - typically via refreshed `G92`
  statements or by adjusting the next motion command directly.

### Integration Points

- Cooperate with the height-map logic (Feature 06) so only one component owns
  the final Z correction passed to the controller.
- Ensure any runtime change updates the data structures shared with the viewer,
  simulation, and streaming engine.

## Edge Cases / Limitations

- There is no UI yet for confirming how much Z is being added, making accidental
  offsets likely.
- The system does not currently track whether a mid-job adjustment has already
  been sent to the controller; redo/undo flows are undefined.

## Future Improvements

1. Provide a dedicated dialog that previews the adjusted Z values before the
   update is streamed.
2. Record the adjustment in the project history so it can be reapplied when the
   job is reloaded.
