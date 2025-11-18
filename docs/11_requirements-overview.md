
# CNC Software - Requirements Overview

This document is the **entry point** for new developers (or AI agents) working on the CNC desktop application. It summarizes:

- What the product is supposed to do.
- How it relates to the physical Cirqoid-style PCB machine.
- The major features and their dependencies.
- The intended architecture and external inspirations (NC Viewer, FlatCAM, Candle).

For detailed specs, see the per-feature documents in `docs/features/`.

---

## Overview

The application is a **G-code-first CNC controller and CAM helper** for a Cirqoid-style PCB milling machine. It combines:

- **FlatCAM-style project management** with multiple G-code "jobs" per project.
- **NC Viewer-style 2D/3D visualization and simulation** of toolpaths.
- A **line-by-line streaming engine** that talks to the controller over a serial port using its custom G-code dialect.
- A set of **advanced operations** (height mapping, realignment, resume-from-click, etc.) implemented primarily as **G-code transforms**.

The philosophy: **treat G-code as the primary editable artifact**, not just a by-product of CAM.  
The app should make G-code visible, understandable, and safely executable.

---

## Machine & Environment Constraints

The requirements are driven by the Cirqoid machine and its firmware.

### Axes and Workspace

- Machine has three axes: **X, Y, Z** (directions as in the Cirqoid manual).
- Typical travel limits (example values):
  - X: `0 .. 100 mm`
  - Y: `0 .. 220 mm`
  - Z: `+2 .. -18 mm`  
    - Z = 0 is on the PCB copper surface.  
    - Negative Z cuts into the board.
- **Software resolution** is ~1.25 um and repeatability better than 0.02 mm.  
  -> The viewer, snapping and picking logic must support at least **0.01 mm** precision.

### Supported G-code Dialect

The controller supports a **restricted G-code subset**, documented in:

- the Cirqoid machine manual, and
- the internal "Supported G-code" spec.

Key groups:

- Motion: `G0`, `G1`, `G2`, `G3`
- Dwell: `G4`
- Homing & coordinate systems: `G28`, `G53`, `G54`, `G92`
- Spindle & auxiliaries: `M3`, `M5`, `M7`, `M8`, `M9`

#### Accepted Structure of a Typical Job

Logically, each job looks like:

```gcode
; --- HEADER (preamble) ---

G28 Y0.835          ; Home / reference (must be sent before anything else)

G53                 ; Machine coordinates
G0 Z0               ; Safe Z in machine coordinates

; User-provided surface offset:
G92 X0 Y0 Z-10.2    ; Z value set at tool touching job surface
                    ; This Z offset may change later via on-the-fly Z adjustment.

G54                 ; Work coordinate system

G0 Z5               ; Move to safe Z above workpiece
S1390 M03           ; Spindle on with PWM 1390
G01 F300.00         ; Default feed
G00 Z5.0000         ; (example safe move)

; --- BODY (toolpath) ---

; All geometric motion commands (this is the part we plot & edit)
; G0 / G1 / G2 / G3 with X/Y/Z values

; --- FOOTER ---

; Retract, stop spindle, return home, etc.
; E.g. G0 Z5 / G28 / M5 / M9
````

Notes:

* **Header and footer** are managed by the application (Feature 15).
  The imported G-code "body" should generally be **geometry only**.
* **Z offset** (`G92 ... Z####`) is **per job** and must be asked from the user
  before sending code to the CNC.
  Later this will be related to Z mesh / height map adjustments:

  * base Z offset from user,
  * additional per-point Z correction from height mapping.

The application must:

* **Parse** and understand this dialect.
* **Ignore or clearly flag** unsupported codes.
* Never generate commands outside valid machine ranges (axis limits, spindle PWM, etc.).

### Communication Protocol

Global rules for talking to the machine:

* **Serial connection** over USB; the machine appears as a virtual COM port.

* **Strict line-by-line protocol**:

  > send one G-code line -> wait for `ok` / `nack` / `error` -> then send next

* **Command rate limit** of roughly **5-8 lines/sec**, configurable.

