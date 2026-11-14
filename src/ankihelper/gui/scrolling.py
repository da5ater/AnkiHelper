from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

FAST_PAGES_PER_NOTCH = 0.8
SIDEWAYS_PIXELS_PER_NOTCH = 120


class FastScroll(QObject):
    """Shift + wheel jumps most of a screen up or down; Ctrl + wheel scrolls left and right."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.Wheel or not isinstance(obj, QWidget):
            return False
        modifiers = event.modifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        if shift == ctrl:
            return False
        delta = event.angleDelta()
        notches = (delta.y() or delta.x()) / 120
        area = obj
        while area is not None:
            if isinstance(area, QAbstractScrollArea):
                bar = area.verticalScrollBar() if shift else area.horizontalScrollBar()
                if bar.maximum() > bar.minimum():
                    step = area.viewport().height() * FAST_PAGES_PER_NOTCH if shift else SIDEWAYS_PIXELS_PER_NOTCH
                    bar.setValue(int(bar.value() - notches * step))
                    return True
            area = area.parentWidget()
        return False
