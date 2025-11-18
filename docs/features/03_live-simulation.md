# Feature 03: Live Simulation

## Overview

Feature 03 bridges the viewer with the CNC controller so the simulated tool head
matches the real machine. It extends the offline simulation in `docs/10_current-implementation.md`
to respond to acknowledgements from the streaming engine and keeps the colour
state of every segment accurate in both modes.

## Current Behavior

- Offline stepping already walks the tool head through the parsed movement list
  and colours visited paths.
- Live synchronisation against controller responses has not been completed, so
  the simulation currently runs only in standalone mode.
- Hover/select interactions are manually disabled during playback to avoid
  conflicting highlights.

## Requirements

### Simulation Control

- Advance the tool head using either the internal stepper (offline) or by
  listening to `ok` acknowledgements emitted by Feature 04.
- Update segment colours to reflect unvisited, active, and completed states in a
  way that matches NC Viewer expectations.

### Interaction Rules

- Suspend hover and selection while playback runs; restore the previous state
  immediately after it pauses or completes.
- Provide hooks so resume-from-click (Feature 07) can safely query the last
  executed statement and the controller modal state.

## Edge Cases / Limitations

- There is no debounce logic for rapid pause/resume cycles yet, so user inputs
  can momentarily desync the simulated head.
- Because live sync is incomplete, there is not yet a way to visualise queued
  lines that the controller has not acknowledged.

## Future Improvements

1. Wire the simulation clock to the streaming engine so colour changes reflect
   the actual machine timing, not only the offline stepper.
2. Provide status callbacks so other features (e.g. pause/continue, resume from
   click) can query the currently executing movement without re-parsing the file.
