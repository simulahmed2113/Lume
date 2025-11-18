# CNC Software - Current Implementation Snapshot

> This document describes the **current working state** of the CNC G-code
> viewer / simulator as of the "pre-NC-Viewer-refactor" milestone.
> 
> Future changes (especially large refactors inspired by NC Viewer) should
> treat this document as the reference for *what already works*.

---

## Overview

This project is a **Python desktop application** for viewing
CNC / PCB G-code.

The goals of the current implementation are:

- Import one or more `.nc` G-code files into a simple **Project**.
- Visualise the toolpaths in a 3D/2D **OpenGL viewer** with an XY grid and
  coloured axes (X = red, Y = green, Z = blue).
- Show and edit the G-code in a **text editor** panel.
- Maintain one-way sync from **editor selection** to **viewer
  segment highlight**.

Offline simulation, vertex picking, and other NC-Viewer-style features are
intentionally **not implemented** in this snapshot; the focus is a small,
robust foundation.

---

## Tech Stack & Dependencies

- **Language**: Python 3.x
- **GUI**: [PySide6] (Qt for Python)
- **3D Viewer**: [pyqtgraph] `GLViewWidget`
- **OpenGL**:
  - Indirectly via pyqtgraph's GL module.
- **Other**:
  - `numpy` (for GL arrays)
- **File formats**:
  - G-code / CNC programs with extension `.nc`
  - Some files may include FlatCAM-style headers/footers; these are kept as
    part of the source text.

Typical dependency install (adjust versions as needed):

```bash
pip install PySide6 pyqtgraph numpy
```

---

## High-Level Architecture

### Core Data Model

Located mainly in:

* `core/project_model.py`
* `core/gcode_model.py` (if present)

Key concepts:

* **Project**

  * Holds a project `name` and a list of `GCodeJob` instances.
* **GCodeJob**

  * Represents a single imported G-code file.
  * Important fields:

    * `name` - filename as shown in the UI.
    * `path` - optional filesystem path.
    * `original_source` - full G-code text as last parsed / imported.
    * `program` - parsed representation of the G-code (`GCodeProgram`).
    * `geometry` - `ToolpathGeometry`, a list of line segments for drawing.
    * `program_index` - `ProgramIndex`, mapping between statements and
      segments (used for editor↔viewer selection).
    * `offset_x`, `offset_y`, `offset_z` - per-job workpiece offsets used
      when generating the final Lume header (`G92` line).
    * `id` - unique identifier.
    * `visible` - checkbox state in Project tree.
    * `color` - base RGBA colour for this job in the viewer.

The data model is intentionally simple; advanced NC-Viewer-style
"movements list" and transform pipelines are **not implemented** in this
snapshot.

---

### Parsing & Geometry

Located mainly in:

* `core/gcode_parser.py`
* `core/geometry_builder.py`
* `core/supported_codes.py`
* `core/import_pipeline.py`

Responsibilities:

* **`gcode_parser.py`**

  * Parses raw G-code text into a `GCodeProgram`.
  * Handles:

    * modal coordinates (X/Y/Z carry over when omitted),
    * recognised motion codes (G0/G00, G1/G01),
    * supported G-codes listed in `supported_codes.py`.
  * Unsupported or unrecognised codes are kept in the source but may not
    generate geometry (see limitations).

* **`geometry_builder.py`**

  * Converts a `GCodeProgram` into:

    * `ToolpathGeometry` - flat list of line segments
      `Segment(start=(x0,y0,z0), end=(x1,y1,z1))`.
    * `ProgramIndex` - mapping:

      * `statement_to_segments: Dict[int, List[int]]`
      * `segment_to_statement: List[int]`
  * This mapping is critical for:

    * editor <-> viewer selection,
    * simulation line stepping.

* **`import_pipeline.py`**

  * Reads `.nc` files from disk.
  * Calls `parse_gcode` and `build_geometry_and_index`.
  * Constructs and returns `GCodeJob` with `source`, `program`, `geometry`,
    `program_index` filled.
  * Also provides `reparse_job(job, new_source)` to rebuild a job after
    edits in the G-code editor.

---

### UI / Application Layer

Located mainly in:

* `main.py`
* `app/main_window.py`
* `app/project_tree.py`
* `app/gcode_editor.py`
* `app/viewer.py`

Responsibilities:

* **`main.py`**

  * Standard Qt application setup.
  * Creates `MainWindow` and shows it.

