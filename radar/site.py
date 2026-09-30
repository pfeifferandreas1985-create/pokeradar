"""Schreibt die Daten fürs Dashboard (docs/data)."""
from __future__ import annotations

from .common import SITE_DATA, Config, iso, now, read_json, write_json
from .news import DEALS, MARKTNEWS, PRODUKTE

STATUS = SITE_DATA / "status.json"


def bauen(cfg: Config, info: dict) -> None:
    produkte = sorted(read_json(PRODUKTE, {}).values(),
                      key=lambda p: p.get("aktualisiert", p["erstmals"]), reverse=True)
    for p in produkte:
        p.pop("gemeldet", None)
    write_json(SITE_DATA / "radar.json", {
        "konfig": cfg.public(),
        "produkte": produkte,
        "deals": read_json(DEALS, []),
        "marktnews": read_json(MARKTNEWS, []),
    })
    alt = read_json(STATUS, {})
    alt.update({k: v for k, v in info.items() if v is not None})
    alt["lauf"] = iso(now())
    write_json(STATUS, alt)
