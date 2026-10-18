"""Schreibt die Daten fürs Dashboard (docs/data)."""
from __future__ import annotations

from datetime import timedelta

from .common import SITE_DATA, Config, iso, now, read_json, write_json
from .news import DEALS, MARKTNEWS, PRODUKTE, offene_hinweise

STATUS = SITE_DATA / "status.json"


def bauen(cfg: Config, info: dict) -> None:
    produkte = sorted(read_json(PRODUKTE, {}).values(),
                      key=lambda p: p.get("aktualisiert", p["erstmals"]), reverse=True)
    for p in produkte:
        p.pop("gemeldet", None)
        if p.get("set") and p["set"].lower() not in p["name"].lower():
            p["name"] = f"{p['set']} {p['name']}"[:100]
    write_json(SITE_DATA / "radar.json", {
        "konfig": cfg.public(),
        "produkte": produkte,
        "deals": read_json(DEALS, []),
        "marktnews": read_json(MARKTNEWS, []),
        "hinweise": [{k: h[k] for k in ("id", "titel", "link", "quelle", "datum", "status", "typ", "sprache", "produkt")}
                     for h in offene_hinweise(timedelta(days=7))][:20],
    })
    alt = read_json(STATUS, {})
    alt.update({k: v for k, v in info.items() if v is not None})
    alt["lauf"] = iso(now())
    write_json(STATUS, alt)
