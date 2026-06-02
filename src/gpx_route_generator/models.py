from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OutputFormat(str, Enum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"



FORMAT_DIMENSIONS: dict[OutputFormat, tuple[int, int]] = {
    OutputFormat.LANDSCAPE: (1280, 720),
    OutputFormat.PORTRAIT: (720, 1280),
}


FORMAT_STATIC_SIZES: dict[OutputFormat, tuple[int, int]] = {
    OutputFormat.LANDSCAPE: (640, 360),
    OutputFormat.PORTRAIT: (360, 640),
}


VALID_MAP_TYPES = {"roadmap", "satellite", "terrain", "hybrid"}
AVAILABLE_AVATARS = {
    "default": "Default",
    "mt15": "MT-15",
}


@dataclass(frozen=True)
class RoutePoint:
    lat: float
    lon: float
    elevation: float | None = None
    time: datetime | None = None


@dataclass(frozen=True)
class RenderOptions:
    output_format: OutputFormat = OutputFormat.LANDSCAPE
    duration_seconds: float = 10.0
    fps: int = 24
    zoom: int = 18
    map_type: str = "roadmap"
    trail_color: str = "#ff2f2f"
    trail_width: int = 6
    arrow_size: int = 54
    avatar_id: str = "default"
    show_progress_bar: bool = True
    show_distance: bool = True
    show_speed: bool = True
    show_elevation: bool = True

    @property
    def width(self) -> int:
        return FORMAT_DIMENSIONS[self.output_format][0]

    @property
    def height(self) -> int:
        return FORMAT_DIMENSIONS[self.output_format][1]

    @property
    def static_size(self) -> tuple[int, int]:
        return FORMAT_STATIC_SIZES[self.output_format]

    @property
    def scale(self) -> int:
        return 2

    @property
    def frame_count(self) -> int:
        return int(round(self.duration_seconds * self.fps))

    @property
    def estimated_map_requests(self) -> int:
        return self.frame_count


def validate_render_options(options: RenderOptions) -> None:
    if not 5 <= options.duration_seconds <= 30:
        raise ValueError("Duration must be between 5 and 30 seconds.")
    if not 1 <= options.fps <= 60:
        raise ValueError("FPS must be between 1 and 60.")
    if not 1 <= options.zoom <= 21:
        raise ValueError("Zoom must be between 1 and 21.")
    if options.map_type not in VALID_MAP_TYPES:
        raise ValueError("Map type must be roadmap, satellite, terrain, or hybrid.")
    if not 1 <= options.trail_width <= 24:
        raise ValueError("Trail width must be between 1 and 24 pixels.")
    if not 16 <= options.arrow_size <= 160:
        raise ValueError("Avatar size must be between 16 and 160 pixels.")
    if options.avatar_id not in AVAILABLE_AVATARS:
        raise ValueError("Avatar must be one of: " + ", ".join(AVAILABLE_AVATARS))
    if options.frame_count < 1:
        raise ValueError("Render must include at least one frame.")
