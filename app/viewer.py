from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence, Tuple

import math
import numpy as np
import pyqtgraph as pg
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
    - RGB axes at origin (legend text).
    - Per-job coloured toolpaths with visibility.
    - Highlight overlay for selected segments + endpoint pins.
    - Approximate XY(Z) cursor readout via unprojection.
    - Simple simulation head marker driven by MainWindow.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = gl.GLViewWidget()
        layout.addWidget(self.view)

        # Background and camera
        self.view.setBackgroundColor(30, 30, 30)
        self.view.opts["distance"] = 200
        self.view.setCursor(Qt.CrossCursor)

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
        grid.setSize(2000, 2000)
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
        self._head_marker: Optional[GLScatterPlotItem] = None  # simulation head

        # Callback to MainWindow for XY(Z) readout
        self.cursor_moved_callback: Optional[CursorCallback] = None

        # Picking radius in model units (mm); updated with zoom/grid
        self._pick_radius: float = 1.0

        # See mouse move events even with no buttons pressed
        self.view.setMouseTracking(True)
        self.view.installEventFilter(self)

        # Initial grid spacing tuning
        self._update_grid_spacing()
        # Default to an isometric-like view from (-, -, +) quadrant
        self.set_iso_view()

    # ----------------------------------------------------------------- public API

    def set_project(self, project: Project) -> None:
        """Set current project and rebuild all job line plots."""
        self._project = project
        self._rebuild_scene()

    def set_top_view(self) -> None:
        """Convenience: look straight down on XY plane."""
        # Elevation 90 => top-down; azimuth 0 aligns X to the right
        # and Y upwards in the 2D projection (screen space).
        self.view.setCameraPosition(elevation=90, azimuth=270)
        self._update_grid_spacing()

    def set_iso_view(self) -> None:
        """Set camera to an isometric view from (-, -, +) quadrant."""
        # Azimuth ~225deg looks from negative X/negative Y towards origin.
        self.view.setCameraPosition(elevation=35, azimuth=225)
        self._update_grid_spacing()

    def zoom_to_fit(self) -> None:
        """Zoom camera so all visible geometry fits the view."""
        if self._project is None:
            return

        has_geometry = False
        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")

        for job in self._project.jobs:
            if not job.visible or job.geometry is None:
                continue
            segments = job.geometry.segments
            if not segments:
                continue
            has_geometry = True
            for seg in segments:
                for (x, y, z) in (seg.start, seg.end):
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y
                    if z < min_z:
                        min_z = z
                    if x > max_x:
                        max_x = x
                    if y > max_y:
                        max_y = y
                    if z > max_z:
                        max_z = z

        if not has_geometry:
            return

        cx = (min_x + max_x) * 0.5
        cy = (min_y + max_y) * 0.5
        cz = (min_z + max_z) * 0.5
        self.view.opts["center"] = pg.Vector(cx, cy, cz)

        span_x = max_x - min_x
        span_y = max_y - min_y
        span_z = max_z - min_z
        radius = max(span_x, span_y, span_z) * 0.5
        if radius <= 0:
            radius = 10.0

        # Factor chosen empirically to keep geometry comfortably in view.
        distance = max(radius * 3.0, 50.0)
        self.view.setCameraPosition(distance=distance)
        self._update_grid_spacing()

    def highlight_segments(self, job: GCodeJob, segment_indices: Sequence[int]) -> None:
        """Highlight specific segments for a job."""
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

        pos = np.array(pts, dtype=float)
        line_item = gl.GLLinePlotItem(
            pos=pos,
            mode="lines",
            color=(1.0, 1.0, 0.0, 1.0),
            width=3.0,
        )
        self.view.addItem(line_item)
        self._highlight_item = line_item

        if point_pts:
            ppos = np.array(point_pts, dtype=float)
            scatter = GLScatterPlotItem(
                pos=ppos,
                size=5.0,
                color=(1.0, 1.0, 0.0, 1.0),
                pxMode=True,
            )
            self.view.addItem(scatter)
            self._highlight_points = scatter

    def reset_simulation_head(self) -> None:
        """Remove the simulation head marker."""
        if self._head_marker is not None:
            self.view.removeItem(self._head_marker)
            self._head_marker = None

    def update_simulation_head(self, job: GCodeJob, stmt_index: int) -> None:
        """Highlight segments for a program line and show a head marker."""
        if job.geometry is None or job.program_index is None:
            return

        idx_map = job.program_index.statement_to_segments
        seg_indices = idx_map.get(stmt_index, [])
        self.highlight_segments(job, seg_indices)

        if not seg_indices:
            self.reset_simulation_head()
            return

        segments = job.geometry.segments
        last_idx = seg_indices[-1]
        if not (0 <= last_idx < len(segments)):
            self.reset_simulation_head()
            return

        seg = segments[last_idx]
        hx, hy, hz = seg.end

        if self._head_marker is not None:
            self.view.removeItem(self._head_marker)
            self._head_marker = None

        pos = np.array([[hx, hy, hz]], dtype=float)
        marker = GLScatterPlotItem(
            pos=pos,
            size=8.0,
            color=(0.0, 1.0, 1.0, 1.0),
            pxMode=True,
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
        if self._head_marker is not None:
            self.view.removeItem(self._head_marker)
            self._head_marker = None

    def _rebuild_scene(self) -> None:
        self._clear_jobs()
        if self._project is None:
            return

        for job in self._project.jobs:
            if not job.visible or job.geometry is None:
                continue
            item = self._create_job_item(job)
            if item is not None:
                self._job_items[job.id] = item
                self.view.addItem(item)

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

    # ------------------- cursor helpers ---------------------

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
        self._grid.setSize(2000, 2000)

        self._grid_spacing = (step, step)
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

        if self.cursor_moved_callback is not None:
            self.cursor_moved_callback(qx, qy, qz)

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
