from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QToolButton,
    QDialog,
)
from PySide6.QtGui import QTextCursor, QAction

from app.gcode_editor import GCodeEditor
from app.project_tree import ProjectTreeWidget
from app.viewer import GCodeViewer
from core.import_pipeline import import_gcode_file, reparse_job
from core.project_model import GCodeJob, Project
from app.xyz_offset_dialog import XYZOffsetDialog


class MainWindow(QMainWindow):
    """Main application window.

    - 3D viewer in the central area.
    - Editable G-code editor with Apply button.
    - Project tree with per-job visibility checkboxes.
    - Live XY cursor readout and plot→editor selection.
    - Simple "Top view" camera option.
    - Offline G-code simulation controls (Run / Pause / Stop).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CNC Softwire")

        self.project = Project(name="Untitled Project")
        self.current_job: Optional[GCodeJob] = None

        # Simulation state
        self._sim_state: str = "idle"  # idle | running | paused
        self._sim_job: Optional[GCodeJob] = None
        self._sim_current_stmt_index: int = -1
        self._sim_interval_ms: int = 30
        self._sim_lines_per_second: float = 400.0

        self._create_viewer()
        self._create_project_tree_dock()
        self._create_gcode_editor_dock()
        self._create_status_bar()
        self._create_menu_bar()
        self._create_sim_toolbar()

        # QTimer for offline simulation
        self.sim_timer = QTimer(self)
        self.sim_timer.setInterval(self._sim_interval_ms)
        self.sim_timer.timeout.connect(self._on_sim_tick)

    # ----------------------------------------------------------------- UI setup

    def _create_viewer(self) -> None:
        self.viewer = GCodeViewer(self)
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewer)
        self.setCentralWidget(container)
        self.viewer.set_project(self.project)

        # Hooks from viewer
        self.viewer.cursor_moved_callback = self._on_view_cursor_moved
        self.viewer.segment_picked_callback = self._on_segment_picked

    def _create_project_tree_dock(self) -> None:
        self.project_tree = ProjectTreeWidget(self)
        self.project_tree.set_project(self.project)
        self.project_tree.job_selected_callback = self._on_job_selected
        self.project_tree.visibility_changed_callback = self._on_visibility_changed

        dock = QDockWidget("Project", self)
        dock.setObjectName("ProjectDock")
        dock.setWidget(self.project_tree)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _create_gcode_editor_dock(self) -> None:
        editor_container = QWidget(self)
        vlayout = QVBoxLayout(editor_container)
        vlayout.setContentsMargins(0, 0, 0, 0)

        hlayout = QHBoxLayout()
        self.apply_button = QPushButton("Apply G-code edits", editor_container)
        self.apply_button.clicked.connect(self._apply_gcode_edits)
        self.apply_button.setEnabled(False)
        hlayout.addWidget(self.apply_button)

        self.offset_button = QToolButton(editor_container)
        self.offset_button.setText("Offsets")
        self.offset_button.setToolTip("Edit workpiece offsets (G92)")
        self.offset_button.clicked.connect(self._edit_offsets)
        self.offset_button.setEnabled(False)
        hlayout.addWidget(self.offset_button)

        hlayout.addStretch(1)

        self.gcode_editor = GCodeEditor(editor_container)

        vlayout.addLayout(hlayout)
        vlayout.addWidget(self.gcode_editor)

        dock = QDockWidget("G-code Editor", self)
        dock.setObjectName("GCodeEditorDock")
        dock.setWidget(editor_container)
        dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        # Track cursor changes to highlight segments in the viewer
        self.gcode_editor.cursorPositionChanged.connect(self._on_editor_cursor_changed)

    def _create_status_bar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)
        status.showMessage("Ready")

        # Live XY(Z) readout on the right, like FlatCAM's bottom bar
        self.status_coord_label = QLabel("X: --    Y: --    Z: --", self)
        self.status_coord_label.setMinimumWidth(220)
        status.addPermanentWidget(self.status_coord_label)

    def _create_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")

        new_project_action = file_menu.addAction("New Project")
        new_project_action.triggered.connect(self._new_project)

        import_action = file_menu.addAction("Import G-code (.nc)...")
        import_action.triggered.connect(self._import_gcode_files)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        job_menu = menu_bar.addMenu("&Job")
        self.apply_action = job_menu.addAction("Apply G-code edits to current job")
        self.apply_action.triggered.connect(self._apply_gcode_edits)
        self.apply_action.setEnabled(False)

        # Simple view menu for camera presets
        view_menu = menu_bar.addMenu("&View")
        top_view_action = view_menu.addAction("Top view (XY)")
        top_view_action.triggered.connect(self.viewer.set_top_view)

    def _create_sim_toolbar(self) -> None:
        """Simulation toolbar with Run / Pause / Stop."""
        toolbar = QToolBar("Simulation", self)
        toolbar.setObjectName("SimulationToolbar")
        self.addToolBar(toolbar)

        self.sim_run_action: QAction = toolbar.addAction("Run")
        self.sim_pause_action: QAction = toolbar.addAction("Pause")
        self.sim_stop_action: QAction = toolbar.addAction("Stop")

        self.sim_run_action.triggered.connect(self._start_simulation)
        self.sim_pause_action.triggered.connect(self._pause_simulation)
        self.sim_stop_action.triggered.connect(self._stop_simulation)

        self._update_sim_actions()

    # ----------------------------------------------------------------- actions

    def _new_project(self) -> None:
        self._stop_simulation()  # reset sim if running

        self.project = Project(name="Untitled Project")
        self.current_job = None
        self.project_tree.set_project(self.project)
        self.gcode_editor.clear()
        self.viewer.set_project(self.project)
        self.apply_action.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.statusBar().showMessage("New project created", 3000)

    def _import_gcode_files(self) -> None:
        dialog = QFileDialog(self, "Import G-code files")
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setNameFilters(["G-code files (*.nc)", "All files (*.*)"])

        if not dialog.exec():
            return

        selected_paths = dialog.selectedFiles()
        if not selected_paths:
            return

        imported_count = 0
        errors: list[str] = []

        for path_str in selected_paths:
            try:
                path = Path(path_str)
                job = import_gcode_file(path)
                self.project.add_job(job)
                imported_count += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path_str}: {exc}")

        self.project_tree.set_project(self.project)
        self.viewer.set_project(self.project)

        if imported_count:
            self.statusBar().showMessage(f"Imported {imported_count} file(s).", 5000)

        if errors:
            QMessageBox.warning(
                self,
                "Import errors",
                "Some files could not be imported:\n" + "\n".join(errors),
            )

    def _apply_gcode_edits(self) -> None:
        if self.current_job is None:
            QMessageBox.information(
                self,
                "No job selected",
                "Select a job in the Project tree before applying edits.",
            )
            return

        new_source = self.gcode_editor.toPlainText()
        try:
            reparse_job(self.current_job, new_source)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Parse error",
                f"Could not parse G-code for this job:\n{exc}",
            )
            return

        self.viewer.set_project(self.project)
        self.statusBar().showMessage("G-code updated from editor", 3000)

    # -------------------------- simulation actions -----------------------------

    def _update_sim_actions(self) -> None:
        has_job = self.current_job is not None
        self.sim_run_action.setEnabled(
            has_job and self._sim_state in ("idle", "paused")
        )
        self.sim_pause_action.setEnabled(self._sim_state == "running")
        self.sim_stop_action.setEnabled(self._sim_state in ("running", "paused"))

    def _start_simulation(self) -> None:
        """Start or resume offline simulation for the current job."""
        if self.current_job is None:
            QMessageBox.information(
                self,
                "No job selected",
                "Select a job in the Project tree before running simulation.",
            )
            return

        if self.current_job.program is None or not self.current_job.program.statements:
            QMessageBox.information(
                self,
                "No G-code",
                "The selected job has no parsed G-code to simulate.",
            )
            return

        restarting = self._sim_state == "idle" or self._sim_job is not self.current_job
        self._sim_job = self.current_job

        if restarting:
            self._sim_current_stmt_index = -1
            self.viewer.reset_simulation_head()
            # Snap to top view when starting a fresh run
            self.viewer.set_top_view()

        self._sim_state = "running"
        self.sim_timer.start(self._sim_interval_ms)
        self._update_sim_actions()
        self.statusBar().showMessage("Simulation running…", 2000)

    def _pause_simulation(self) -> None:
        if self._sim_state != "running":
            return
        self.sim_timer.stop()
        self._sim_state = "paused"
        self._update_sim_actions()
        self.statusBar().showMessage("Simulation paused", 2000)

    def _stop_simulation(self) -> None:
        if self._sim_state == "idle" and self._sim_job is None:
            return
        self.sim_timer.stop()
        self._sim_state = "idle"
        self._sim_job = None
        self._sim_current_stmt_index = -1
        self.viewer.reset_simulation_head()
        self._update_sim_actions()
        # Do not spam status bar if called as part of other actions

    def _on_sim_tick(self) -> None:
        """Timer callback: advance simulation through G-code."""
        if self._sim_state != "running" or self._sim_job is None:
            return

        program = self._sim_job.program
        if program is None or not program.statements:
            self._stop_simulation()
            return

        total = len(program.statements)
        if total == 0:
            self._stop_simulation()
            return

        if self._sim_current_stmt_index < 0:
            self._sim_current_stmt_index = 0
        else:
            lines_per_tick = max(
                1, int(self._sim_lines_per_second * (self._sim_interval_ms / 1000.0))
            )
            self._sim_current_stmt_index += lines_per_tick

        if self._sim_current_stmt_index >= total:
            self._sim_current_stmt_index = total - 1

        stmt_index = self._sim_current_stmt_index

        # Update viewer head + highlight
        self.viewer.update_simulation_head(self._sim_job, stmt_index)

        # Focus editor on the corresponding line
        stmt = program.statements[stmt_index]
        line_no = getattr(stmt, "line_number", stmt_index + 1)

        doc = self.gcode_editor.document()
        block = doc.findBlockByNumber(line_no - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            self.gcode_editor.setTextCursor(cursor)

        self.statusBar().showMessage(
            f"Simulation line {line_no} / {total}", self._sim_interval_ms * 2
        )

        # Stop automatically at the end
        if stmt_index >= total - 1:
            self._stop_simulation()
            self.statusBar().showMessage("Simulation completed", 3000)

    # ----------------------------------------------------------------- callbacks

    def _on_job_selected(self, job: Optional[GCodeJob]) -> None:
        # Changing job cancels any running simulation
        if job is not self.current_job:
            self._stop_simulation()

        self.current_job = job

        if job is None:
            self.gcode_editor.clear()
            self.apply_action.setEnabled(False)
            self.apply_button.setEnabled(False)
            self.offset_button.setEnabled(False)
            self._update_sim_actions()
            self.statusBar().showMessage("No job selected", 3000)
            return

        self.gcode_editor.set_job(job)
        self.apply_action.setEnabled(True)
        self.apply_button.setEnabled(True)
        self.offset_button.setEnabled(True)
        self._update_sim_actions()
        self.statusBar().showMessage(f"Selected job: {job.name}", 3000)

    def _on_editor_cursor_changed(self) -> None:
        if self.current_job is None or self.current_job.program_index is None:
            return

        cursor = self.gcode_editor.textCursor()

        sc = QTextCursor(self.gcode_editor.document())
        ec = QTextCursor(self.gcode_editor.document())

        if cursor.hasSelection():
            sc.setPosition(cursor.selectionStart())
            ec.setPosition(cursor.selectionEnd())
        else:
            sc.setPosition(cursor.position())
            ec.setPosition(cursor.position())

        start_line = sc.blockNumber() + 1
        end_line = ec.blockNumber() + 1
        if end_line < start_line:
            start_line, end_line = end_line, start_line

        program = self.current_job.program
        stmt_indices = [
            idx
            for idx, stmt in enumerate(program.statements)
            if start_line <= stmt.line_number <= end_line
        ]

        segment_indices: list[int] = []
        idx_map = self.current_job.program_index.statement_to_segments
        for si in stmt_indices:
            segment_indices.extend(idx_map.get(si, []))

        self.viewer.highlight_segments(self.current_job, segment_indices)

    def _on_visibility_changed(self) -> None:
        self.viewer.set_project(self.project)

    # -------------------- viewer → mainwindow hooks -------------------

    def _on_view_cursor_moved(self, x: float, y: float, z: float) -> None:
        """Update status bar with current crosshair position (always XY plane)."""
        self.status_coord_label.setText(f"X: {x:7.3f}    Y: {y:7.3f}    Z: {z:7.3f}")

    def _on_segment_picked(self, job: GCodeJob, segment_index: int) -> None:
        """Right-click in viewer selects nearest segment → editor line."""
        # Select job in tree
        root = getattr(self.project_tree, "jobs_root_item", None)
        if root is not None:
            for i in range(root.childCount()):
                item = root.child(i)
                if item.data(0, Qt.UserRole) == job.id:
                    self.project_tree.setCurrentItem(item)
                    break

        self.current_job = job
        self.gcode_editor.set_job(job)
        self.apply_action.setEnabled(True)
        self.apply_button.setEnabled(True)
        self._update_sim_actions()

        if job.program_index is None:
            return

        # Robust mapping: search through statement_to_segments
        idx_map = job.program_index.statement_to_segments
        stmt_index = None
        for si, seg_list in idx_map.items():
            if segment_index in seg_list:
                stmt_index = si
                break

        if stmt_index is None:
            return

        stmt = job.program.statements[stmt_index]
        line_no = stmt.line_number

        doc = self.gcode_editor.document()
        block = doc.findBlockByNumber(line_no - 1)
        if not block.isValid():
            return

        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        self.gcode_editor.setTextCursor(cursor)
        self.gcode_editor.setFocus()

        # Keep highlight consistent with editor selection
        self._on_editor_cursor_changed()

    # -------------------------- offsets dialog ------------------------

    def _edit_offsets(self) -> None:
        if self.current_job is None:
            return

        job = self.current_job
        dlg = XYZOffsetDialog(
            offset_x=job.offset_x,
            offset_y=job.offset_y,
            offset_z=job.offset_z,
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            ox, oy, oz = dlg.get_offsets()
            job.offset_x = ox
            job.offset_y = oy
            job.offset_z = oz

            # Rebuild final Lume G-code with new offsets and make it canonical
            from core.lume_runtime import build_final_gcode

            new_source = build_final_gcode(job)
            try:
                # Update job model + geometry (database + plot)
                reparse_job(job, new_source)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(
                    self,
                    "Offset error",
                    f"Could not apply offsets to G-code:\n{exc}",
                )
                return

            # Refresh editor text so the new G92/header/footer are visible
            if self.current_job is job:
                self.gcode_editor.setPlainText(new_source)

    # -------------------------- final G-code helper --------------------

    def get_final_gcode_for_job(self, job: GCodeJob) -> str:
        from core.lume_runtime import build_final_gcode

        return build_final_gcode(job)
