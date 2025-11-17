from __future__ import annotations

from typing import Optional, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from core.project_model import Project, GCodeJob


class ProjectTreeWidget(QTreeWidget):
    """FlatCAM-style project tree with visibility checkboxes."""

    job_selected_callback: Optional[Callable[[Optional[GCodeJob]], None]]
    visibility_changed_callback: Optional[Callable[[], None]]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.project: Optional[Project] = None
        self.jobs_root_item: Optional[QTreeWidgetItem] = None
        self.job_selected_callback = None
        self.visibility_changed_callback = None

        self.itemSelectionChanged.connect(self._on_selection_changed)
        self.itemChanged.connect(self._on_item_changed)

    # --------------------------------------------------------------------- API

    def set_project(self, project: Project) -> None:
        self.project = project
        self._rebuild_tree()

    # ----------------------------------------------------------------- helpers

    def _rebuild_tree(self) -> None:
        self.clear()
        if self.project is None:
            return

        project_root = QTreeWidgetItem([self.project.name])
        self.addTopLevelItem(project_root)

        jobs_root = QTreeWidgetItem(["G-code Jobs"])
        project_root.addChild(jobs_root)
        self.jobs_root_item = jobs_root

        for job in self.project.jobs:
            item = QTreeWidgetItem([job.display_name()])
            flags = item.flags()
            flags |= Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled
            item.setFlags(flags)
            item.setCheckState(0, Qt.Checked if job.visible else Qt.Unchecked)
            item.setData(0, Qt.UserRole, job.id)
            jobs_root.addChild(item)

        project_root.setExpanded(True)
        jobs_root.setExpanded(True)

    def _on_selection_changed(self) -> None:
        if self.project is None:
            return

        selected_items = self.selectedItems()
        if not selected_items:
            if self.job_selected_callback:
                self.job_selected_callback(None)
            return

        item = selected_items[0]
        job_id = item.data(0, Qt.UserRole)
        if job_id is None:
            if self.job_selected_callback:
                self.job_selected_callback(None)
            return

        job = self.project.get_job_by_id(job_id)
        if self.job_selected_callback:
            self.job_selected_callback(job)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self.project is None:
            return

        job_id = item.data(0, Qt.UserRole)
        if job_id is None:
            return

        job = self.project.get_job_by_id(job_id)
        if job is None:
            return

        job.visible = item.checkState(0) == Qt.Checked
        if self.visibility_changed_callback:
            self.visibility_changed_callback()