* Both **short** and **long** operation timeouts must be supported.

* **Retries** and clear error reporting belong to the streaming engine.

### Header & Footer

Every job sent to the machine must be wrapped with a **standard preamble and footer**.

**Header (preamble):**

* Home the machine (`G28` with appropriate Y compensation).
* Select machine / work coordinate systems (`G53`, `G54`, `G92` as needed).
* Move to safe Z.
* Ask the user for initial **Z offset** (if not already known), apply via `G92`.
* Set spindle speed with `M3 S####` (integer PWM).
* Turn spindle on and optionally dwell.

**Footer:**

* Retract to safe Z.
* Return to home or parking position.
* Turn spindle and auxiliaries off (`M5`, `M9`).

Header/footer injection is **centralized** (Feature 15) but must be respected by:

* importing,
* previewing,
* simulation, and
* streaming.

---

## Feature Map & Dependencies

The original FRD defines many features. This section summarizes the main ones, their dependencies, and their current approximate status.

Legend:

* **[ok] Implemented** (basic version)
* **[yellow] Partially implemented / prototype**
* **[ ] Not implemented yet**

> Status must be kept in sync with `docs/10_current-implementation.md`.

### Core Foundation

1. **Feature 1 - G-code Import & Parsing**
   **Status:** [yellow]
   Responsibilities:

   * Parse supported commands, maintain modal state, normalize coordinates, and build internal `GCodeProgram` structures.
   * Detect unsupported codes / syntax and report clearly.
   * Preserve the **G-code body** (geometry) while letting the application
     inject header & footer dynamically.
   * Before finalizing a job for simulation/streaming, **ask the user for
     Z offset** (per file) and:

     * apply it using `G92` in the preamble, or
     * adjust body Z values if needed (especially if on-the-fly Z or Z mesh
       will be applied later).
   * Provide the parsed result to:

     * geometry builder (for plotting),
     * streaming engine,
     * advanced transforms (height mapping, alignment, etc.).

2. **Feature 2 - 3D G-code Plotting / Viewer & Editor**
   **Status:** [yellow] (basic version working; several improvements pending)
   Responsibilities:

   * NC Viewer-style 3D/2D plotting with:

     * isometric 3D view,
     * top-down 2D view,
     * dynamic XY grid,
     * axis lines (X = red, Y = green, Z = blue).
   * FlatCAM-style UI:

     * project tree on the left,
     * central viewer,
     * G-code editor at bottom.
   * Synchronized editor <-> viewer interactions:

     * selecting lines in the editor highlights corresponding segments,
     * clicking in the viewer can select a line in the editor.
   * Continuous live coordinate readout for the mouse cursor (XY; Z if relevant).

   **Known missing / to-do:**

   * The viewer currently does **not mark every discrete point** (vertex) along
     the toolpath; we need:

     * explicit point visualization (e.g. small dots),
     * when the mouse is near one of these points in 2D, the point should
       highlight.
   * From the highlighted point, the app should:

     * know which G-code statement/line it came from, and
     * select that line in the editor.
   * Continuous cursor coordinates in the UI should always reflect the XY
     position of the crosshair in the plot area (even when moving).

3. **Feature 4 - Reliable Line-By-Line Streaming Engine**
   **Status:** [ ] (design only)
   Responsibilities:

   * Implement the strict send -> wait -> ack protocol.
   * Obey rate limits and timeouts.
   * Provide clear error handling and status reporting.
   * Expose events for:

     * live simulation ("line X confirmed executed"),
     * pause/resume,
     * emergency stop.

These three are the **foundation**: parsing, visualization, and robust streaming.

### Execution & Control

4. **Feature 3 - Live G-code Simulation (Synced With CNC)**
   **Status:** [yellow] (offline simulation logic exists; live sync with CNC not done)
   Responsibilities:

   * Drive a visual "tool head" along the path based on:

     * internal stepping (offline mode), or
     * real `ok` responses from the controller (online mode).
   * Colour the path based on state:

     * unvisited,
     * visited,
     * current active segment.
   * Disable hover/select while simulation is running.

