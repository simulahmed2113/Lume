# Feature 07: Affine Alignment

## Overview

This feature lets you:

1. **Define reference points** (fiducials) in G-code (design) space.
2. **Drill those points** as physical holes on the PCB (via a dedicated drill job).
3. After moving / flipping / re-fixturing the board, **measure the new positions**
   of those same holes in machine space.
4. Compute a **2D transform** (rotation + translation, optionally full affine).
5. Apply that transform to any remaining G-code so the **rest of the job is
   perfectly aligned** to the new physical position.

It supports:

- **3-point alignment** (minimal case), and
- **4-point alignment** (recommended - overdetermined, more robust).

In practice, this is the core of **double-sided alignment** and any workflow
where the board is not perfectly square/aligned to the machine axes.

---

## Current Behavior

- The design exists as a spec; there is no production-ready UI for selecting or
  measuring fiducials yet.
- Reference drill workflows (Feature 08) and alignment profiles are manually
  assembled when needed, so nothing is persisted automatically.

---

## Current Challenges & Goals

### Problem Statement

Real PCB workflow:

- You drill reference holes / fiducials on the board.
- You remove, flip, or re-clamp the board.
- Now the board is **shifted and rotated** relative to machine axes.
- Original G-code coordinates **no longer line up** with the board.

We want to:

- Use known reference points (A, B, C, D) in **design coordinates**.
- Drill those as physical holes on the board.
- Later, find where those holes actually are in **machine coordinates**
  after re-fixture.
- Compute a transform that maps original design space -> new machine space.
- Apply that transform to all XY coordinates of the remaining jobs.

### Goals

1. **Reference point definition (design side)**
   - User selects **3 or 4 reference points** on the plotted G-code (A, B, C, D).
   - System stores their **design coordinates** in the current board coordinate system.
   - System can generate a separate **drilling job** for these points (see Feature 11).

2. **Reference point measurement (machine side)**
   - After drilling and re-fixture, user uses the CNC to find **actual machine
     coordinates** of the same points (A', B', C', D').
   - Software records these **machine coordinates**.

3. **Transform computation**
   - Compute a 2D transform `T(x) = A x + t`:
     - at least rotation + translation,
     - optionally full affine (scale + shear).
   - Use 3 points for an exact solution; use 4 points for overdetermined
     least-squares (more stable).

4. **Apply to G-code**
   - For any selected G-code object:
     - apply `T()` to all XY positions,
     - leave Z as-is (Z corrections are handled by other features).
   - Output a **realigned G-code job** used for the remaining operations.

5. **Integration in pipeline**
   - Fits into full pipeline:
     - import -> standard -> mirror (if needed) -> realign -> height map -> operation.
   - Works with:
     - double-sided boards,
     - mirroring (Feature 12),
     - height map / Z mesh (Feature 9),
     - runtime execution (Feature 3 / Feature 4).

---

## Current Workflow

### Typical Workflow

1. **Before machining**
   - Load / prepare G-code.
   - Pick 3-4 reference points in the job area (A, B, C, D).
   - Generate & run a **reference drilling program** to drill these points.

2. **Run initial operations**
   - Example: run top-side isolation and drilling using original alignment.

3. **Move / flip the board**
   - Flip to back side, or re-clamp in a slightly different position.

4. **Teach new coordinates**
   - After re-fixture, jog to each reference hole A, B, C, D.
   - Capture each actual machine position A', B', C', D'.

5. **Compute transform & apply**
   - Software computes transform from design points -> machine points.
   - Generate transformed G-code for remaining jobs
     (e.g. bottom layer, second pass).

6. **Run transformed job**
   - Operate on the realigned G-code so paths line up with existing features.

---

## Requirements

### 4.1 Step 1 - Selecting Reference Points (Design Space)

In the **viewer**, user selects reference points on the plotted G-code:

- Tool: **"Define Reference Points (Fiducials)"** (or via Feature 11 wizard).

Behaviour:

1. User selects 3-4 distinct positions on geometry:
   - Points labeled A, B, C, D.
   - Clicking uses snap-to geometry (pad centers, drill holes, corners etc.)
     where possible.

