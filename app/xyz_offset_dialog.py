from __future__ import annotations
from PySide6.QtWidgets import QDialog, QVBoxLayout, QGridLayout, QLabel, QLineEdit, QDialogButtonBox


class XYZOffsetDialog(QDialog):
    def __init__(self, offset_x: float = 0.0, offset_y: float = 0.0, offset_z: float = -0.10, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Workpiece Offset (G92)")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Enter workpiece offsets that will be applied with G92:"))

        grid = QGridLayout()
        self.edit_x = QLineEdit(f"{offset_x:.2f}")
        self.edit_y = QLineEdit(f"{offset_y:.2f}")
        self.edit_z = QLineEdit(f"{offset_z:.2f}")

        grid.addWidget(QLabel("X offset (mm):"), 0, 0)
        grid.addWidget(self.edit_x, 0, 1)
        grid.addWidget(QLabel("Y offset (mm):"), 1, 0)
        grid.addWidget(self.edit_y, 1, 1)
        grid.addWidget(QLabel("Z offset (mm):"), 2, 0)
        grid.addWidget(self.edit_z, 2, 1)

        layout.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.edit_z.selectAll()

    def get_offsets(self) -> tuple[float, float, float]:
        try:
            return (round(float(self.edit_x.text()), 2),
                    round(float(self.edit_y.text()), 2),
                    round(float(self.edit_z.text()), 2))
        except ValueError:
            return 0.0, 0.0, -0.10
