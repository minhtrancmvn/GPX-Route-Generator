from __future__ import annotations

from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace

import pytest

from gpx_route_generator import renderer
from gpx_route_generator.models import RenderOptions, RoutePoint


class BlockingStdin:
    def __init__(self) -> None:
        self.closed = False
        self.write_started = Event()
        self.release = Event()
        self.writes: list[bytes] = []

    def write(self, value: bytes) -> int:
        self.write_started.set()
        self.release.wait()
        if self.closed:
            raise BrokenPipeError("stdin closed")
        self.writes.append(bytes(value))
        return len(value)

    def close(self) -> None:
        self.closed = True
        self.release.set()


class FakeProcess:
    def __init__(self, stdin: BlockingStdin) -> None:
        self.stdin = stdin
        self.stderr = BytesIO()
        self.returncode: int | None = None
        self.killed = False

    @property
    def pid(self) -> int:
        return 12345

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self.stdin.close()

    def terminate(self) -> None:
        self.returncode = -15
        self.stdin.close()


@pytest.fixture
def minimal_render(monkeypatch: pytest.MonkeyPatch) -> RenderOptions:
    options = RenderOptions(duration_seconds=5, fps=1)
    point = RoutePoint(1.0, 2.0)
    camera_state = SimpleNamespace(zoom=14)
    plan = SimpleNamespace(camera_states=[camera_state], map_request_count=1)
    monkeypatch.setattr(renderer, "validate_render_options", lambda _options: None)
    monkeypatch.setattr(renderer, "resample_by_distance", lambda *_args: ([point], [0.0]))
    monkeypatch.setattr(renderer, "dynamic_camera_states", lambda *_args, **_kwargs: [camera_state])
    monkeypatch.setattr(renderer, "build_map_segment_plan", lambda *_args: plan)
    monkeypatch.setattr(renderer, "lat_lon_to_world_pixel", lambda *_args: (0.0, 0.0))
    monkeypatch.setattr(renderer, "_prefetch_segment_images", lambda *_args: {})
    monkeypatch.setattr(renderer, "_render_video_frame", lambda **_kwargs: b"frame")
    monkeypatch.setattr(renderer, "_frame_worker_count", lambda: 1)
    monkeypatch.setattr(renderer, "_FRAME_PROGRESS_TIMEOUT_SECONDS", 0.05, raising=False)
    monkeypatch.setattr(renderer, "_PROCESS_TERM_GRACE_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(renderer, "_READER_JOIN_TIMEOUT_SECONDS", 0.01, raising=False)
    return options


def test_render_times_out_when_child_never_reads_stdin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    minimal_render: RenderOptions,
) -> None:
    stdin = BlockingStdin()
    process = FakeProcess(stdin)
    progress: list[int] = []
    monkeypatch.setattr(renderer.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(renderer.os, "killpg", lambda _pid, _signal: process.kill())
    failures: list[BaseException] = []

    def render() -> None:
        try:
            renderer.render_route_video(
                [],
                minimal_render,
                tmp_path / "video.mp4",
                object(),
                progress_callback=lambda current, _total, _maps: progress.append(current),
            )
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=render)
    started = monotonic()
    thread.start()
    try:
        assert stdin.write_started.wait(timeout=0.2)
        thread.join(timeout=0.2)
        assert not thread.is_alive()
    finally:
        stdin.release.set()
        thread.join(timeout=1)

    assert monotonic() - started < 0.3
    assert process.killed
    assert len(failures) == 1
    assert "timed out" in str(failures[0]).lower()
    assert progress == []