2. For each click:
   - System finds nearest relevant geometry point.
   - Extracts its **design coordinates** `(x_design, y_design)` in current
     board coordinate system (typically G54).

3. UI shows a list:

   ```text
   Reference Points (Design Coordinates)
   A: (xA, yA)
   B: (xB, yB)
   C: (xC, yC)
   D: (xD, yD)
````

Rules:

* Minimum **3 points** required.
* Up to **4 points** supported (recommended).
* If 4 are defined, alignment uses **all 4** when computing transform.

> **Note:** The actual creation and storage of these design points and the
> corresponding drill job is covered in **Feature 11 - Reference Point Drilling**.
> This feature (10) consumes those design reference points and adds the
> machine-side part and transform.

---

### 4.2 Step 2 - Reference Drill Program (Design -> Physical Holes)

Once reference points are chosen, the user generates a **reference drilling job**
(usually via the Feature 11 wizard).

This program:

* Contains only:

  * safe Z move,
  * rapid moves to each point,
  * drilling moves,
  * spindle on/off and footer.
* Is treated as its own **operation** and run early in the process.

Typical structure:

```gcode
; Reference points drilling
G21 G90
G0 Z5.000          ; safe Z

; A
G0 XxA YyA
G1 Z-0.700 F80.0
G0 Z5.000

; B
G0 XxB YyB
G1 Z-0.700 F80.0
G0 Z5.000

; C
G0 XxC YyC
G1 Z-0.700 F80.0
G0 Z5.000

; D (if defined)
G0 XxD YyD
G1 Z-0.700 F80.0
G0 Z5.000

