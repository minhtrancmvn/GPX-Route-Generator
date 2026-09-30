from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PIL import Image

import gpx_route_generator.renderer as renderer


def test_concurrent_avatar_first_use_builds_cache_once(monkeypatch) -> None:
    renderer._AVATAR_CACHE.clear()
    calls = 0
    real_open = Image.open

    def counted_open(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(renderer.Image, "open", counted_open)

    with ThreadPoolExecutor(max_workers=8) as executor:
        images = list(executor.map(lambda _: renderer.make_arrow(54, "mt15"), range(8)))

    assert calls == 1
    assert len({id(image) for image in images}) == 8
    images[0].close()
    assert images[1].getbbox() is not None
