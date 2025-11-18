# Feature 09: G-code Remapping

## Overview

* You already have a **mesh of Z heights** defined over the XY plane.
* Each mesh cell corresponds to a small rectangle (uniform grid).
* The **original G-code** has toolpaths with Z values (cutting, clearance, etc.).
* Goal:
  Create a **new G-code** where:

  * The XY toolpath is identical (same shape and order).
  * Extra points are inserted where toolpath crosses mesh grid lines.
  * Each point's Z is adjusted:
    `Z_new = Z_gcode + Z_mesh_at_XY`.

This makes the toolpath follow the actual surface defined by the mesh.

---

## Current Behavior

- The remapping logic is fully specified but has not yet been integrated into
  the application or streaming engine.
- Height-map data can be stored, yet no automated path warping occurs in the
  current UI.

---

## Align Mesh Z With Job Z (G92 Logic)

### Reference Point

1. Pick a **known reference point** `(X_ref, Y_ref)`:

   * This is a physical location where you know the job's correct Z zero (e.g. where user has set Z=0 on the workpiece).

2. Compute the mesh Z at this point:

```python
Z_mesh_ref = mesh.interpolate_z(X_ref, Y_ref)
```

### Normalize Mesh Around the Reference

To ensure mesh Z=0 at that reference point:

```python
Z_shift = Z_mesh_ref

for each node (i, j) in mesh:
    mesh_z[i][j] = mesh_z[i][j] - Z_shift
```

After this transformation:

* At `(X_ref, Y_ref)` -> `Z_mesh_normalized ~ 0`.
* The mesh is now in the **same Z-zero system** as your G-code (or ready to be mapped to it).

### Apply the G92 Offset

Optionally, you may:

* Insert a `G92` at the beginning of the program to align controller coordinates:

```gcode
G92 Z<job_z_offset>
```

Where `job_z_offset` is whatever value you need to make the controller's Z=0 match your logical Z=0 (this depends on your existing coordinate system).
The important thing for Codex: **the mesh must be normalized such that its "zero" matches the G-code Z zero**.

---

## Prepare the 2D Grid & Filter G-code Moves

### 2D Mesh Projection

* Ignore Z for now and treat the mesh as a **2D grid** over XY.
* Grid consists of uniform rectangular cells:

```python
# Pre-known from mesh:
x_lines = [x0, x1, x2, ..., x_n]  # vertical grid lines (X coords)
y_lines = [y0, y1, y2, ..., y_m]  # horizontal grid lines (Y coords)
# Cells = rectangles between (x_i, x_{i+1}) and (y_j, y_{j+1})
```

### Filter Only "Cutting" Segments

From original G-code:

1. Parse all motion commands (G0, G1, G2, G3) into segments.
2. Consider only segments where the tool is **at or below the cutting plane**. For simplicity:

   * Cutting segments: segments where `Z <= 0` at any part.
   * Pure clearance moves (high above the job) are **ignored** for mesh intersection.

Implementation strategy:

* For each segment, check its start/end Z:

  * If both Z > 0 (pure clearance), **keep original** (no extra points).
  * If at least part of segment has `Z <= 0`:

    * Use this segment in the mesh intersection process.
    * If needed, split segment at Z=0 crossings so that each "cutting" part is a separate segment.

---

## Find Intersections Between Toolpath and Mesh Grid

Instead of thinking "intersection with small squares", it's easier to think **intersection with vertical and horizontal grid lines**.

For each **cutting segment**:

* Segment in XY: from `P0 = (x0, y0)` to `P1 = (x1, y1)`.

We need all intersection points with:

* Vertical grid lines: `X = x_lines[k]`
* Horizontal grid lines: `Y = y_lines[l]`

### Compute the Parametric Form

Represent the segment as:

```python
P(t) = P0 + t * (P1 - P0)   # t  in  [0, 1]
x(t) = x0 + t * (x1 - x0)
y(t) = y0 + t * (y1 - y0)
z(t) = z0 + t * (z1 - z0)
```

### Intersections With Vertical Lines

For each vertical grid line `X = xv`:

* Solve for `t`:

```python
if x1 != x0:
    t = (xv - x0) / (x1 - x0)
    if 0 <= t <= 1:
        y_int = y(t)
        # Only keep if y_int is within overall mesh Y range
```

### Intersections With Horizontal Lines

For each horizontal line `Y = yh`:

* Solve for `t`:

```python
if y1 != y0:
    t = (yh - y0) / (y1 - y0)
    if 0 <= t <= 1:
        x_int = x(t)
        # Only keep if x_int is within overall mesh X range
```

### Collect All Relevant Points

For each segment:

* Always include:

  * t = 0 (start point)
  * t = 1 (end point)
