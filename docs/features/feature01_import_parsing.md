
````markdown
# Feature 1 – G-code Import & Parsing

## 1. Summary

Feature 1 is responsible for getting G-code **into** the application and turning
it into a structured, machine-aware model that everything else can use:

- Project / job management.
- 2D/3D plotting.
- Simulation and streaming.
- Higher-level transforms (Z mesh, affine realignment, etc.).

Its job is to:

1. Read one or more `.nc` files.
2. Validate and parse the content according to the Cirqoid dialect.
3. Separate concerns between:
   - **Header / footer** (managed by the application) and
   - **Body** (the geometric movements coming from CAM).
4. Build a `GCodeProgram` + geometry/indices that downstream features can use.

It **does not** talk to the machine directly and should not contain any
serial-communication logic.

---

## 2. Goals & User Stories

### 2.1 Goals

- Make it easy and safe to load G-code from FlatCAM or other CAM tools.
- Give users a clear view of:
  - what commands are understood,
  - where there are problems or unsupported codes.
- Provide a clean, consistent internal representation that:
  - is easy to simulate,
  - can be transformed (Z mesh, affine, mirror),
  - can be streamed line-by-line safely.

### 2.2 User stories

1. **Load PCB milling job**

   > As a user, I want to load one or more `.nc` files (drill, mill, outline)
   > into a project so I can see them in the viewer, inspect the code, and run
   > them later.

2. **See if my G-code is valid for this machine**

   > As a user, I want to see any problems or unsupported codes at import time,
   > so I know if the job is safe to run on my Cirqoid-style machine.

3. **Set Z offset per job**

   > As a user, for each job I want to specify the tool Z offset (where the bit
   > touches the board surface) before running, so the application can generate
   > correct `G92`/Z values for the machine without me editing the file by hand.

4. **Keep my original G-code**

   > As a user, I want the original G-code file content preserved so I can
   > compare, re-export, or re-import without losing what the CAM generated.

---

## 3. Scope

### 3.1 In scope

- Import of G-code files with extension `.nc`.
- Parsing of supported G-code dialect (subset defined by Cirqoid + “Supported G-code” doc).
- Storage of:
  - raw source text,
  - parsed program (`GCodeProgram`),
  - line → statement index mapping.
- Detection and reporting of:
  - syntax errors,
  - unsupported commands,
  - suspicious patterns.
- Per-job configuration of **Z surface offset** (to feed into header/preamble).
- Preparing parsed data for:
  - geometry builder,
  - viewer,
  - streaming engine and transforms.

### 3.2 Out of scope

- Header/footer generation itself (Feature 15 – implemented elsewhere).
- Serial communication or streaming (Feature 4+).
- UI layout (handled by main window / project tree / editor).

---

## 4. Dependencies

- **Machine dialect & safety**
  - Cirqoid manual (axes, limits, supported codes).
  - Internal “Supported G-code” table.

- **Core modules**
  - `gcode_parser.py`
  - `gcode_model.py`
  - `supported_codes.py`
  - `geometry_builder.py` (consumes parser output)
  - `project_model.py`
  - `import_pipeline.py`

- **UI modules**
  - `main_window.py` (menu actions)
  - `project_tree.py` (jobs)
  - `gcode_editor.py` (shows `job.source`)

---

## 5. Functional Requirements

### 5.1 File import

1. The app must be able to open `.nc` files from:
   - menu: **File → Open G-code file…**
   - drag-and-drop (future enhancement, optional).

2. Multiple files can be selected in one go; each becomes a separate **G-code job** under the current project.

3. The file path and base filename must be stored in the `GCodeJob` model.

4. Import should be robust:
   - If one file fails to parse, others should still import.
   - A summary dialog lists all import errors and warnings.

---

### 5.2 G-code structure handling (header / body / footer)

The application expects that **CAM-generated files primarily contain the
geometric body**, but must also handle users importing complete programs that
already include preambles and footers.

1. **Body focus**

   - For plotting, simulation and transforms, Feature 1 must identify the
     **geometric body region**:
     - motion commands (`G0/G1/G2/G3`) with X/Y(/Z) coordinates,
     - relevant feed changes (`F`),
     - spindle state if it affects movement (e.g. “engraving vs rapid”).

2. **Header/footer awareness**

   - If header/footer-like commands exist in the file (e.g. `G28`, `G53`, `M3`,
     `M5`), they must still be parsed, but:
     - flagged to the user (e.g. “CAM generated its own header/footer”),
     - clearly marked in the internal model so the **centralized header/footer
       engine** can decide whether to keep or override them.

3. **Execution program construction (later features)**

   - Feature 1 provides enough structure so other features can build a final
     “execution program” as:

     ```text
     HEADER (from Feature 15, using job config)
     + BODY (possibly transformed)
     + FOOTER (from Feature 15)
     ```

   - Feature 1 itself does **not** merge them; it only ensures that the body is
     clearly represented and that header/footer-like statements are identifiable.

---

### 5.3 Parsing rules

The parser must:

1. **Tokenization**

   - Handle comments:
     - `; comment` style,
     - parentheses `(comment)` if used.
   - Skip blank lines cleanly.
   - Preserve **original line numbers**, even for comment-only lines.

2. **Modal state**

   - Track modal G-codes (e.g. G0 vs G1) and apply them when subsequent lines
     omit explicit codes.
   - Track current work coordinate system (`G54`) and offsets (`G92`).
   - Track units (`G21` for mm; inches can be ignored or explicitly rejected
     for now to keep things simple).

