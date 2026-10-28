"""Render document templates to PNG with headless Chromium (Playwright)."""

import base64
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from playwright.sync_api import sync_playwright

from synthetic.names_eval import CARD_COLOURS

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
FONT_PATH = TEMPLATES_DIR / "fonts" / "NotoSansDevanagari.ttf"


def id_groups(number: str) -> str:
    """'012345678901' -> '0123 4567 8901'."""
    return " ".join(number[i : i + 4] for i in range(0, len(number), 4))


def rupees(amount: int) -> str:
    """Indian digit grouping: 120000 -> '1,20,000'."""
    s = str(amount)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


class Renderer:
    """Use as a context manager; one browser page renders every document."""

    def __init__(self) -> None:
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
        )
        self.env.filters["id_groups"] = id_groups
        self.env.filters["rupees"] = rupees
        # The font is embedded as a data URI so rendering never depends on network or file-URL rules.
        self.base_context = {
            "font_b64": base64.b64encode(FONT_PATH.read_bytes()).decode("ascii"),
            "css": (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8"),
            # v2 ration card colour labels (unused by v1 cards)
            "card_colours": {k: v["colour"]._asdict() for k, v in CARD_COLOURS.items()},
        }

    def __enter__(self) -> "Renderer":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        self._page = self._browser.new_page(viewport={"width": 1300, "height": 1800}, device_scale_factor=1)
        return self

    def __exit__(self, *exc: object) -> None:
        self._browser.close()
        self._playwright.stop()

    def html(self, doc_type: str, fields: dict[str, Any]) -> str:
        return self.env.get_template(f"{doc_type}.html").render(f=fields, **self.base_context)

    def render(self, doc_type: str, fields: dict[str, Any]) -> bytes:
        self._page.set_content(self.html(doc_type, fields), wait_until="load")
        self._page.evaluate("document.fonts.ready.then(() => true)")
        return self._page.locator(".doc").screenshot(type="png")