M5
G0 Z5.000
; end reference drilling
```

(Depth, feed, safe Z, spindle depend on user settings.)

---

### 4.3 Step 3 - Measuring New Coordinates (Machine Space)

After the board is moved / flipped:

* The user opens a **"Teach Reference Points (Machine)"** dialog.

For each reference point:

1. Jog the machine so the tool is centered over the **corresponding hole**.
2. Press **"Capture A"** (or B, C, D).

   * Software reads current machine position `(xA', yA')` in current work
     coordinate system.
   * Stores as **machine coordinate** for that reference.

UI shows:

```text
Reference Points (Machine Coordinates)
A': (xA', yA')
B': (xB', yB')
C': (xC', yC')
D': (xD', yD')   ; if captured
Status: Ready (3+ points captured)
```

Constraints:

* Must capture at least **3** points: A', B', C'.
* If 4 are captured, all 4 are used for a more stable solution.
* Multiple **AlignmentProfiles** can be stored (e.g. "Flip alignment", "Re-clamp #2").

---

### 4.4 Step 4 - Computing the Transform

We now have:

* Design coordinates: `(xA, yA)`, `(xB, yB)`, `(xC, yC)`, `(xD, yD)`
* Machine coordinates: `(xA', yA')`, `(xB', yB')`, `(xC', yC')`, `(xD', yD')`

We want a 2D transform:

```text
[ x' ]   [ a11 a12 ] [ x ]   [ tx ]
[ y' ] = [ a21 a22 ] [ y ] + [ ty ]
```

Modes:

1. **Rigid mode (recommended)**

   * rotation + translation (+ optional uniform scale).
   * best for standard board rotation / translation.

2. **Affine mode (advanced)**

   * full 2x2 matrix (scale + shear + rotation) + translation.
   * can compensate for slight non-uniform scaling or fixture distortion.

The user can choose:

* "Rigid alignment (recommended)"
* "Full affine (advanced)"

#### Choosing 3 vs 4 Points

* With **3 points**, system solves exactly (rigid or affine variant).
* With **4 points**, system solves in least-squares sense to reduce error.

After computing transform:

* Show per-point **residual error**:

  ```text
  error_i = distance( T(x_i, y_i), (x_i', y_i') )
  ```

* Display:

  * max error,
  * RMS error.

If error > threshold (e.g. 0.02-0.05 mm), warn user alignment may be unreliable.

---

### 4.5 Step 5 - Applying Transform to G-code

The user then selects one or more **G-code objects to align**:

* e.g. `Mill_Bottom (standard)`, `Drill_Top_rest`, etc.

Context menu: **"Apply Alignment Profile..."**

* User chooses a previously computed **AlignmentProfile** (e.g.
  `"Ref_ABCD_2025-01-01"`).

System creates **new transformed objects**, e.g.:

* `Mill_Bottom (aligned_ABCD_2025-01-01)`

Transformation behaviour:

* For every statement with X/Y:

  ```text
  (x_original, y_original) -> (x_transformed, y_transformed) = T(x_original, y_original)
  ```

* Z values remain unchanged (Z is handled by Features 6/9).

* Non-motion lines (no X/Y) are left as-is.

* Arcs (G2/G3):

  * ideally: transform endpoints and centers and preserve arcs, OR
  * in a simpler implementation: approximate arcs with segments in the internal
    model and optionally re-generate arcs later.

After transformation:

* Geometry is rebuilt.
* Viewer shows transformed path over the board in its **new** position.
* G-code text of the new object has transformed XY values.

---

### Multiple Alignments & Double-Sided PCBs

This feature also supports:

* **Different alignment profiles** for different setups:

  * e.g. first profile for initial top-side fixture,
  * second profile for flipped board alignment.

For double-sided boards, typical bottom-side pipeline:

1. Mirror bottom design (Feature 12).
2. Apply **3-/4-point alignment** based on same reference holes (drilled through board).
3. Apply height map / Z mesh (Feature 9) if needed.
4. Run through runtime / streaming (Features 3 & 4).

---

## Current Implementation

### Data Structures

#### Design & Machine Reference Points

```python
class DesignRefPoint:
    label: str   # "A", "B", "C", "D"
    x: float
    y: float

class MachineRefPoint:
    label: str   # "A", "B", "C", "D"
    x: float
    y: float
```

#### Alignment Profile

```python
from enum import Enum

class AlignmentMode(Enum):
    RIGID = "rigid"   # rotation + translation (+ optional uniform scale)
    AFFINE = "affine" # full 2x2 + translation

class AlignmentProfile:
    id: str
    name: str
    mode: AlignmentMode
    design_points: list[DesignRefPoint]
    machine_points: list[MachineRefPoint]
    # Transform parameters:
    a11: float
    a12: float
    a21: float
    a22: float
    tx: float
    ty: float
    created_at: datetime
    active_for_front: bool
    active_for_back: bool
```

Project model:

```python
class Project:
    ...
    gcode_jobs: list[GCodeJob]
    reference_point_sets: list[ReferencePointSet]  # Feature 11
    alignment_profiles: list[AlignmentProfile]
    ...
```

---

### Solving the Transform

We want `T(x) = A x + t`, with:

```text
A = [a11 a12]
    [a21 a22]
t = [tx ty]^T
```

Given N reference pairs `(x_i, y_i) -> (x_i', y_i')`.

#### Affine Mode

Affine has 6 parameters: `a11, a12, a21, a22, tx, ty`.

For each point i:

```text
x_i' = a11 x_i + a12 y_i + tx
y_i' = a21 x_i + a22 y_i + ty
```

* With N >= 3 points (each gives 2 equations):

  * N=3 -> exactly determined,
  * N=4 -> overdetermined; solve via least squares.

Implementation:

* Build linear system `M p = b`,
* `p = [a11, a12, a21, a22, tx, ty]^T`,
* Solve by normal equations or SVD.

#### Rigid Mode

Rigid transform with optional uniform scale:

```text
x' = s ( costheta * x - sintheta * y ) + tx
y' = s ( sintheta * x + costheta * y ) + ty
```

Parameters: `s, theta, tx, ty` (4 total).

Standard solution:

1. Compute centroids of design and machine point sets.
2. Translate both sets to zero-mean.
3. Use a Procrustes / Kabsch-style algorithm:

   * compute rotation (and scale if desired) that best aligns sets.
4. Compute translation `t` to align centroids.

---

### Applying the Transform to G-code (Implementation)

Integration with transform pipeline:

Typical order:

1. Import and parse (Feature 1).
2. Standardization / normalization.
3. Mirror (for bottom side, Feature 12).
4. **Alignment transform (Feature 10)**.
5. Height mapping / Z mesh (Feature 9).
6. Operation / runtime (Features 3 & 4).

Pseudo-code:

```python
def apply_alignment_profile(job: GCodeJob, profile: AlignmentProfile) -> GCodeJob:
    new_job = job.clone_shallow()  # copy metadata, new ID, etc.
    new_job.name = f"{job.name} (aligned {profile.name})"

    for stmt in new_job.program.statements:
        if stmt.has_xy():
            x, y = stmt.x, stmt.y
            x_prime = profile.a11 * x + profile.a12 * y + profile.tx
            y_prime = profile.a21 * x + profile.a22 * y + profile.ty
            stmt.x, stmt.y = x_prime, y_prime
        # Z remains unchanged here

    # rebuild text + geometry
    new_job.rebuild_text_from_statements()
    new_job.rebuild_geometry()

    return new_job
```

Arcs:

* Implementation detail:

  * either transform arc centers (I, J) and endpoints consistently,
  * or approximate arcs with segments in the internal model.

---

### Interaction With Other Features

* **Feature 9 - Height Mapping / Z Mesh**

  * Alignment is applied to XY **before** mesh correction:

    * we query the Z mesh using transformed `(X, Y)`.
* **Feature 6 - Z Offsets / On-the-fly Z**

  * Z offsets and runtime deltas act on Z after alignment.
* **Feature 7 - Resume From Click**

  * Runtime & picking operate on transformed geometry, so clicking on the
    viewer still maps to correct (aligned) program statements.
* **Feature 12 - Mirror / Back-side Mode**

  * For bottom side:

    1. mirror geometry,
    2. then apply alignment profile for backside,
    3. then apply Z mesh & Z offsets.

---

## Example Scenario

1. **Top side:**

   * Choose 4 corner fiducials:

     * A(2, 5), B(90, 5), C(90, 70), D(2, 70).
   * Generate and run **reference drill** to drill A-D.
   * Run top isolation and drilling jobs.

2. **Flip board & clamp again.**

3. **Teach new positions:**

   * Jog to hole A -> capture A'(15.3, 20.1).
   * Jog to B', C', D' -> capture each.
   * Compute a rigid alignment profile `"TopToBottom_2025-01-01"`.

4. **Apply profile to bottom job:**

   * `Mill_Bottom (standard)` ->
     `Mill_Bottom (aligned TopToBottom_2025-01-01)`.

5. **Height map (optional):**

   * Apply Z mesh to get:

     * `Mill_Bottom (aligned+leveled)`.

6. **Run aligned bottom job.**

Result:
Bottom traces line up precisely with top traces because all XY coordinates were
rotated and translated to match the new board position.

---

## Edge Cases / Limitations

- Using only three points is mathematically valid but fragile; the solver becomes unstable if the picks are nearly collinear.
- Arcs demand consistent handling of I/J offsets. Until the arc-transform path is complete, approximating arcs as segments may be safer.
- Alignment is only as good as the captured machine coordinates, so inaccurate data from Feature 08 will still yield a bad transform.

## Summary

Feature 10 - **3-/4-Point Realignment / Affine Correction** provides:

* Selection of **3-4 reference points** in G-code (design space).
* A workflow (with help from Feature 11) to drill those points as physical
  reference holes.
* A "teaching" step where the user records the **machine coordinates** of
  those holes after re-fixture.
* Computation of a **2D transform** (rigid or full affine) mapping design
  -> machine coordinates.
* Application of that transform to any G-code job, producing **realigned
  G-code** for subsequent operations.
* Tight integration with:

  * Z offset & on-the-fly Z (Feature 6),
  * height mapping / Z mesh (Feature 9),
  * runtime execution & simulation (Feature 3 / 4),
  * double-sided / mirror workflows (Feature 12).

This feature is the core alignment mechanism that makes the whole PCB workflow
robust against board movement, tilt, and imperfect fixturing.

## Future Improvements

1. Provide a guided wizard that links Feature 08 and this transform so operators cannot mix up fiducial order.
2. Persist multiple alignment profiles per job and expose them in the UI so previously proven transforms can be reused.