3. **Coordinates**

   - For each statement, parse X, Y, Z, F, S, etc.
   - Default assumption: **absolute** coordinates for X/Y/Z unless the machine
     spec says otherwise (incremental modes may be disallowed or ignored).
   - Maintain last-known coordinate values to support modal behaviour (e.g. a
     line specifying only X updates X while Y/Z stay the same).

4. **Supported vs unsupported codes**

   - Only codes from the supported list are considered **valid**.
   - Others should:
     - be preserved in the raw source,
     - be stored as “unknown” statements,
     - generate **warnings** (not fatal errors) unless explicitly dangerous.

5. **Error handling**

   - Types of issues:
     - Syntax errors (malformed numbers, unknown letter words).
     - Unsupported G-codes or parameters.
     - Out-of-range values (e.g. obvious axis limit violation).
   - On error:
     - The line is still stored in the raw text.
     - The parser marks it in the program model as an error/warning.
     - Import finishes; the UI presents an error list referencing file + line.

---

### 5.4 Z offset configuration

This is a key part of the workflow and must be clear.

1. For each imported job, the system must maintain a **Z offset configuration**:

   ```text
   job.z_surface_offset  (float, mm, typically negative)
````

Example: `-10.2` if `G92 X0 Y0 Z-10.2` was used when the bit touched the
board surface.

2. The UI should either:

   * Prompt the user for Z offset when first preparing the job for simulation /
     streaming, or
   * Allow the user to set / edit it in a job properties dialog.

3. Feature 1 does **not** decide *how* the Z offset is applied; it just:

   * stores the value, and
   * marks any existing `G92 ... Z` statements in the source.

4. Later features (header/footer, on-the-fly Z, Z mesh) will use this stored
   value to:

   * generate `G92` commands in the preamble, or
   * adjust motion Z values in a transformed copy of the body.

---

### 5.5 Program index & geometry hooks

The parser must output enough information for the geometry builder and viewer.

1. **Program index**

   * Each parsed statement has:

     * `statement_index` (0-based in `GCodeProgram`),
     * `source_line_number` (1-based in the file).

   * A separate `ProgramIndex` structure (built together with geometry) maps:

     * from statement → list of segment indices,
     * from segment → statement index.

2. **Movement representation**

   * For motion statements, the parser provides:

     * previous XYZ position,
     * new XYZ position,
     * motion type (rapid, feed, arc, etc.).
   * Geometry builder uses this to create line segments or arc approximations.

3. **Consistency**

   * There must be a stable mapping from:

     * editor line → statement index → segment indices,
     * viewer picked segment → statement index → editor line.

   * This mapping is critical for Feature 2 (viewer/editor sync), Feature 3
     (simulation), and Feature 7 (resume from click).

---

## 6. Data Model

### 6.1 GCodeJob (project model)

At minimum, each `GCodeJob` should contain:

* `id`: unique identifier.
* `name`: display name (usually filename).
* `path`: original file path (if any).
* `source`: full raw G-code text as imported.
* `program`: parsed `GCodeProgram`.
* `program_index`: mapping between statements and geometry segments.
* `geometry`: toolpath geometry (segments) derived from `program`.
* `z_surface_offset`: user-specified Z offset (float).
* `visible`: whether job is shown in viewer.
* `color`: base colour for this job’s geometry.

### 6.2 GCodeProgram

Core elements (conceptual):

* `statements: List[Statement]`
* Each `Statement` contains:

  * `line_number`
  * `modal_group` (motion / plane / units / etc.)
  * parsed words (X/Y/Z/F/S/G/M/…)
  * error/warning flags
  * flags `is_header_candidate`, `is_footer_candidate`, `is_body_motion`, etc.

---

## 7. Non-Functional Requirements

1. **Performance**

   * Typical use case: PCB toolpaths in the range of 1–100k lines.
   * Parsing and geometry building for a 10k-line file should complete well
     under 1 second on a modern desktop.

2. **Determinism**

   * Parsing must be deterministic: the same file always produces the same
     `GCodeProgram` and indices.

3. **Safety**

   * Parsing alone should never send anything to the machine.
   * Out-of-range values should be detected early and cause warnings.

4. **Extensibility**

   * It should be straightforward to:

     * add new supported codes,
     * add new analysis passes (e.g. to detect drilling operations for
       optimization),
     * add transforms that operate on `GCodeProgram` / movement lists.

---

## 8. Implementation Notes for Developers / AI Agents

1. **Do not rewrite the parser from scratch** unless absolutely necessary.
   Prefer incremental improvements that keep the existing data model stable.

2. **Keep raw source vs structured model separate**:

   * Never lose or silently rewrite the original text.
   * All transformations should operate on a separate structure or cloned text.

3. **Model header/footer explicitly**, but keep the **central logic** for
   constructing preambles/footers in Feature 15, not here.

4. **Z offset is configuration, not code**:

   * Store it in `GCodeJob`.
   * Let header/footer and Z-adjustment features decide how to apply it.

5. **Always think about the mapping chain**:

   ```text
   file line ↔ statement ↔ movement(s) ↔ geometry segment(s)
   ```

   Any changes to parsing must preserve or improve this mapping, not break it.

6. When in doubt about behaviour, refer to:

   * NC Viewer for how movements are interpreted and visualized.
   * FlatCAM and Candle for how PCB jobs are structured and how user workflows
     feel.
   * Cirqoid manual for what the machine actually accepts.

---

