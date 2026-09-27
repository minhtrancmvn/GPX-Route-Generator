from __future__ import annotations

from gpx_route_generator.rate_limit import SlidingWindowLimiter


def test_limiter_allows_requests_within_limit() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)

    assert limiter.check("client", now=0) is None
    assert limiter.check("client", now=1) is None


def test_limiter_returns_retry_after_when_limit_reached() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    limiter.check("client", now=10)
    limiter.check("client", now=20)

    assert limiter.check("client", now=30) == 40


def test_limiter_allows_after_window_expires() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("client", now=10)

    assert limiter.check("client", now=70) is None


def test_limiter_evicts_idle_client_keys() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("expired", now=0)

    limiter.check("current", now=61)

    assert limiter.tracked_keys == 1


def test_limiter_tracks_clients_separately() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.check("first", now=0)

    assert limiter.check("second", now=1) is None
