from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import moves
from ..config import Config
from . import theme
from .common import Page, card, label, pill

MODE_LABELS = {moves.CHANGE: ("changes the card", theme.AMBER), moves.ADD: ("adds new cards", theme.CYAN)}


class MovesPage(Page):
    """Every move with how often it is used, its instruction, its last uses and an undo; suggestions on top."""

    changed = Signal()

    def __init__(self, cfg: Config):
        super().__init__("Moves", "The one-click things you do to a card. Save new ones from a conversation in Anki (⭐); teach them when you correct a result.", theme.VIOLET)
        self.cfg = cfg
        body = QWidget()
        self.column = QVBoxLayout(body)
        self.column.setContentsMargins(0, 0, 8, 0)
        self.column.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.layout_.addWidget(scroll, 1)
        self.refresh()

    def shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        while self.column.count():
            item = self.column.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        suggestions = moves.suggestions()
        if suggestions:
            self.column.addWidget(label("SUGGESTED FROM YOUR CONVERSATIONS", "fieldLabel"))
            for index, item in enumerate(suggestions):
                self.column.addWidget(self._suggestion(index, item))
            self.column.addWidget(label("YOUR MOVES, MOST USED FIRST", "fieldLabel"))
        for move in moves.ordered():
            self.column.addWidget(self._move(move))
        self.column.addStretch()

    def _suggestion(self, index: int, item: dict) -> QWidget:
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 10, 10)
        title = label(f"{item['icon']} {item['name']}")
        title.setStyleSheet("font-weight: 800; font-size: 15px;")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addWidget(pill(MODE_LABELS[item["mode"]][0], MODE_LABELS[item["mode"]][1]))
        head.addStretch()
        layout.addLayout(head)
        text = QPlainTextEdit(item["instruction"])
        text.setFixedHeight(70)
        layout.addWidget(text)
        if item.get("evidence"):
            layout.addWidget(label(item["evidence"], "faint", wrap=True))
        row = QHBoxLayout()
        row.addStretch()
        dismiss = QPushButton("✕ Not this")
        dismiss.clicked.connect(lambda: (moves.dismiss_suggestion(index), self.refresh()))
        add = QPushButton("＋ Add move")
        add.setObjectName("primary")
        add.clicked.connect(lambda: (moves.accept_suggestion(index, text.toPlainText().strip()), self.refresh(), self.changed.emit()))
        row.addWidget(dismiss)
        row.addWidget(add)
        layout.addLayout(row)
        return frame

    def _move(self, move: moves.Move) -> QWidget:
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(6)
        head = QHBoxLayout()
        title = label(f"{move.icon} {move.name}")
        title.setStyleSheet("font-weight: 800; font-size: 15px;")
        head.addWidget(title)
        head.addWidget(pill(f"used {move.uses}×", theme.GREEN if move.uses else theme.FAINT))
        head.addWidget(pill(*MODE_LABELS[move.mode]))
        if move.builtin:
            head.addWidget(pill("built in", theme.FAINT))
        head.addStretch()
        layout.addLayout(head)
        text = QPlainTextEdit(move.instruction)
        text.setFixedHeight(70)
        layout.addWidget(text)
        if move.examples:
            lines = [f"• {e['before'].get('question', '')[:70]}  →  {e['result'].get('question', '')[:90]}" for e in reversed(move.examples)]
            examples = label("Last results you kept:\n" + "\n".join(lines), "faint", wrap=True)
            layout.addWidget(examples)
        row = QHBoxLayout()
        row.addStretch()
        if move.history:
            undo = QPushButton("↶ Undo last change")
            undo.setToolTip(f"Back to: {move.history[-1]['instruction']}")
            undo.clicked.connect(lambda: (moves.undo(move.id), self.refresh()))
            row.addWidget(undo)
        if not move.builtin:
            delete = QPushButton("🗑 Delete")
            delete.clicked.connect(lambda: (moves.delete(move.id), self.refresh(), self.changed.emit()))
            row.addWidget(delete)
        save = QPushButton("Save instruction")
        save.setEnabled(False)
        text.textChanged.connect(lambda: save.setEnabled(text.toPlainText().strip() != move.instruction))
        save.clicked.connect(lambda: (moves.update_instruction(move.id, text.toPlainText()), self.refresh()))
        row.addWidget(save)
        layout.addLayout(row)
        return frame
