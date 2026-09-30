"""Markt-Lauf (täglich) und Abendübersicht."""
from __future__ import annotations

from datetime import timedelta

from . import market
from .common import DATA, SITE_DATA, Config, iso, log, now, read_json, write_json
from .news import DEALS, QUEUE
from .notify import SPRACH_LABEL, Ntfy
from .rating import baelle, bewerten

ALARME = DATA / "preisalarme.json"
MARKT_JSON = SITE_DATA / "market.json"


def _eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def _gewuenscht(p: dict, cfg: Config) -> bool:
    if p["typ"] not in cfg.produkte:
        return False
    return ("jp" in cfg.sprachen) if p["sprache"] == "jp" else bool({"de", "en"} & set(cfg.sprachen))


def markt_index() -> dict[int, dict]:
    return {p["id"]: p for p in read_json(MARKT_JSON, {}).get("produkte", [])}


def lauf(cfg: Config, ntfy: Ntfy) -> dict:
    produkte, stand = market.laden(cfg)
    neu_tag = market.schnappschuss(produkte, stand)
    market.katalog_speichern(produkte)
    items = market.auswerten(produkte, stand, cfg)
    tage = market.verlauf_tage(stand)
    for e in items:
        if e.get("ch7") is not None:
            e["rating"] = bewerten("markt", {}, e)

    # Preisalarme (einmal pro Produkt und Richtung innerhalb von 7 Tagen)
    gemerkt: dict[str, str] = read_json(ALARME, {})
    grenze = iso(now() - timedelta(days=7))
    gemerkt = {k: v for k, v in gemerkt.items() if v >= grenze}
    hoch, runter = [], []
    if neu_tag:
        for e in items:
            ch7 = e.get("ch7")
            if ch7 is None or not _gewuenscht(e, cfg) or abs(ch7) < cfg.alarm_prozent:
                continue
            richtung = "hoch" if ch7 > 0 else "runter"
            k = f"{e['id']}:{richtung}"
            if k in gemerkt:
                continue
            gemerkt[k] = iso(now())
            (hoch if ch7 > 0 else runter).append(e)
    for liste, titel, tag in ((hoch, "📈 Stark gestiegen", "chart_with_upwards_trend"),
                              (runter, "📉 Stark gefallen", "chart_with_downwards_trend")):
        if not liste:
            continue
        liste.sort(key=lambda e: abs(e["ch7"]), reverse=True)
        zeilen = []
        for e in liste[:5]:
            r = e["rating"]
            zeilen.append(f"{e['name']} ({SPRACH_LABEL[e['sprache']]})\n"
                          f"{_eur(e['trend'])} · {e['ch7']:+.0f} % in 7 Tagen · {baelle(r['sterne'])} {r['urteil']}\n"
                          + "\n".join(f"• {g}" for g in r["gruende"][:2]))
        rest = f"\n\n… und {len(liste) - 5} weitere" if len(liste) > 5 else ""
        ntfy.senden(f"{titel}: {len(liste)} {'Box' if len(liste) == 1 else 'Boxen'}",
                    "\n\n".join(zeilen) + rest, prio=4, tags=[tag], link=ntfy.dashboard or None)
    write_json(ALARME, gemerkt)

    felder = ("id", "name", "typ", "sprache", "set", "trend", "low", "ch7", "ch30", "ch90", "hoch",
              "spark", "seit", "rating")
    write_json(MARKT_JSON, {"stand": stand, "tage": tage,
                            "produkte": [{k: e.get(k) for k in felder} for e in items]}, compact=True)
    log.info("Markt: %d Produkte ≥ %s €, %d Tage Verlauf, %d Alarme",
             len(items), cfg.mindestpreis, tage, len(hoch) + len(runter))
    return {"markt_stand": stand, "markt_tage": tage}


def abend(cfg: Config, ntfy: Ntfy) -> None:
    if not cfg.abenduebersicht:
        return
    queue: list[dict] = read_json(QUEUE, [])
    deals = [d for d in read_json(DEALS, []) if d["datum"] >= iso(now() - timedelta(hours=24))
             and d["typ"] in cfg.produkte and d["sprache"] in cfg.sprachen]
    markt = [e for e in read_json(MARKT_JSON, {}).get("produkte", []) if e.get("ch7") is not None
             and _gewuenscht(e, cfg)]
    teile = []
    neu = [q for q in queue if q["art"] == "neu"]
    if neu:
        neu.sort(key=lambda q: q["sterne"], reverse=True)
        teile.append("✨ Neu auf dem Radar\n" + "\n".join(f"{baelle(q['sterne'])} {q['titel']}" for q in neu[:6]))
    if deals:
        deals.sort(key=lambda d: d["rating"]["sterne"], reverse=True)
        teile.append("💸 Angebote heute\n" + "\n".join(
            f"{baelle(d['rating']['sterne'])} {d['produkt']}"
            + (f" – {d['preis_eur']:.2f} €".replace(".", ",") if d.get("preis_eur") else "")
            + (f" (−{d['rabatt']:.0f} %)" if d.get("rabatt") and d["rabatt"] > 0 else "")
            for d in deals[:5]))
    if markt:
        top = sorted(markt, key=lambda e: e["ch7"], reverse=True)[:3]
        flop = sorted(markt, key=lambda e: e["ch7"])[:2]
        zeilen = [f"▲ {e['name']} {e['ch7']:+.0f} % · {_eur(e['trend'])}" for e in top if e["ch7"] > 2]
        zeilen += [f"▼ {e['name']} {e['ch7']:+.0f} % · {_eur(e['trend'])}" for e in flop if e["ch7"] < -2]
        if zeilen:
            teile.append("📊 Markt (7 Tage)\n" + "\n".join(zeilen))
    if teile:
        ntfy.senden("🌙 Pokéradar – dein Abend", "\n\n".join(teile), prio=2, tags=["crescent_moon"],
                    link=ntfy.dashboard or None)
    else:
        log.info("Abendübersicht: nichts Neues")
    write_json(QUEUE, [])