* **`app/main_window.py`**

  * Top-level window:

    * Menus: File, Job, View, etc.
    * Dock widgets:

      * Project tree (left).
      * G-code editor (bottom).
      * Status bar (coordinate readout, etc.).
    * Central widget: 3D/2D viewer (`GCodeViewer`).
  * Connects menu actions to:

    * Import G-code,
    * Top view camera preset,
    * Apply G-code edits.

* **`app/project_tree.py`**

  * Tree view showing:

    * Project root node.
    * "G-code Jobs" group.
    * One item per job, with a checkbox for visibility.

* **`app/gcode_editor.py`**

  * Text editor for the G-code.
  * Shows the **final Lume G-code** for the job: header + body + footer
    generated via `core.lume_runtime.build_final_gcode(job)` using the
    current XYZ offsets.
  * "Apply G-code edits" button triggers `reparse_job(job, text)` in
    `import_pipeline.py` and refreshes viewer.

* **`app/viewer.py`**

  * Wraps a `pyqtgraph.opengl.GLViewWidget` inside `GCodeViewer`.
  * Renders toolpaths as GL line strips for each job using
    `job.geometry.segments` only.
  * Handles camera control (distance/orbit, top view) and approximate
    XY(Z) cursor readout via unprojection.
  * Exposes `highlight_segments(job, segment_indices)` for editor-driven
    selection highlighting.

---

## Data Flow

1. **File Import**

   * User chooses: *File -> Open G-code file...*
   * Each selected `.nc` file is passed to `import_gcode_file(path)`.

2. **Parsing & Geometry**

   * `import_gcode_file`:

     * Reads text.
     * `program = parse_gcode(text)`
     * `geometry, index = build_geometry_and_index(program)`
     * Creates `GCodeJob(source=text, program=program, geometry=geometry,
       program_index=index, ...)`.

3. **Project Integration**

   * `MainWindow` adds each `GCodeJob` to the current `Project`.
   * `ProjectTreeWidget` is updated to show new jobs under **G-code Jobs**.

4. **Viewer & Editor**

   * `GCodeViewer.set_project(project)` is called to rebuild geometry.
   * For each job:

     * GL line plot is built from `job.geometry.segments`.
   * When a job is selected in the tree:

     * `GCodeEditor.set_job(job)` shows the final Lume G-code for that job
       (header/body/footer with current offsets).

5. **Selection**

   * Editor line selection -> `ProgramIndex` -> segment indices ->
     viewer highlight via `GCodeViewer.highlight_segments(...)`.

---

## UI Layout & Interaction Model

### Main Window Layout

* **Left dock**: *Project* tree

  * Root: "Untitled Project".
  * Child: "G-code Jobs" group.
  * Under that: one item per imported `.nc` file, with checkbox.

* **Bottom dock**: *G-code Editor*

  * `QPlainTextEdit` showing the raw G-code.
  * Below it: a button *"Apply G-code edits"*.

* **Central area**: *G-code Viewer*

  * `GCodeViewer` (`GLViewWidget`) showing:

    * XY grid,
    * coordinate axes,
    * toolpaths coloured by job,
    * simulation overlays (head marker, visited path).

* **Status bar**:

  * Shows current mouse / cursor coordinates (X, Y, optionally Z).
  * May also show simple messages (simulation state, etc.).

* **View toolbar**:

  * Top-level toolbar with camera controls:
    * `Fit` - zoom-to-fit of all visible toolpaths based on their bounding box.
    * `Toggle` - switches between isometric 3D view and strict top-down XY view.

---

### Viewer Behaviour (3D & 2D)

**3D / Isometric View:**

* Camera:

  * Default elevation ~ 30-35 degrees.
  * Azimuth ~ 225 degrees (looking from negative X / negative Y towards the origin).
  * Distance based on scene size (via zoom-to-fit or manual zoom).
* Visuals:

  * Gray XY grid at Z=0.
  * X axis: red.
  * Y axis: green.
  * Z axis: blue.
  * Each job has its own base colour.

**Controls (current behaviour):**

* **Left mouse drag** - orbit / rotate camera (GLViewWidget default).
* **Right mouse drag** - (in some versions) may pan, but this is not fully
  standardised yet.
* **Mouse wheel** - zoom in/out (changes `distance`).
* **Right-click** - in 2D mode, used for picking a segment.

**Top View (2D):**

* Activated via View menu: *Top view (XY 2D)* or equivalent.
* Camera is oriented straight down:

  * Elevation ~ 90 degrees (looking along -Z).
* Grid aligns with XY plane.
* Hover highlight and pick logic treat Z as "ignored" and work in XY space.

