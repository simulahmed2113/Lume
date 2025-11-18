# Feature 04: Streaming Engine

## Overview

Feature 04 implements the strict line-by-line protocol used by the Cirqoid
controller. It sends exactly one command at a time, waits for an `ok`, `nack`,
or `error`, and only then proceeds. Everything related to machine I/O, rate
limiting, and retries belongs here.

## Current Behavior

- The design for this engine exists in `docs/11_requirements-overview.md`, but
  no production-ready code has been committed.
- Simulation and preview run offline, so there is no dependency on serial I/O
  yet.

## Requirements

### Protocol Handling

- Enforce the controller contract: send a single G-code line, wait for the
  response, then continue or retry.
- Apply configurable rate limiting (5-8 lines per second by default) and expose
  timeouts for both short and long-running commands.
- Surface clear status messages or errors so the UI can alert the user and stop
  playback safely.

### Event Hooks

- Emit granular events that Feature 03 can use to keep the simulated head in
  sync (e.g. "line X acknowledged").
- Provide pause, resume, and emergency stop hooks for higher-level workflow
  features.
- Keep consistent program-to-response mapping so resume-from-click and range
  execution can reuse the same state machine.

## Edge Cases / Limitations

- Right now there are no retries, so any serial hiccup would halt execution
  without guidance.
- Timeouts are not yet user-configurable, making it impossible to adapt to
  slower operations like probing.

## Future Improvements

1. Implement a pluggable serial client with fault injection hooks, so the UI can
   be tested without hardware.
2. Add structured error reporting that captures the offending line, modal state,
   and suggested recovery actions.
