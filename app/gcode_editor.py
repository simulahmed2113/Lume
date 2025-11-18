from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QPlainTextEdit

from core.project_model import GCodeJob


class GCodeEditor(QPlainTextEdit):
    """Text editor used to display and edit the raw G-code of the selected job.

    For Feature 2 the editor becomes editable; MainWindow is responsible for
    taking the current text and re-parsing it into the job when the user
    chooses "Apply G-code edits".
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.current_job: Optional[GCodeJob] = None
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))

    def set_job(self, job: GCodeJob) -> None:
        self.current_job = job
        from core.lume_runtime import build_final_gcode

        # Show the final Lume G-code (header + body + footer) so that
        # replaced header/footer and offsets are visible to the user.
        text = build_final_gcode(job)
        self.setPlainText(text)
        cursor = self.textCursor()
        cursor.setPosition(0)
        self.setTextCursor(cursor)
