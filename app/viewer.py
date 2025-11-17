from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence, Tuple

import math
import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import GLGraphicsItem, GLScatterPlotItem
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from OpenGL.GL import (
    glGetDoublev,
    glGetIntegerv,
    GL_MODELVIEW_MATRIX,
    GL_PROJECTION_MATRIX,
    GL_VIEWPORT,
)
from OpenGL.GLU import gluUnProject

from core.project_model import GCodeJob, Project

CursorCallback = Callable[[float, float, float], None]
SegmentCallback = Callable[[GCodeJob, int], None]


class GCodeViewer(QWidget):
    """NC-style 3D viewer based on pyqtgraph's GLViewWidget.

    - XY grid at Z=0.
    - RGB axes at origin (X=red, Y=green, Z=blue) with tiny coloured label.
    - Per-job coloured toolpaths with visibility.
    - Highlight overlay for selected segments + endpoint pins.
    - Mouse XY readout + right-click picking of segments in XY plane.
    - Hover-point highlight on nearest vertex (auto-disabled for very large jobs).
    - Simple simulation head marker driven by MainWindow.
    """

    def __init__(self, parent: Optional[Widget] = None) -> None:  # type: ignore[name-defined]
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = gl.GLViewWidget()
        layout.addWidget(self.view)

        # Background and camera
        self.view.setBackgroundColor(30, 30, 30)
        self.view.opts["distance"] = 200
        self.view.orbit(45, 45)
        self.view.setCursor(Qt.CrossCursor)  # plus-style cursor in plot area

        # Tiny coloured axis legend overlay inside the view
        self.axis_label = QLabel(self.view)
        self.axis_label.setTextFormat(Qt.RichText)
        self.axis_label.setText(
            "<span style='color:#ff5555'>X</span> "
            "<span style='color:#55ff55'>Y</span> "
            "<span style='color:#5599ff'>Z</span>"
        )
        self.axis_label.setStyleSheet("background-color: transparent; font-size: 8px;")
        self.axis_label.move(4, 4)
        self.axis_label.adjustSize()
        self.axis_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # XY grid at Z=0
        grid = gl.GLGridItem()
        grid.setSize(2000, 2000)  # always large, never disappears
        grid.setSpacing(10, 10)
        self.view.addItem(grid)
        self._grid = grid
        self._grid_spacing: Tuple[float, float] = (10.0, 10.0)

        # Origin axes (X red, Y green, Z blue)
        self._axes: list[GLGraphicsItem] = []
        self._add_axes()

        self._project: Optional[Project] = None
        self._job_items: Dict[str, GLGraphicsItem] = {}
        self._highlight_item: Optional[GLGraphicsItem] = None
        self._highlight_points: Optional[GLScatterPlotItem] = None
        self._cursor_cross: Optional[GLGraphicsItem] = None
        self._hover_point: Optional[GLScatterPlotItem] = None
        self._head_marker: Optional[GLScatterPlotItem] = None  # simulation head

        # Hover control – disabled automatically for very large geometries
        self._hover_enabled: bool = True
        self._hover_segment_limit: int = 15000  # if total segments > this, no hover

        # Callbacks to MainWindow
        self.cursor_moved_callback: Optional[CursorCallback] = None
        self.segment_picked_callback: Optional[SegmentCallback] = None

        # Picking radius in model units (mm); updated with zoom/grid
        self._pick_radius: float = 1.0

        # See mouse move events even with no buttons pressed
        self.view.setMouseTracking(True)
        self.view.installEventFilter(self)

        # Initial grid spacing tuning
        self._update_grid_spacing()

    # ----------------------------------------------------------------- public API

    def set_project(self, project: Project) -> None:
        self._project = project
        self._rebuild_scene()

    def set_top_view(self) -> None:
        """Convenience: look straight down on XY plane."""
        self.view.setCameraPosition(elevation=90, azimuth=0)

    def highlight_segments(self, job: GCodeJob, segment_indices: Sequence[int]) -> None:
        # Clear previous highlight
        if self._highlight_item is not None:
            self.view.removeItem(self._highlight_item)
            self._highlight_item = None
        if self._highlight_points is not None:
            self.view.removeItem(self._highlight_points)
            self._highlight_points = None

        if job.geometry is None or not segment_indices:
            return

        pts = []
        point_pts = []
        segments = job.geometry.segments
        for idx in segment_indices:
            if 0 <= idx < len(segments):
                seg = segments[idx]
                x0, y0, z0 = seg.start
                x1, y1, z1 = seg.end
                pts.append([x0, y0, z0])
                pts.append([x1, y1, z1])
                point_pts.append([x0, y0, z0])
                point_pts.append([x1, y1, z1])

        if not pts:
            return

        # Yellow line overlay
        pos = np.array(pts, dtype=float)
        line_item = gl.GLLinePlotItem(
            pos=pos,
            mode="lines",
            color=(1.0, 1.0, 0.0, 1.0),
            width=3.0,
        )
        self.view.addItem(line_item)
        self._highlight_item = line_item

        # Endpoint pins so single-line selection is obvious
        if point_pts:
            ppos = np.array(point_pts, dtype=float)
            scatter = GLScatterPlotItem(
                pos=ppos,
                size=5.0,
                color=(1.0, 1.0, 0.0, 1.0),
            )
            self.view.addItem(scatter)
            self._highlight_points = scatter

    # --------------------------- simulation helpers -----------------------------

    def reset_simulation_head(self) -> None:
        """Remove the simulation head marker and highlight."""
        if self._head_marker is not None:
            self.view.removeItem(self._head_marker)
            self._head_marker = None
        # Do not clear _highlight_item here – MainWindow keeps that in sync
        # via highlight_segments / update_simulation_head.

    def update_simulation_head(self, job: GCodeJob, stmt_index: int) -> None:
        """Highlight the segments for a given program line and show a head marker."""
        if job.geometry is None or job.program_index is None:
            return

        idx_map = job.program_index.statement_to_segments
        seg_indices = idx_map.get(stmt_index, [])
        self.highlight_segments(job, seg_indices)

        if not seg_indices:
            # No geometry for this line – clear head marker.
            self.reset_simulation_head()
            return

        segments = job.geometry.segments
        last_idx = seg_indices[-1]
        if not (0 <= last_idx < len(segments)):
            self.reset_simulation_head()
            return

        seg = segments[last_idx]
        hx, hy, hz = seg.end

        # Replace head marker
        if self._head_marker is not None:
            self.view.removeItem(self._head_marker)
            self._head_marker = None

        pos = np.array([[hx, hy, hz]], dtype=float)
        marker = GLScatterPlotItem(
            pos=pos,
            size=8.0,
            color=(0.0, 1.0, 1.0, 1.0),  # cyan head marker
        )
        self.view.addItem(marker)
        self._head_marker = marker

    # ----------------------------------------------------------------- event filter

    def eventFilter(self, obj, ev):  # type: ignore[override]
        if obj is self.view:
            et = ev.type()
            if et == QEvent.MouseMove and isinstance(ev, QMouseEvent):
                # Let GLViewWidget handle drag/rotate, then update cursor
                self.view.mouseMoveEvent(ev)
                self._update_cursor_from_mouse(ev)
                return True
            if et == QEvent.MouseButtonPress and isinstance(ev, QMouseEvent):
                if ev.button() == Qt.RightButton:
                    self._pick_segment_at(ev)
                    return True
            if et == QEvent.Wheel:
                # Let GLViewWidget handle zoom, then adjust grid spacing
                self.view.wheelEvent(ev)
                self._update_grid_spacing()
                return True
        return super().eventFilter(obj, ev)

    # ----------------------------------------------------------------- internals

    def _add_axes(self) -> None:
        for ax in self._axes:
            self.view.removeItem(ax)
        self._axes.clear()

        # X axis (red)
        x_pos = np.array([[0, 0, 0], [50, 0, 0]], dtype=float)
        x_axis = gl.GLLinePlotItem(pos=x_pos, mode="lines", color=(1.0, 0.0, 0.0, 1.0), width=2.0)
        self.view.addItem(x_axis)
        self._axes.append(x_axis)

        # Y axis (green)
        y_pos = np.array([[0, 0, 0], [0, 50, 0]], dtype=float)
        y_axis = gl.GLLinePlotItem(pos=y_pos, mode="lines", color=(0.0, 1.0, 0.0, 1.0), width=2.0)
        self.view.addItem(y_axis)
        self._axes.append(y_axis)

        # Z axis (blue)
        z_pos = np.array([[0, 0, 0], [0, 0, 10]], dtype=float)
        z_axis = gl.GLLinePlotItem(pos=z_pos, mode="lines", color=(0.0, 0.4, 1.0, 1.0), width=2.0)
        self.view.addItem(z_axis)
        self._axes.append(z_axis)

    def _clear_jobs(self) -> None:
        for item in self._job_items.values():
            self.view.removeItem(item)
        self._job_items.clear()

        if self._highlight_item is not None:
            self.view.removeItem(self._highlight_item)
            self._highlight_item = None
        if self._highlight_points is not None:
            self.view.removeItem(self._highlight_points)
            self._highlight_points = None
        if self._hover_point is not None:
            self.view.removeItem(self._hover_point)
            self._hover_point = None
        if self._head_marker is not None:
            self.view.removeItem(self._head_marker)
            self._head_marker = None

    def _rebuild_scene(self) -> None:
        self._clear_jobs()
        if self._project is None:
            return

        total_segments = 0

        for job in self._project.jobs:
            if not job.visible or job.geometry is None:
                continue
            total_segments += len(job.geometry.segments)
            item = self._create_job_item(job)
            if item is not None:
                self._job_items[job.id] = item
                self.view.addItem(item)

        # Auto-disable hover when geometry is large to avoid lag
        self._hover_enabled = total_segments <= self._hover_segment_limit
        if not self._hover_enabled and self._hover_point is not None:
            self.view.removeItem(self._hover_point)
            self._hover_point = None

    @staticmethod
    def _create_job_item(job: GCodeJob) -> Optional[GLGraphicsItem]:
        geometry = job.geometry
        if geometry is None or not geometry.segments:
            return None

        pts = []
        for seg in geometry.segments:
            x0, y0, z0 = seg.start
            x1, y1, z1 = seg.end
            pts.append([x0, y0, z0])
            pts.append([x1, y1, z1])

        pos = np.array(pts, dtype=float)
        item = gl.GLLinePlotItem(pos=pos, mode="lines", color=job.color)
        return item

    # ------------------- picking / cursor helpers ---------------------

    def _update_grid_spacing(self) -> None:
        """Adjust grid spacing based on camera distance (NC-viewer style)."""
        dist = float(self.view.opts.get("distance", 200.0))
        if dist <= 0:
            dist = 1.0

        target = dist / 20.0

        base = 10 ** math.floor(math.log10(target))
        mult = target / base
        if mult < 1.5:
            step = base
        elif mult < 3.5:
            step = 2 * base
        else:
            step = 5 * base

        step = max(0.01, min(step, 50.0))

        self._grid.setSpacing(step, step)
        # Size fixed large so grid never disappears
        self._grid.setSize(2000, 2000)

        # Remember spacing for crosshair size
        self._grid_spacing = (step, step)

        # Picking radius ~ half a grid square (XY only)
        self._pick_radius = step * 0.5

    def _update_cursor_from_mouse(self, ev: QMouseEvent) -> None:
        pos = ev.position() if hasattr(ev, "position") else ev.pos()
        res = self._unproject_to_plane(pos.x(), pos.y(), plane_z=0.0)
        if res is None:
            return
        wx, wy, wz = res

        # Snap to 0.01 mm resolution
        qx = round(wx * 100.0) / 100.0
        qy = round(wy * 100.0) / 100.0
        qz = round(wz * 100.0) / 100.0

        # Update crosshair and, optionally, hover point in XY plane
        self._update_crosshair(qx, qy)

        if self._hover_enabled:
            self._update_hover_point(qx, qy)
        else:
            # Ensure any previous hover marker is removed when disabled
            if self._hover_point is not None:
                self.view.removeItem(self._hover_point)
                self._hover_point = None

        if self.cursor_moved_callback is not None:
            self.cursor_moved_callback(qx, qy, qz)

    def _update_crosshair(self, x: float, y: float) -> None:
        if self._cursor_cross is not None:
            self.view.removeItem(self._cursor_cross)
            self._cursor_cross = None

        spacing_x, spacing_y = self._grid_spacing
        size = min(spacing_x, spacing_y) * 0.5
        z = 0.0

        pts = np.array(
            [
                [x - size, y, z],
                [x + size, y, z],
                [x, y - size, z],
                [x, y + size, z],
            ],
            dtype=float,
        )
        cross = gl.GLLinePlotItem(
            pos=pts,
            mode="lines",
            color=(1.0, 1.0, 1.0, 1.0),
            width=1.5,
        )
        self.view.addItem(cross)
        self._cursor_cross = cross

    def _update_hover_point(self, x: float, y: float) -> None:
        """Highlight nearest G-code vertex near the cursor (XY only)."""
        if not self._hover_enabled:
            # Should already be handled earlier, but guard anyway.
            return

        if self._project is None:
            if self._hover_point is not None:
                self.view.removeItem(self._hover_point)
                self._hover_point = None
            return

        best_point: Optional[Tuple[float, float, float]] = None
        best_dist_sq = (self._pick_radius * 0.8) ** 2

        for job in self._project.jobs:
            if not job.visible or job.geometry is None:
                continue
            for seg in job.geometry.segments:
                for px, py, pz in (seg.start, seg.end):
                    dx = x - px
                    dy = y - py
                    d2 = dx * dx + dy * dy
                    if d2 < best_dist_sq:
                        best_dist_sq = d2
                        best_point = (px, py, pz)

        if best_point is None:
            if self._hover_point is not None:
                self.view.removeItem(self._hover_point)
                self._hover_point = None
            return

        if self._hover_point is not None:
            self.view.removeItem(self._hover_point)
            self._hover_point = None

        pos = np.array([best_point], dtype=float)
        pt = GLScatterPlotItem(pos=pos, size=6.0, color=(1.0, 1.0, 0.0, 1.0))
        self.view.addItem(pt)
        self._hover_point = pt

    def _pick_segment_at(self, ev: QMouseEvent) -> None:
        if self._project is None:
            return

        pos = ev.position() if hasattr(ev, "position") else ev.pos()
        hit = self._unproject_to_plane(pos.x(), pos.y(), plane_z=0.0)
        if hit is None:
            return
        px, py, _pz = hit

        best_job: Optional[GCodeJob] = None
        best_seg_idx: int = -1
        best_dist_sq: float = self._pick_radius ** 2

        # Pure XY distance – Z ignored as requested
        for job in self._project.jobs:
            if not job.visible or job.geometry is None:
                continue
            for i, seg in enumerate(job.geometry.segments):
                x0, y0, _ = seg.start
                x1, y1, _ = seg.end

                vx = x1 - x0
                vy = y1 - y0
                wx = px - x0
                wy = py - y0

                seg_len_sq = vx * vx + vy * vy
                if seg_len_sq <= 1e-12:
                    cx, cy = x0, y0
                else:
                    t = (vx * wx + vy * wy) / seg_len_sq
                    t = max(0.0, min(1.0, t))
                    cx = x0 + t * vx
                    cy = y0 + t * vy

                dx = px - cx
                dy = py - cy
                dist_sq = dx * dx + dy * dy

                if dist_sq < best_dist_sq:
                    best_dist_sq = dist_sq
                    best_job = job
                    best_seg_idx = i

        if best_job is None or best_seg_idx < 0:
            return

        if self.segment_picked_callback is not None:
            self.segment_picked_callback(best_job, best_seg_idx)
        self.highlight_segments(best_job, [best_seg_idx])

    def _unproject_to_plane(
        self, win_x: float, win_y: float, plane_z: float
    ) -> Optional[Tuple[float, float, float]]:
        """Unproject 2D screen coords to intersection with Z=plane_z in world space."""
        try:
            self.view.makeCurrent()
            model = glGetDoublev(GL_MODELVIEW_MATRIX)
            proj = glGetDoublev(GL_PROJECTION_MATRIX)
            viewport = glGetIntegerv(GL_VIEWPORT)
        except Exception:
            return None
        finally:
            try:
                self.view.doneCurrent()
            except Exception:
                pass

        win_y_flipped = viewport[3] - win_y

        try:
            near = gluUnProject(win_x, win_y_flipped, 0.0, model, proj, viewport)
            far = gluUnProject(win_x, win_y_flipped, 1.0, model, proj, viewport)
        except Exception:
            return None

        nx, ny, nz = near
        fx, fy, fz = far
        dz = fz - nz
        if abs(dz) < 1e-6:
            return None

        t = (plane_z - nz) / dz
        x = nx + (fx - nx) * t
        y = ny + (fy - ny) * t
        z = nz + (fz - nz) * t
        return float(x), float(y), float(z)
