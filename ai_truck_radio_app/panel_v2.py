# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import html
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict


UI_DIR = Path(__file__).with_name("ui")


@lru_cache(maxsize=None)
def _text(name: str) -> str:
    return (UI_DIR / name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _data_uri(name: str, mime: str) -> str:
    payload = base64.b64encode((UI_DIR / name).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


@lru_cache(maxsize=1)
def _vendor_css() -> str:
    icons = _text("vendor/bootstrap-icons.min.css")
    icons = re.sub(r"@font-face\{[^}]+\}", "", icons, count=1)
    icon_font = _data_uri("vendor/bootstrap-icons.woff2", "font/woff2")
    cyrillic = _data_uri("vendor/inter-cyrillic-wght-normal.woff2", "font/woff2")
    latin = _data_uri("vendor/inter-latin-wght-normal.woff2", "font/woff2")
    return (
        "@font-face{font-family:'bootstrap-icons';font-style:normal;font-weight:400;"
        f"font-display:block;src:url('{icon_font}') format('woff2');}}"
        "@font-face{font-family:'Inter Variable';font-style:normal;font-weight:100 900;font-display:swap;"
        f"src:url('{cyrillic}') format('woff2-variations');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116;}}"
        "@font-face{font-family:'Inter Variable';font-style:normal;font-weight:100 900;font-display:swap;"
        f"src:url('{latin}') format('woff2-variations');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD;}}"
        + icons
    )


def _json_for_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_panel_v2(
    *,
    cfg: Dict[str, Any],
    snap: Dict[str, Any],
    default_config: Dict[str, Any],
    app_name: str,
    app_version: str,
    settings: Dict[str, str],
    checkbox_keys: list[str],
) -> str:
    bootstrap = {
        "app": {"name": app_name, "version": app_version},
        "config": cfg,
        "defaults": default_config,
        "status": snap,
        "settingsHtml": settings,
        "checkboxKeys": checkbox_keys,
    }
    page = _text("panel.html")
    replacements = {
        "__APP_TITLE__": html.escape(app_name, quote=True),
        "__VENDOR_CSS__": _vendor_css(),
        "__PANEL_CSS__": _text("panel.css"),
        "__BOOTSTRAP_JSON__": _json_for_script(bootstrap),
        "__PANEL_JS__": _text("panel.js"),
    }
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    return page
