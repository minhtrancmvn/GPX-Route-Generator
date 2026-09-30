from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from threading import Barrier, Event, Lock, Thread

import gpx_route_generator.maps as maps_module
from gpx_route_generator.maps import GoogleStaticMapClient
from gpx_route_generator.models import RenderOptions


class FakeResponse:
    content = b"png"

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    def __init__(self, created: list["FakeSession"], lock: Lock) -> None:
        self.closed = False
        self.calls = 0
        with lock:
            created.append(self)

    def get(self, url: str, timeout: int) -> FakeResponse:
        self.calls += 1
        return FakeResponse()

    def close(self) -> None:
        self.closed = True


def test_map_client_reuses_session_on_same_thread(monkeypatch) -> None:
    created: list[FakeSession] = []
    lock = Lock()
    monkeypatch.setattr(maps_module.requests, "Session", lambda: FakeSession(created, lock))
    client = GoogleStaticMapClient("key")
    options = RenderOptions()

    client.fetch(1, 2, options)
    client.fetch(1, 2, options)

    assert len(created) == 1
    assert created[0].calls == 2


def test_map_client_uses_distinct_sessions_across_threads(monkeypatch) -> None:
    created: list[FakeSession] = []
    lock = Lock()
    monkeypatch.setattr(maps_module.requests, "Session", lambda: FakeSession(created, lock))
    client = GoogleStaticMapClient("key")
    options = RenderOptions()

    barrier = Barrier(2)

    def fetch(_: int) -> bytes:
        barrier.wait()
        return client.fetch(1, 2, options)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(fetch, range(2)))

    assert len(created) == 2


def test_map_client_close_waits_for_inflight_fetch(monkeypatch) -> None:
    started = Event()
    release = Event()
    closed = Event()

    class BlockingSession(FakeSession):
        def get(self, url: str, timeout: int) -> FakeResponse:
            started.set()
            release.wait(timeout=1)
            return FakeResponse()

        def close(self) -> None:
            super().close()
            closed.set()

    created: list[FakeSession] = []
    lock = Lock()
    monkeypatch.setattr(maps_module.requests, "Session", lambda: BlockingSession(created, lock))
    client = GoogleStaticMapClient("key")
    fetch_thread = Thread(target=lambda: client.fetch(1, 2, RenderOptions()))
    fetch_thread.start()
    assert started.wait(timeout=0.5)
    close_thread = Thread(target=client.close)
    close_thread.start()

    assert not closed.wait(timeout=0.05)
    release.set()
    fetch_thread.join(timeout=1)
    close_thread.join(timeout=1)
    assert closed.is_set()


def test_map_client_rejects_fetch_after_close(monkeypatch) -> None:
    created: list[FakeSession] = []
    lock = Lock()
    monkeypatch.setattr(maps_module.requests, "Session", lambda: FakeSession(created, lock))
    client = GoogleStaticMapClient("key")
    client.close()

    with pytest.raises(RuntimeError, match="closed"):
        client.fetch(1, 2, RenderOptions())


def test_map_client_close_closes_all_thread_sessions(monkeypatch) -> None:
    created: list[FakeSession] = []
    lock = Lock()
    monkeypatch.setattr(maps_module.requests, "Session", lambda: FakeSession(created, lock))
    client = GoogleStaticMapClient("key")
    options = RenderOptions()

    barrier = Barrier(2)

    def fetch(_: int) -> bytes:
        barrier.wait()
        return client.fetch(1, 2, options)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(fetch, range(2)))
    client.close()

    assert created
    assert all(session.closed for session in created)