5. **Feature 5 - Pause & Continue**
   **Status:** [ ]
   Responsibilities:

   * Safely pause streaming in the middle of a job.
   * Preserve controller modal state.
   * Resume without leaving marks or gouges.

6. **Feature 6 - On-The-Fly & Global Z Adjustment**
   **Status:** [ ]
   Responsibilities:

   * Apply global or incremental Z offset to **remaining** motions:

     * without regenerating full G-code from CAM,
     * using either `G92` updates or Z-modified motion commands.
   * Integrate cleanly with height map / Z mesh logic.

7. **Feature 7 - Resume From Click / Restart Anywhere**
   **Status:** [ ]
   Responsibilities:

   * Let the user click on a location in the viewer, then:

     * find the nearest movement / statement,
     * compute a safe resume preamble (moves, spindle, Z, etc.),
     * stream from that point as a new job.

8. **Feature 8 - Single Line / Range Execution**
   **Status:** [ ]
   Responsibilities:

   * Allow execution of a single line or a selected range from the editor.
   * Use the same streaming engine; ensure all safety checks still apply.

### Geometric Transforms & Calibration

9. **Feature 9 - Height Mapping / Auto-Leveling**
   **Status:** [ ]
   Responsibilities:

   * Probe or import a Z mesh over the board area.
   * Warp cutting paths so depth is uniform across warped or tilted boards.
   * Combine with base Z offset (Feature 1) and on-the-fly adjustments
     (Feature 6).

10. **Feature 10 - 3-Point Realignment / Affine Correction**
    **Status:** [ ]
    Responsibilities:

    * Use three (or more) corresponding fiducials (machine vs design) to
      compute a 2D affine transform (scale, rotation, translation, skew).
    * Apply this transform to all future toolpaths for a given job.

11. **Feature 11 - Reference Point Drilling**
    **Status:** [ ]
    Responsibilities:

    * Generate drilling jobs for reference / alignment holes.
    * Used by Feature 10 and double-sided PCB workflows.

### Optimization & Housekeeping

12. **Feature 19 - Project Save/Load (FlatCAM-like)**
    **Status:** [ ]
    Responsibilities:

    * Save project tree, file paths or embedded G-code, height maps,
      transforms, and resume points.
    * Reload projects reliably and restore viewer state.

13. **Feature 22 - Command Rate Limiting**
    **Status:** [ ]
    Responsibilities:

    * Central control for maximum lines/sec streaming rate.
    * Integrate with streaming engine timing and progress display.

14. **Feature 23 - Serial Logging & Diagnostics**
    **Status:** [ ]
    Responsibilities:

    * Log all serial traffic (commands and responses).
    * Provide both:

      * on-screen logs, and
      * persistent logs for debugging problems later.

---

## Intended Architecture

This section helps future developers map features to file structure quickly.

### Core Layers

1. **G-code model & parser (core)**
   Files: `gcode_parser.py`, `gcode_model.py`, `supported_codes.py`

   Responsibilities:

   * Tokenize and parse G-code text.
   * Maintain modal state and current units.
   * Validate against the supported dialect.
   * Expose `GCodeProgram` structures consumed by all other modules.

2. **Geometry builder & viewer**
   Files: `geometry_builder.py`, `geometry.py`, `viewer.py`

   Responsibilities:

   * Convert `GCodeProgram` into **movement segments** with X/Y/Z and links
     back to source statements.
   * Provide batched line geometry and colour buffers to the PyQtGraph
     3D/2D view.
   * Provide picking and coordinate readout in both 2D and 3D modes.

3. **Project model & import pipeline**
   Files: `project_model.py`, `import_pipeline.py`

   Responsibilities:

   * Manage the project tree of **G-code jobs** (imported, edited, transformed).
   * Support multiple files per project.
   * Run `file -> parse -> build geometry` with robust error reporting.

4. **UI shell & tools**
   Files: `main_window.py`, `project_tree.py`, `gcode_editor.py`

   Responsibilities:

   * Provide FlatCAM-style layout: project tree (left), viewer (center), editor (bottom).
   * Wire menus/toolbars: import, view modes, simulation controls, streaming controls.
   * Coordinate selection and focus between tree, viewer, and editor.

