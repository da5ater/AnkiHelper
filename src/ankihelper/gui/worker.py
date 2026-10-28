import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as error:  # surfaced in the UI instead of killing the worker thread
            traceback.print_exc()
            self.signals.failed.emit(str(error))
        else:
            self.signals.done.emit(result)


_running: set[_Task] = set()


def run_async(fn: Callable[[], object], on_done: Callable[[object], None], on_error: Callable[[str], None]) -> None:
    """Run a slow call (an agent, AnkiConnect) off the UI thread and hand the result back on it."""
    task = _Task(fn)
    task.setAutoDelete(False)
    _running.add(task)
    task.signals.done.connect(on_done)
    task.signals.failed.connect(on_error)
    task.signals.done.connect(lambda _: _running.discard(task))
    task.signals.failed.connect(lambda _: _running.discard(task))
    QThreadPool.globalInstance().start(task)