---

### G-code Editor

* Displays the full `job.source` text.
* Edits are local to the text until *Apply G-code edits* is clicked.
* On *Apply*:

  * New text is passed to `reparse_job(job, new_source)`.
  * Job's `program`, `geometry`, `program_index` are rebuilt.
  * Viewer is refreshed; any geometry differences should be visible.

---

### Project Tree

* Each job item:

  * Checkbox toggles `job.visible`.
    The viewer respects this and hides/shows the job's geometry.
  * Selecting a job:

    * Sets it as "active job" for:

      * Editor content,
      * Simulation,
      * Some selection operations.

---

### Simulation Controls

* Available via a toolbar or menu in `MainWindow` (implementation details
  may vary, but the pattern is):

  * **Run / Play** - steps through program line by line with a timer.
  * **Pause** - stops stepping but keeps current state.
  * **Stop / Reset** - returns simulation to idle state.

Simulation visuals in the viewer:

* A **tool head marker** showing current tool position.
* **Visited path** coloured differently from unvisited segments.
* Current statement's segments may be highlighted (e.g. brighter colour).

During simulation:

* **Hover / picking is disabled** (by design, to avoid interference).
* Editor line tracking follows the simulation head.

---

## Current Behavior

This section uses "F#" IDs so future docs can reference specific features.

### F1 - G-code import & project model

* Import multiple `.nc` files via File menu.
* Each becomes a `GCodeJob` added to `Project`.
* Jobs appear in Project tree and viewer.
* Visibility can be toggled by checkbox.

### F2 - G-code editor & Apply

* Editor shows `job.source` for the selected job.
* Edits are applied via "Apply G-code edits" button.
* On apply:

  * Job is reparsed,
  * Geometry and indices are rebuilt,
  * Viewer updates.

### F3 - 3D viewer & grid

* XY grid at Z=0 with adaptive spacing (coarser when zoomed out).
* Colour axes (X red, Y green, Z blue).
* Toolpaths drawn as sets of line segments per job.
* Zoom via mouse wheel.

### F4 - Top view (2D)

* View menu option sets camera to look straight down.
* Grid still visible.
* XY plane represents the board; Z is mostly ignored for selection.
* Some panning/zoom behaviour exists; future work plans to stabilise:

  * Left / right drag semantics,
  * Zoom-to-fit function.

### F5 - Editor -> viewer selection

* When a line (or selection) in the G-code editor changes:

  * Using `ProgramIndex`, the app finds all segments associated with that
    statement or line.
  * These segments are highlighted in the viewer (e.g. yellow line overlay,
    thicker line, endpoints highlighted, etc.).
* Multi-line selections highlight the union of segments for those lines.

### F6 - Viewer -> editor selection (reverse pick)

* In 2D view, right-click near a segment:

  * The viewer finds the nearest segment in XY (within a threshold).
  * Using `ProgramIndex.segment_to_statement`, the corresponding statement
    index is retrieved.
  * Editor selects that line, and viewer highlights the associated segments.
* This is useful for finding the code that generated a specific path region.

### F7 - Hover highlight (small jobs)

* When hover is enabled and the job is not too large:

  * Moving the mouse near geometry shows a small highlight point near the
    nearest segment endpoint.
  * Hover is limited to **2D top view** to reduce confusion in 3D.
* Hover is automatically **disabled**:

  * while simulation is running,
  * or when geometry size exceeds a threshold (to avoid lag).

### F8 - Simulation (offline, no device)

* Simulation runs purely from parsed program & geometry:

  * For each step / tick:

    * Choose the next statement index.
    * Use `ProgramIndex` to find segments for that statement.
    * Update viewer:

      * Head marker position (end of last segment).
      * Colours for visited vs unvisited segments.
  * Editor scrolls/highlights the current statement.
* No GRBL / machine connection logic is included in this snapshot; this is
  purely a visual NC viewer.

---

## Edge Cases / Limitations

This list intentionally captures known issues so the next developer does not
treat them as bugs they "discovered".

1. **L1 - 2D panning not final**

   * In top view, panning by mouse drag is present but behaviour is not
     fully standardised;

2. **L2 - Zoom-to-fit incomplete**

   * There is not yet a fully robust "zoom to fit all geometry" function
     comparable to NC Viewer's `resetCamera()`.
     Some experiments exist but may require rework.

3. **L3 - Picking precision in dense areas**

   * Reverse pick (segment -> editor) uses distance in XY; in very dense
     areas it may select a neighbouring segment rather than the visually
     closest one.