* Add all intersection parameters `t` found with grid lines, as long as:

  * The intersection is within mesh X,Y bounds.
  * The intersection lies within the "cutting" part of the segment (Z <= 0 if that matters).

Then:

```python
t_values = sorted(unique([0.0, 1.0] + all_intersection_t))
```

For each `t` in `t_values`:

```python
x_t = x(t)
y_t = y(t)
z_t = z(t)  # original nominal Z from G-code
```

These `(x_t, y_t, z_t)` are the **new points** we will use to build corrected moves.

---

## Compute Corrected Z Using the Mesh

For each point `(x_t, y_t, z_t)` from the previous step:

1. Get mesh Z value at that XY:

```python
z_mesh = mesh.interpolate_z(x_t, y_t)
```

2. Compute corrected Z:

```python
z_corrected = z_t + z_mesh
```

(Recall: mesh has been normalized so its zero corresponds to job Z zero.)

Now we have the new 3D point:

```python
P_corrected = (x_t, y_t, z_corrected)
```

---

## Rebuild G-code With Additional Points

For each original segment:

1. We already have its sorted `t_values` and corresponding corrected points.
2. Generate **G1 moves** between these points in order, preserving the motion direction and order of the original program.

### Example Pseudocode

```python
def remap_segment_with_mesh(segment, mesh):
    # segment: has P0, P1 with x,y,z; we assume it's cutting segment
    t_values = [0.0, 1.0] + find_grid_intersection_t_values(segment, mesh)
    t_values = sorted(unique(t_values))

    new_points = []
    for t in t_values:
        x = segment.x0 + t * (segment.x1 - segment.x0)
        y = segment.y0 + t * (segment.y1 - segment.y0)
        z_nominal = segment.z0 + t * (segment.z1 - segment.z0)

        z_mesh = mesh.interpolate_z(x, y)
        z_corrected = z_nominal + z_mesh

        new_points.append((x, y, z_corrected))

    # Build G-code lines:
    gcode_lines = []
    # first point may already be at correct position from previous line,
    # but for simplicity emit G1 for each point except maybe the very first segment start.
    for (x, y, z) in new_points[1:]:
        gcode_lines.append(f"G01 X{x:.4f} Y{y:.4f} Z{z:.4f}")

    return gcode_lines
```

### Whole Program Remap

```python
def remap_program_with_mesh(original_gcode, mesh):
    segments = parse_gcode_to_segments(original_gcode)
    new_gcode = []

    for seg in segments:
        if is_clearance_segment(seg):
            # no correction, keep as original (or re-output motion)
            new_gcode.extend(seg.original_lines)
        else:
            # cutting or partly cutting segment => remap
            # optionally split at Z=0 first
            cutting_subsegments = split_segment_by_z_zero(seg)
            for s in cutting_subsegments:
                new_gcode.extend(remap_segment_with_mesh(s, mesh))

    return new_gcode
```

The key invariant:
**XY path is the same**, order is the same; you only add more points along that path with corrected Z values.

---

## Edge Cases / Limitations

- Mesh data must be normalised against a known reference point; if the wrong G92 offset is used the entire job will cut at the wrong depth.
- Only cutting segments should be remapped. Clearance moves remain untouched or the controller would waste time following pointless extra vertices.
- Segments that cross multiple grid lines can accumulate duplicate points; always deduplicate parameter values before building fresh G-code.

## Summary

1. **Normalize mesh Z**:

   * Choose a reference `(X_ref, Y_ref)`.
   * Subtract a constant from all mesh Z so that `meshZ(X_ref, Y_ref) = 0`.
   * Now mesh Z zero aligns with job Z zero used by G-code. Optionally send `G92` to the machine.

2. **Project everything to XY**:

   * Treat mesh as a uniform grid of rectangles in XY.
   * Project G-code toolpath to XY plane.
   * Ignore segments that move only at clearance (Z above cutting depth).

3. **Find intersections**:

   * For each cutting segment, find intersections with grid lines (vertical & horizontal).
   * Each intersection creates a new point along the original path.

4. **Compute new Z at each point**:

   * For each point (original or new intersection point):

     * `Z_new = Z_gcode_original + Z_mesh(x, y)`.

5. **Rebuild G-code**:

   * Replace each cutting segment with a sequence of `G01 X Y Z` moves through all new points in order.
   * The final G-code has:

     * Same path on XY plane.
     * Adjusted Z following the actual surface height from the mesh.
     * Many more points -> smoother level optimization.

---


## Future Improvements

1. Integrate this remapping routine with Feature 06 so users can preview the warped toolpath before streaming.
2. Add optional smoothing to avoid emitting nearly collinear micro-segments after grid intersections.
