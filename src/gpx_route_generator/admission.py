from __future__ import annotations

from contextlib import AbstractContextManager
from collections import deque
from threading import Condition
from typing import Self


class _AdmissionToken(AbstractContextManager["_AdmissionToken"]):
    def __init__(self, admission: RenderAdmission, sequence: int) -> None:
        self._admission = admission
        self._sequence = sequence
        self._released = False

    @property
    def sequence(self) -> int:
        return self._sequence

    def __enter__(self) -> Self:
        self._admission._activate(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self._released:
            self._released = True
            self._admission._release(self)


class RenderAdmission:
    def __init__(self, *, max_active: int, max_queued: int) -> None:
        if max_active < 1:
            raise ValueError("MAX_ACTIVE_RENDERS must be at least one.")
        if max_queued < 0:
            raise ValueError("MAX_QUEUED_RENDERS must be zero or greater.")
        self._condition = Condition()
        self._max_active = max_active
        self._max_queued = max_queued
        self._active = 0
        self._queued = 0
        self._next_sequence = 0
        self._waiters: deque[_AdmissionToken] = deque()

    def enqueue(self) -> _AdmissionToken | None:
        with self._condition:
            if self._active + self._queued >= self._max_active + self._max_queued:
                return None
            token = _AdmissionToken(self, self._next_sequence)
            self._next_sequence += 1
            self._queued += 1
            self._waiters.append(token)
            return token

    def _activate(self, token: _AdmissionToken) -> None:
        with self._condition:
            while self._waiters[0] is not token or self._active >= self._max_active:
                self._condition.wait()
            self._waiters.popleft()
            self._queued -= 1
            self._active += 1

    def _release(self, token: _AdmissionToken) -> None:
        del token
        with self._condition:
            self._active -= 1
            self._condition.notify_all()

    def cancel(self, token: _AdmissionToken) -> None:
        with self._condition:
            if token._released:
                return
            token._released = True
            try:
                self._waiters.remove(token)
            except ValueError:
                self._active -= 1
            else:
                self._queued -= 1
            self._condition.notify_all()

    @property
    def capacity(self) -> dict[str, int]:
        return {"active": self._max_active, "queued": self._max_queued}

    def snapshot(self) -> dict[str, int]:
        with self._condition:
            return {"active": self._active, "queued": self._queued}
