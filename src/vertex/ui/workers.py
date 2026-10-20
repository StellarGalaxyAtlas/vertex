"""Running blocking work off the UI thread and getting the result back on it.

Qt widgets may only be touched from the thread that created them. `run`
executes a function on a worker thread and delivers its result (or exception)
to callbacks on the UI thread through a queued signal — the single pattern
every background job in the app goes through.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vertex")


class _Bridge(QObject):
    deliver = Signal(object, object)    # callback, value

    def __init__(self):
        super().__init__()
        self.deliver.connect(self._call, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def _call(callback, value):
        try:
            callback(value)
        except RuntimeError as exc:
            # A widget deleted while its job ran: nothing left to update.
            if "deleted" not in str(exc) and "already" not in str(exc):
                raise


_bridge: _Bridge | None = None


def bridge() -> _Bridge:
    """Created lazily, on first use, which is always on the UI thread."""
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
    return _bridge


def post(callback: Callable[[Any], None], value: Any = None) -> None:
    """Call `callback(value)` on the UI thread. Safe from any thread."""
    bridge().deliver.emit(callback, value)


def run(fn: Callable[[], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        executor: ThreadPoolExecutor | None = None) -> Future:
    """Run `fn()` on a worker; deliver its result or exception on the UI thread."""
    bridge()

    def settled(future: Future):
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            if on_error is not None:
                post(on_error, error)
            else:
                post(_reraise, error)
        elif on_done is not None:
            post(on_done, future.result())

    future = (executor or _pool).submit(fn)
    future.add_done_callback(settled)
    return future


def _reraise(error: BaseException) -> None:
    raise error


def serial_executor(name: str) -> ThreadPoolExecutor:
    """One worker thread, so jobs on it run in order — for the recorder and the like."""
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)


class Cancel(threading.Event):
    """A cancellation flag a worker checks."""
