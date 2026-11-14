import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea  # noqa: E402

from ankihelper import gui  # noqa: E402


def wheel(widget, modifiers):
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def test_shift_jumps_down_fast_and_ctrl_scrolls_sideways():
    gui.make_app()
    area = QScrollArea()
    content = QLabel("x")
    content.setFixedSize(3000, 5000)
    area.setWidget(content)
    area.resize(400, 400)
    area.show()

    wheel(content, Qt.KeyboardModifier.ShiftModifier)
    assert area.verticalScrollBar().value() >= 250, "one notch moves most of a screen"
    assert area.horizontalScrollBar().value() == 0

    wheel(content, Qt.KeyboardModifier.ControlModifier)
    assert area.horizontalScrollBar().value() == 120
