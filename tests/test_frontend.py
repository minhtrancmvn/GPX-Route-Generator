from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gpx_route_generator.app import create_app
from gpx_route_generator.config import Settings


class FrontendParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_head = False
        self.head_tag: str | None = None
        self.stray_head_text: list[str] = []
        self.elements: list[dict[str, str | None]] = []
        self.controls: list[dict[str, str | None]] = []
        self.select_options: dict[str, list[dict[str, str | None]]] = {}
        self.in_form = False
        self.select_name: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = dict(attrs)
        self.elements.append(element)
        if tag == "head":
            self.in_head = True
        elif self.in_head and tag in {"title", "script", "style"}:
            self.head_tag = tag
        if tag == "form" and element.get("id") == "render-form":
            self.in_form = True
        if not self.in_form:
            return
        if tag in {"input", "select"}:
            self.controls.append(element)
        if tag == "select":
            self.select_name = element.get("name")
            if self.select_name:
                self.select_options[self.select_name] = []
        elif tag == "option" and self.select_name:
            self.select_options[self.select_name].append(element)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False
        if tag == self.head_tag:
            self.head_tag = None
        if tag == "form":
            self.in_form = False
        if tag == "select":
            self.select_name = None

    def handle_data(self, data: str) -> None:
        if self.in_head and self.head_tag is None and data.strip():
            self.stray_head_text.append(data.strip())


@pytest.fixture
def root_html(tmp_path: Path) -> Iterator[str]:
    settings = Settings(
        google_maps_api_key=None,
        google_maps_signature_secret=None,
        jobs_dir=tmp_path / "jobs",
    )
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/")
        assert response.status_code == 200
        yield response.text


@pytest.fixture
def document(root_html: str) -> FrontendParser:
    parser = FrontendParser()
    parser.feed(root_html)
    return parser


def test_rendered_root_head_contains_no_raw_text(document: FrontendParser) -> None:
    assert not document.stray_head_text


def test_head_validator_detects_text_after_stylesheet(root_html: str) -> None:
    parser = FrontendParser()
    parser.feed(root_html.replace("</head>", "Unexpected template text</head>", 1))
    assert parser.stray_head_text == ["Unexpected template text"]


def test_rendered_root_all_js_selector_ids_exist_exactly_once(document: FrontendParser) -> None:
    source = Path(__file__).resolve().parents[1] / "src/gpx_route_generator/static/app.js"
    selector_ids = set(re.findall(r'''querySelector\(\s*["']#([\w-]+)["']\s*\)''', source.read_text()))
    assert len(selector_ids) >= 20
    counts = Counter(element["id"] for element in document.elements if "id" in element)
    assert {selector_id: counts[selector_id] for selector_id in selector_ids} == dict.fromkeys(selector_ids, 1)


def test_rendered_root_payload_controls_and_defaults_preserved(document: FrontendParser) -> None:
    controls = {control["name"]: control for control in document.controls if "name" in control}
    assert set(controls) == {
        "gpx_file", "output_format", "duration_seconds", "fps", "map_type", "trail_color",
        "avatar_id", "trail_width", "arrow_size", "show_progress_bar", "show_distance",
        "show_speed", "show_elevation",
    }
    assert controls["gpx_file"]["type"] == "file"
    assert "required" in controls["gpx_file"]
    formats = [control for control in document.controls if control.get("name") == "output_format"]
    assert {control["value"] for control in formats} == {"landscape", "portrait"}
    assert [control["value"] for control in formats if "checked" in control] == ["landscape"]
    for name, value, minimum, maximum in (
        ("duration_seconds", "10", "5", "30"),
        ("fps", "24", "1", "60"),
        ("trail_width", "6", "1", "24"),
        ("arrow_size", "54", "16", "160"),
    ):
        assert controls[name]["value"] == value
        assert controls[name]["min"] == minimum
        assert controls[name]["max"] == maximum
    assert "required" in controls["duration_seconds"]
    assert "required" in controls["fps"]
    assert controls["trail_color"]["value"] == "#ff2f2f"
    assert {option["value"] for option in document.select_options["map_type"]} == {
        "roadmap", "satellite", "terrain", "hybrid",
    }
    for name, default in (("map_type", "roadmap"), ("avatar_id", "default")):
        assert [option["value"] for option in document.select_options[name] if "selected" in option] == [default]
    for name in ("show_progress_bar", "show_distance", "show_speed", "show_elevation"):
        assert controls[name]["type"] == "checkbox"
        assert "checked" in controls[name]


def test_rendered_root_accessible_progressbar_exists(document: FrontendParser) -> None:
    progressbars = [element for element in document.elements if element.get("role") == "progressbar"]
    assert len(progressbars) == 1
    progressbar = progressbars[0]
    assert progressbar.get("aria-label") or progressbar.get("aria-labelledby")
    assert progressbar.get("aria-valuemin") == "0"
    assert progressbar.get("aria-valuemax") == "100"
    assert progressbar.get("aria-valuenow") == "0"


def test_rendered_root_accessible_status_message_exists(document: FrontendParser) -> None:
    messages = [element for element in document.elements if element.get("id") == "message"]
    assert len(messages) == 1
    assert messages[0].get("role") == "status"
