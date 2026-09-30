from __future__ import annotations

import base64
import hashlib
import hmac
from io import BytesIO
from threading import Condition, local
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from PIL import Image
import requests

from .models import RenderOptions


class StaticMapClient(Protocol):
    def fetch(
        self,
        center_lat: float,
        center_lon: float,
        options: RenderOptions,
        *,
        zoom: int | None = None,
        static_size: tuple[int, int] | None = None,
    ) -> bytes: ...


class GoogleStaticMapClient:
    base_url = "https://maps.googleapis.com/maps/api/staticmap"

    def __init__(self, api_key: str, signature_secret: str | None = None) -> None:
        self.api_key = api_key
        self.signature_secret = signature_secret
        self._local = local()
        self._sessions: list[requests.Session] = []
        self._condition = Condition()
        self._closed = False
        self._inflight = 0

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is not None:
            with self._condition:
                if self._closed:
                    raise RuntimeError("Google Static Map client is closed.")
            return session
        with self._condition:
            if self._closed:
                raise RuntimeError("Google Static Map client is closed.")
            session = requests.Session()
            self._local.session = session
            self._sessions.append(session)
        return session

    def close(self) -> None:
        with self._condition:
            self._closed = True
            while self._inflight:
                self._condition.wait()
            sessions = self._sessions[:]
            self._sessions.clear()
        for session in sessions:
            session.close()

    def fetch(
        self,
        center_lat: float,
        center_lon: float,
        options: RenderOptions,
        *,
        zoom: int | None = None,
        static_size: tuple[int, int] | None = None,
    ) -> bytes:
        size_w, size_h = static_size or options.static_size
        params = {
            "center": f"{center_lat:.7f},{center_lon:.7f}",
            "zoom": str(zoom if zoom is not None else options.zoom),
            "size": f"{size_w}x{size_h}",
            "scale": str(options.scale),
            "maptype": options.map_type,
            "format": "png",
            "key": self.api_key,
        }
        url = f"{self.base_url}?{urlencode(params)}"
        if self.signature_secret:
            url = self._sign_url(url)
        session = self._session()
        with self._condition:
            if self._closed:
                raise RuntimeError("Google Static Map client is closed.")
            self._inflight += 1
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        finally:
            with self._condition:
                self._inflight -= 1
                self._condition.notify_all()

    def _sign_url(self, url: str) -> str:
        split = urlsplit(url)
        path_and_query = f"{split.path}?{split.query}"
        decoded_key = base64.urlsafe_b64decode(self.signature_secret)
        signature = hmac.new(decoded_key, path_and_query.encode("utf-8"), hashlib.sha1).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).decode("utf-8")
        separator = "&" if split.query else "?"
        return f"{url}{separator}signature={encoded_signature}"


class SolidColorMapClient:
    """Small test helper that returns a valid in-memory PNG for every map request."""

    def __init__(self, color: tuple[int, int, int] = (232, 237, 242)) -> None:
        self.color = color
        self.requests = 0

    def close(self) -> None:
        pass

    def fetch(
        self,
        center_lat: float,
        center_lon: float,
        options: RenderOptions,
        *,
        zoom: int | None = None,
        static_size: tuple[int, int] | None = None,
    ) -> bytes:
        self.requests += 1
        size_w, size_h = static_size or options.static_size
        image = Image.new("RGB", (size_w * options.scale, size_h * options.scale), self.color)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