4. **L4 - Coordinate overlay UI**

   * Mouse cursor coordinates are available via callbacks / status bar,
     but a FlatCAM-style permanent on-plot overlay (Dx, Dy, X, Y) is not
     yet implemented.

5. **L5 - Arcs & unsupported G-codes**

   * The current geometry builder focuses on linear moves 
     * approximated by upstream CAM into many small linear moves.
       This is acceptable for FlatCAM-style `.nc` files but should be
       documented if behaviour changes.

6. **L6 - Movement list not yet NC-Viewer style**

   * This snapshot does **not** have NC Viewer's unified `movements[]`
     structure; geometry and selection rely on `ToolpathGeometry +
     ProgramIndex`.
     Future work should introduce a movement list *alongside* these
     structures first, then migrate gradually.

7. **L7 - Sim / hover edge cases**

   * While simulation is running, hover is supposed to be fully disabled.
     Any behaviour where hover still triggers during sim should be
     considered a bug to fix, not a feature.

---

## Typical User Workflow

1. **Start application**

   * `python main.py`

2. **Import jobs**

   * `File -> Open G-code file...`
   * Select one or more `.nc` files.
   * Check they appear under "G-code Jobs" in the Project tree and are
     visible in the viewer.

3. **Inspect geometry**

   * Use isometric/3D view to get overall sense of the board.
   * Switch to Top view (XY 2D) for precise selection.

4. **Select and inspect lines**

   * Click in the editor -> highlight corresponding path segment(s).

5. **Edit G-code**

   * Modify coordinates or feed rates.
   * Click "Apply G-code edits" -> geometry recalculated -> inspect change.

---

## Directory / Module Reference

Quick reference for next developers:

``text
main.py                 - Qt app bootstrap; creates MainWindow.

app/
  main_window.py        - Main window, menus, docks.
  project_tree.py       - Project tree widget with job list & visibility.
  viewer.py             - GCodeViewer: OpenGL viewer, camera, selection.
  gcode_editor.py       - Plain text editor for job.source.

core/
  project_model.py      - Project and GCodeJob dataclasses.
  gcode_parser.py       - parse_gcode(text) -> GCodeProgram.
  geometry_builder.py   - build_geometry_and_index(program)
                           -> ToolpathGeometry + ProgramIndex.
  geometry.py           - Segment types and helpers (if separated).
  gcode_model.py        - Additional program/statement data structures.
  import_pipeline.py    - import_gcode_file(path), reparse_job(job, text).
  supported_codes.py    - List / helpers for supported G-codes.
``

Other files (e.g. requirement docs, NC Viewer reference HTML, etc.) live in
`docs/` or `tools/` as needed.

---

## Future Improvements & Guidance

This section is addressed directly to the next AI agent / developer who
takes over this project.

1. **Read the docs first**

   * Before changing code, read:

     * `docs/10_current-implementation.md` (this file)
     * `docs/11_requirements-overview.md` (updated spec, once created)
   * Do **not** assume the repo state matches your mental model until you
     cross-check with these docs.

2. **Do not rewrite from scratch**

   * Preserve:

     * `GCodeJob`, `Project`
     * `ToolpathGeometry`, `ProgramIndex`
     * `import_pipeline` behaviour
     * Main window layout and basic viewer/editor wiring.
   * Large refactors (e.g. introducing NC Viewer movement list,
     per-vertex colour buffers, custom controls) must be staged and
     confirmed with the human user.

3. **When designing a new feature**

   * First, summarise:

     * What you plan to change.
     * Which modules/files will be touched.
     * Which existing features (F1-F8 above) *might* be affected.
   * Wait for user confirmation before implementing.

4. **When delivering code changes**

   * Keep patches **small and focused** (one feature or bugfix at a time).
   * After each change, provide:

     * A list of **tests** the user should run, referencing the F# IDs above.
     * Any known side effects or limitations.

5. **NC Viewer reference**

   * Some future features should explicitly imitate NC Viewer:

     * Movement list / segment mapping.
     * Per-vertex colour buffer for visited/active segments.
     * Camera controls and zoom-to-fit behaviour.
   * When you borrow ideas from NC Viewer, briefly explain:

     * Which part of NC Viewer you mirrored.
     * How it maps onto this Python architecture.

6. **Always maintain selection & simulation mappings**

   * Whatever you change, preserve (or clearly replace) the chain:

     * `editor line <-> statement index <-> segments <-> viewer geometry`
   * This mapping is central to the user's workflow.

---

*End of `docs/10_current-implementation.md`.*