5. **Streaming & machine interface** (future)
   Planned files: `streaming_engine.py`, `serial_client.py`, `machine_state.py`

   Responsibilities:

   * Implement Features 3-8, 15, 21-23 (actual CNC control).
   * Provide events & state updates to:

     * the viewer (for live simulation),
     * the UI (for progress, errors, E-stop).

### Unified Movement List

Architectural direction (NC Viewer-style):

* Maintain a **central movement list** per job.

Each movement should store:

* start X/Y/Z
* end X/Y/Z
* motion type (rapid, feed, arc, etc.)
* link to:

  * statement index in `GCodeProgram`,
  * original G-code line number.

**All** visualization, selection, simulation, and resume-from-click logic should eventually rely on this movement list instead of re-parsing each time.

---

## External Inspirations & UX Targets

### NC Viewer

We intentionally copy several behaviours from **NC Viewer**:

* **3D isometric view** with grid floor and colour-coded toolpaths.
* **Isometric zoom-to-fit** based on the toolpath bounding box.
* **Segment picking -> G-code line mapping**:

  * click in viewer selects the corresponding line,
  * selecting a line highlights its segments.
* **Simulation colouring**:

  * Unvisited segments: base feed/rapid colours.
  * Visited segments: "completed" colour.
  * Current active segment: highlighted "active" colour.

Developers should consult `NCviewer.html` for implementation ideas, but **port concepts, not JavaScript code**.

### FlatCAM

From **FlatCAM**, we borrow:

* Project layout (tree at left, plot center, editor/log at bottom).
* Continuous **mouse coordinate readout** in status bar.
* 2D zooming & panning behaviour, including a grid that becomes finer as you zoom in.

### Candle

Another important inspiration is **Candle** (popular GRBL G-code sender):

We want to learn and copy techniques from Candle for features that match our requirements, especially:

* 3-point reference transformation / workpiece alignment.
* Z mesh leveling / probing workflows.
* Jog control and manual movement UI.
* The feel of its real-time view + machine control integration.

When a feature overlaps with Candle's functionality, developers should:

* Study how Candle solves it,
* Adapt the approach to this project's architecture and G-code dialect.

### Cirqoid Manual

The **Cirqoid machine manual** is the authoritative reference for:

* Axis conventions and travel limits.
* Supported G-code dialect and parameter semantics.
* Safety requirements (E-stop behaviour, compressed air, vacuum, etc.).

Any behaviour that sends commands **must** be checked against these constraints.

---

## Future Improvements

This is a **recommended development order**, assuming basic Feature 1 and Feature 2 support already exists.

1. **Stabilize Feature 1 & Feature 2**

   * Harden the parser & viewer pipeline on real sample files.
   * Finish picking, point highlighting, cursor coordinate readout, and editor synchronization.

2. **Introduce unified movement list & NC Viewer-style rendering**

   * Build a movement list per job.
   * Refactor viewer to rely on a single batched geometry per job with per-vertex colour buffers.
   * Implement simulation colouring via colour buffer updates.

3. **Build the streaming engine (Feature 4)**

   * Implement serial client, rate limiting, timeouts, error handling.
   * Expose events suitable for live simulation and pause/resume.

4. **Add live CNC-synced simulation (Feature 3)**

   * Link streaming events with viewer head position and visited path colours.
   * Ensure hover/select is disabled during playback.

5. **Pause/continue and safe resume (Features 5-7, 8)**

   * Implement Z offset adjustments, resume-from-click, and range execution.
   * Reuse the movement list and program indices for safety checks.

6. **Calibration transforms & CAM helpers (Features 9-12)**

   * Implement height map, affine alignment, mirroring, and reference drilling.
   * Reuse movement list + transforms instead of regenerating G-code from scratch.

Each of these steps should update:

* the relevant feature doc in `docs/features/`,
* this overview file, and
* `docs/10_current-implementation.md`,

so that docs and code stay synchronized.