def test_render_writes_complete_large_frame_before_reporting_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    minimal_render: RenderOptions,
) -> None:
    class PartialStdin(BlockingStdin):
        def write(self, value: bytes) -> int:
            self.writes.append(bytes(value[:2]))
            return min(2, len(value))

    stdin = PartialStdin()
    process = FakeProcess(stdin)
    frame = b"frame-larger-than-pipe"
    progress: list[int] = []
    monkeypatch.setattr(renderer.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(renderer, "_render_video_frame", lambda **_kwargs: frame)

    def successful_wait(timeout: float | None = None) -> int:
        (tmp_path / ".video.partial.mp4").write_bytes(b"video")
        process.returncode = 0
        return 0

    process.wait = successful_wait
    renderer.render_route_video(
        [],
        minimal_render,
        tmp_path / "video.mp4",
        object(),
        progress_callback=lambda current, _total, _maps: progress.append(current),
    )

    assert b"".join(stdin.writes) == frame * minimal_render.frame_count
    assert progress == list(range(1, minimal_render.frame_count + 1))


def test_render_times_out_when_frame_producer_stalls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    minimal_render: RenderOptions,
) -> None:
    stdin = BlockingStdin()
    stdin.release.set()
    process = FakeProcess(stdin)
    started = Event()
    release = Event()
    monkeypatch.setattr(renderer.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(renderer.os, "killpg", lambda _pid, _signal: process.kill())

    def stalled_frame(**_kwargs: object) -> bytes:
        started.set()
        release.wait()
        return b"frame"

    monkeypatch.setattr(renderer, "_render_video_frame", stalled_frame)

    def release_worker() -> None:
        started.wait(timeout=0.2)
        Event().wait(0.1)
        release.set()

    releaser = Thread(target=release_worker)
    releaser.start()
    with pytest.raises(RuntimeError, match="timed out"):
        renderer.render_route_video([], minimal_render, tmp_path / "video.mp4", object())
    releaser.join(timeout=1)

    assert process.killed


def test_render_fails_if_descendant_keeps_stderr_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    minimal_render: RenderOptions,
) -> None:
    class BlockingStderr:
        def read(self, _size: int) -> bytes:
            Event().wait()
            return b""

    stdin = BlockingStdin()
    stdin.release.set()
    process = FakeProcess(stdin)
    process.stderr = BlockingStderr()
    monkeypatch.setattr(renderer.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(renderer.os, "killpg", lambda _pid, _signal: process.kill())

    def successful_wait(timeout: float | None = None) -> int:
        (tmp_path / ".video.partial.mp4").write_bytes(b"video")
        process.returncode = 0
        return 0

    process.wait = successful_wait
    started = monotonic()
    with pytest.raises(RuntimeError, match="stderr reader"):
        renderer.render_route_video([], minimal_render, tmp_path / "video.mp4", object())

    assert monotonic() - started < 0.2
    assert not (tmp_path / "video.mp4").exists()
    assert process.killed


def test_render_cleans_up_when_thread_start_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    minimal_render: RenderOptions,
) -> None:
    stdin = BlockingStdin()
    stdin.release.set()
    process = FakeProcess(stdin)
    monkeypatch.setattr(renderer.subprocess, "Popen", lambda *_args, **_kwargs: process)
    real_thread = renderer.Thread

    class FailingThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._thread = real_thread(*args, **kwargs)

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(renderer, "Thread", FailingThread)
    monkeypatch.setattr(renderer.os, "killpg", lambda _pid, _signal: process.kill())

    with pytest.raises(RuntimeError, match="thread unavailable"):
        renderer.render_route_video([], minimal_render, tmp_path / "video.mp4", object())

    assert process.killed
    assert not (tmp_path / ".video.partial.mp4").exists()


def test_render_uses_mp4_suffix_for_partial_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    minimal_render: RenderOptions,
) -> None:
    stdin = BlockingStdin()
    stdin.release.set()
    process = FakeProcess(stdin)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        renderer.subprocess,
        "Popen",
        lambda command, **_kwargs: commands.append(command) or process,
    )

    def successful_wait(timeout: float | None = None) -> int:
        Path(commands[0][-1]).write_bytes(b"video")
        process.returncode = 0
        return 0

    process.wait = successful_wait
    renderer.render_route_video([], minimal_render, tmp_path / "video.mp4", object())

    assert commands[0][-1].endswith(".mp4")


def test_render_removes_partial_output_after_ffmpeg_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    minimal_render: RenderOptions,
) -> None:
    stdin = BlockingStdin()
    stdin.release.set()
    process = FakeProcess(stdin)
    monkeypatch.setattr(renderer.subprocess, "Popen", lambda *_args, **_kwargs: process)

    def failed_wait(timeout: float | None = None) -> int:
        (tmp_path / ".video.partial.mp4").write_bytes(b"partial")
        process.returncode = 1
        return 1

    process.wait = failed_wait
    with pytest.raises(RuntimeError, match="exit code 1"):
        renderer.render_route_video([], minimal_render, tmp_path / "video.mp4", object())

    assert not (tmp_path / ".video.partial.mp4").exists()
    assert not (tmp_path / "video.mp4").exists()
