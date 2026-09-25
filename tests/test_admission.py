from __future__ import annotations

from threading import Event, Thread
import time

import pytest

from gpx_route_generator.admission import RenderAdmission


def test_admission_accepts_active_and_queued_capacity() -> None:
    admission = RenderAdmission(max_active=1, max_queued=2)

    first = admission.enqueue()
    second = admission.enqueue()
    third = admission.enqueue()

    assert first is not None
    assert second is not None
    assert third is not None
    assert admission.snapshot() == {"active": 0, "queued": 3}


def test_admission_rejects_when_active_and_queue_are_full() -> None:
    admission = RenderAdmission(max_active=1, max_queued=2)
    tokens = [admission.enqueue() for _ in range(3)]

    assert admission.enqueue() is None
    assert all(token is not None for token in tokens)


def test_admission_counts_waiting_tokens_against_queue_capacity() -> None:
    admission = RenderAdmission(max_active=1, max_queued=1)
    first = admission.enqueue()
    second = admission.enqueue()
    assert first is not None and second is not None
    waiting = Event()

    def wait_for_slot() -> None:
        waiting.set()
        with second:
            pass

    with first:
        thread = Thread(target=wait_for_slot)
        thread.start()
        assert waiting.wait(timeout=0.2)
        time.sleep(0.02)
        assert admission.snapshot() == {"active": 1, "queued": 1}
        assert admission.enqueue() is None
    thread.join(timeout=1)


def test_admission_starts_queued_work_in_fifo_order() -> None:
    admission = RenderAdmission(max_active=1, max_queued=2)
    first = admission.enqueue()
    second = admission.enqueue()
    third = admission.enqueue()
    assert first is not None and second is not None and third is not None
    order: list[int] = []

    def acquire(token: object, value: int) -> None:
        with token:  # type: ignore[attr-defined]
            order.append(value)
            time.sleep(0.01)

    with first:
        second_thread = Thread(target=acquire, args=(second, 2))
        third_thread = Thread(target=acquire, args=(third, 3))
        second_thread.start()
        third_thread.start()
        time.sleep(0.02)
    second_thread.join(timeout=1)
    third_thread.join(timeout=1)

    assert order == [2, 3]


def test_admission_starts_queued_work_after_active_release() -> None:
    admission = RenderAdmission(max_active=1, max_queued=1)
    first = admission.enqueue()
    second = admission.enqueue()
    assert first is not None and second is not None

    started = Event()
    acquired: list[object] = []

    def wait_for_slot() -> None:
        with second:
            started.set()
            acquired.append(second)

    with first:
        thread = Thread(target=wait_for_slot)
        thread.start()
        assert not started.wait(timeout=0.05)
    assert started.wait(timeout=0.5)
    thread.join(timeout=1)
    assert acquired == [second]
    assert admission.snapshot() == {"active": 0, "queued": 0}


def test_admission_releases_slot_when_context_exits_after_failure() -> None:
    admission = RenderAdmission(max_active=1, max_queued=0)
    token = admission.enqueue()
    assert token is not None

    with pytest.raises(RuntimeError):
        with token:
            raise RuntimeError("render failed")

    assert admission.snapshot() == {"active": 0, "queued": 0}
    assert admission.enqueue() is not None


def test_admission_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="MAX_ACTIVE_RENDERS"):
        RenderAdmission(max_active=0, max_queued=1)
    with pytest.raises(ValueError, match="MAX_QUEUED_RENDERS"):
        RenderAdmission(max_active=1, max_queued=-1)
