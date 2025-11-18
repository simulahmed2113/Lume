from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
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
)
from PySide6.QtGui import QTextCursor

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
    - Live XY cursor readout and plot�+'editor selection.
    - Simple "Top view" camera option.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CNC Softwire")

        self.project = Project(name="Untitled Project")
        self.current_job: Optional[GCodeJob] = None
        self._is_top_view: bool = False

        self._create_viewer()
        self._create_project_tree_dock()
        self._create_gcode_editor_dock()
        self._create_status_bar()
        self._create_menu_bar()
        self._create_view_toolbar()

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

    def _create_view_toolbar(self) -> None:
        toolbar = QToolBar("View", self)
        toolbar.setObjectName("ViewToolbar")

        fit_action = toolbar.addAction("Fit")
        fit_action.setToolTip("Zoom to fit all visible geometry")
        fit_action.triggered.connect(self.viewer.zoom_to_fit)

        toggle_action = toolbar.addAction("Toggle")
        toggle_action.setToolTip("Toggle between isometric and top views")
        toggle_action.triggered.connect(self._toggle_view_mode)

        self.addToolBar(toolbar)

    # ----------------------------------------------------------------- actions

    def _new_project(self) -> None:
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

    # ----------------------------------------------------------------- callbacks

    def _on_job_selected(self, job: Optional[GCodeJob]) -> None:
        self.current_job = job

        if job is None:
            self.gcode_editor.clear()
            self.apply_action.setEnabled(False)
            self.apply_button.setEnabled(False)
            self.offset_button.setEnabled(False)
            self.statusBar().showMessage("No job selected", 3000)
            return

        self.gcode_editor.set_job(job)
        self.apply_action.setEnabled(True)
        self.apply_button.setEnabled(True)
        self.offset_button.setEnabled(True)
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

    # -------------------- viewer �+' mainwindow hooks -------------------

    def _on_view_cursor_moved(self, x: float, y: float, z: float) -> None:
        """Update status bar with current crosshair position (always XY plane)."""
        self.status_coord_label.setText(f"X: {x:7.3f}    Y: {y:7.3f}    Z: {z:7.3f}")

    # -------------------------- offsets dialog ------------------------

    def _toggle_view_mode(self) -> None:
        """Toggle between isometric and top-down camera views."""
        if self._is_top_view:
            self.viewer.set_iso_view()
            self._is_top_view = False
        else:
            self.viewer.set_top_view()
            self._is_top_view = True

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
