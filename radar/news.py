"""News-Lauf: Meldungen sammeln, einordnen, zu Produkten bündeln, Alarme auslösen."""
from __future__ import annotations

import re
from datetime import timedelta

from . import market
from .classify import KI, einordnen
from .common import DATA, Config, http, iso, log, now, parse_iso, read_json, slug, tokens, write_json
from .notify import Ntfy, kopf, rating_zeilen
from .rating import bewerten
from .sources import Meldung, sammeln

SEEN = DATA / "seen.json"
PRODUKTE = DATA / "produkte.json"
DEALS = DATA / "deals.json"
MARKTNEWS = DATA / "marktnews.json"
QUEUE = DATA / "abend.json"
FX = DATA / "fx.json"

PRODUKT_STATUS = ("angekuendigt", "vorbestellbar", "ausverkauft", "erschienen", "nachschub")
STUFE = {"angekuendigt": 1, "vorbestellbar": 2, "ausverkauft": 3, "erschienen": 4, "nachschub": 5}
FRISCH = timedelta(hours=36)  # ältere Meldungen lösen keine Sofort-Alarme mehr aus


# ── Hilfen ───────────────────────────────────────────────────────────────────

def wechselkurse() -> dict[str, float]:
    """EUR-Kurse der EZB, einmal pro Tag."""
    fx = read_json(FX, {})
    heute = now().strftime("%Y-%m-%d")
    if fx.get("tag") == heute:
        return fx["kurse"]
    try:
        xml = http().get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", timeout=20).text
        kurse = {c: float(r) for c, r in re.findall(r"currency='(\w+)' rate='([\d.]+)'", xml)}
        if kurse:
            write_json(FX, {"tag": heute, "kurse": kurse})
            return kurse
    except Exception as e:  # noqa: BLE001
        log.warning("Wechselkurse nicht abrufbar: %s", e)
    return fx.get("kurse") or {"USD": 1.1, "JPY": 160.0}


def in_eur(preis: float | None, waehrung: str | None, kurse: dict) -> float | None:
    if preis is None:
        return None
    if waehrung in (None, "EUR"):
        return round(preis, 2)
    kurs = kurse.get(waehrung)
    return round(preis / kurs, 2) if kurs else None


def _quelle(m: Meldung, a: dict) -> dict:
    return {"titel": m.titel, "link": m.link, "quelle": m.quelle, "datum": m.datum, "status": a["status"]}


def _markt_ref(p: dict | None, markt_idx: dict) -> dict | None:
    if not p:
        return None
    ref = {"id": p["id"], "name": p["name"], "trend": p.get("trend"), "low": p.get("low")}
    m = markt_idx.get(p["id"])
    if m:
        ref.update({k: m.get(k) for k in ("ch7", "ch30", "hoch")})
    return ref


def _ki_sets(kandidaten: list[tuple[Meldung, dict]], kat: list[dict], ki: KI) -> dict[str, str]:
    """Lässt die KI deutsche/japanische Setnamen den englischen Cardmarket-Namen zuordnen."""
    if not kandidaten or not ki.aktiv or ki.zeit_um:
        return {}
    sets_int = [s for s in market.set_namen([p for p in kat if p["sprache"] == "int"])]
    sets_jp = [s for s in market.set_namen([p for p in kat if p["sprache"] == "jp"])]
    system = ("Ordne Pokémon-TCG-Produkte dem passenden Setnamen aus einer Liste zu. Deutsche Setnamen "
              "sind Übersetzungen der englischen (z. B. 'Prismatische Entwicklungen' = 'Prismatic Evolutions', "
              "'Karmesin & Purpur' = 'Scarlet & Violet'). Antworte nur mit JSON {\"items\":[{\"i\":n,\"set\":"
              "\"<exakt aus der Liste>\"|null}]}. Wenn unsicher: null.")
    user = ("Liste INT: " + " | ".join(sets_int) + "\n\nListe JP: " + " | ".join(sets_jp) + "\n\n" +
            "\n".join(f"[{i}] ({'JP' if a['sprache'] == 'jp' else 'INT'}) {m.titel} · Set laut Analyse: {a.get('set')}"
                      for i, (m, a) in enumerate(kandidaten)))
    antwort = ki.chat(system, user) or {}
    erlaubt = set(sets_int) | set(sets_jp)
    out = {}
    for d in antwort.get("items") or []:
        if isinstance(d, dict) and isinstance(d.get("i"), int) and d.get("set") in erlaubt \
                and 0 <= d["i"] < len(kandidaten):
            out[kandidaten[d["i"]][0].id] = d["set"]
    return out


def _deal(m: Meldung, a: dict, ref: dict | None, preis_eur: float | None, deals: list[dict]) -> dict | None:
    """Legt ein Angebot an. None, wenn kein Preis bekannt ist oder es das Angebot schon gibt."""
    rabatt = round((1 - preis_eur / ref["trend"]) * 100, 1) if preis_eur and ref and ref.get("trend") else None
    if rabatt is not None and rabatt > 70:  # unplausibel → Preis vermutlich falsch gelesen
        return None
    if not preis_eur:
        return None
    d = {"id": m.id, "titel": m.titel, "link": m.link, "quelle": m.quelle, "datum": m.datum,
         "produkt": a["produkt"], "typ": a["typ"], "sprache": a["sprache"], "preis": a["preis"],
         "waehrung": a["waehrung"], "preis_eur": preis_eur, "haendler": a["haendler"],
         "lieferwelle": a.get("lieferwelle"), "liefertermin": a.get("liefertermin"),
         "hype": a["hype"], "kurz": a["kurz"], "markt": ref, "rabatt": rabatt, "status": a["status"]}
    d["rating"] = bewerten("angebot", d, ref)
    # Gleiches Angebot aus mehreren Artikeln nur einmal führen
    for x in deals:
        gleiche_ware = (ref and (x.get("markt") or {}).get("id") == ref["id"]) or slug(x["produkt"]) == slug(d["produkt"])
        if gleiche_ware and abs((x.get("preis_eur") or 0) - preis_eur) < 1.5:
            if d["datum"] > x["datum"]:
                x.update({k: d[k] for k in ("datum", "link", "quelle", "titel")})
            return None
    deals.insert(0, d)
    return d


def _produkt_finden(produkte: dict, a: dict, m: Meldung) -> str:
    basis = a.get("set_en") or a.get("set")
    if basis:
        key = slug(f"{basis}-{a['typ']}-{a['sprache']}-{a.get('variante') or ''}")
        if key in produkte:
            return key
    # Ähnlichkeitsabgleich mit bestehenden Produkten gleicher Art und Sprache
    t = tokens(f"{a.get('produkt') or ''} {basis or ''}")
    bester, score = None, 0.0
    for key, p in produkte.items():
        if p["typ"] != a["typ"] or p["sprache"] != a["sprache"] or p.get("variante") != a.get("variante"):
            continue
        u = tokens(f"{p['name']} {p.get('set') or ''}")
        j = len(t & u) / max(1, len(t | u))
        if j > score:
            bester, score = key, j
    if bester and score >= 0.5:
        return bester
    return slug(f"{basis}-{a['typ']}-{a['sprache']}-{a.get('variante') or ''}") if basis else \
        slug(f"{a.get('produkt') or m.titel}")[:70]


# ── Hauptlauf ────────────────────────────────────────────────────────────────

def lauf(cfg: Config, ntfy: Ntfy, markt_idx: dict) -> dict:
    seen: dict[str, str] = read_json(SEEN, {})
    erster_lauf = not seen
    produkte: dict[str, dict] = read_json(PRODUKTE, {})
    deals: list[dict] = read_json(DEALS, [])
    marktnews: list[dict] = read_json(MARKTNEWS, [])
    queue: list[dict] = read_json(QUEUE, [])
    kat = market.katalog()
    kurse = wechselkurse()

    meldungen, quellen_status = sammeln()
    neu = [m for m in meldungen if m.id not in seen]
    ki = KI(cfg)
    log.info("%d neue Meldungen · KI %s", len(neu), "aktiv" if ki.aktiv else "aus (Regeln)")
    analysen = einordnen(neu, cfg, ki)

    # Setnamen für Marktvergleich klären (nur wo nötig)
    offen = [(m, a) for m in neu if (a := analysen.get(m.id)) and a["relevant"]
             and a["typ"] in cfg.produkte and a["status"] in ("angebot", "vorbestellbar", "nachschub", "angekuendigt")
             and not market.zuordnen(a, kat)]
    set_map = _ki_sets(offen[:24], kat, ki)

    t_jetzt = now()
    alarme: list[tuple[str, str, int, list[str], str | None]] = []  # titel, text, prio, tags, link

    def gewuenscht(x: dict) -> bool:
        return x["typ"] in cfg.produkte and x["sprache"] in cfg.sprachen

    for m in neu:
        a = analysen.get(m.id)
        if a is None:
            continue  # über dem KI-Kontingent → nächster Lauf
        seen[m.id] = m.datum
        if not a["relevant"]:
            continue
        frisch = t_jetzt - parse_iso(m.datum) <= FRISCH and not erster_lauf
        cm = market.zuordnen(a, kat, set_map.get(m.id))
        ref = _markt_ref(cm, markt_idx)
        preis_eur = in_eur(a["preis"], a["waehrung"], kurse)

        # Preisberichte → Markt-News
        if a["status"] == "markt":
            marktnews.insert(0, {"id": m.id, "titel": m.titel, "link": m.link, "quelle": m.quelle,
                                 "datum": m.datum, "sprache": a["sprache"], "typ": a["typ"],
                                 "trend": a["trend"], "kurz": a["kurz"], "markt": ref})
            continue

        # Angebote → Schnäppchen-Radar
        ist_deal = a["status"] == "angebot" or (m.art == "deal" and a["preis"] and a["status"] in ("vorbestellbar", "nachschub"))
        if ist_deal and a["typ"] in ("etb", "display", "upc"):
            d = _deal(m, a, ref, preis_eur, deals)
            if d and gewuenscht(d) and frisch and d["rating"]["sterne"] >= cfg.schnaeppchen_ab_rating:
                preis_txt = f"{d['preis_eur']:.2f} €".replace(".", ",")
                haendler = f" · {d['haendler']}" if d["haendler"] else ""
                alarme.append((f"💸 Schnäppchen: {d['produkt']}"[:120],
                               f"{kopf(d)}{haendler} · {preis_txt}\n\n{rating_zeilen(d['rating'])}",
                               4, ["moneybag"], m.link))
            elif d and gewuenscht(d) and d["rating"]["sterne"] >= 3:
                queue.append({"art": "angebot", "titel": d["produkt"], "sterne": d["rating"]["sterne"],
                              "info": d["rating"]["gruende"][0] if d["rating"]["gruende"] else "", "link": m.link})
            if a["status"] == "angebot":
                continue

        if a["status"] not in PRODUKT_STATUS or a["typ"] not in ("etb", "display", "upc"):
            continue

        # Produkte bündeln
        key = _produkt_finden(produkte, a, m)
        p = produkte.get(key)
        alt_stufe = p["stage"] if p else None
        if p is None:
            p = produkte[key] = {
                "key": key, "name": a["produkt"], "set": a.get("set_en") or a.get("set"), "typ": a["typ"],
                "sprache": a["sprache"], "variante": a.get("variante"), "stage": a["status"],
                "hype": a["hype"], "erstmals": m.datum, "quellen": [], "gemeldet": [],
            }
        # Stufe nur vorwärts – außer Nachschub, der immer zählt
        if a["status"] == "nachschub" or STUFE[a["status"]] > STUFE.get(p["stage"], 0):
            p["stage"] = a["status"]
        p["hype"] = max(p["hype"], a["hype"] + (1 if a["status"] == "ausverkauft" else 0))
        p["hype"] = min(10, p["hype"])
        for feld in ("vorverkauf_ab", "erscheint_am", "haendler", "lieferwelle", "liefertermin"):
            if a.get(feld):
                p[feld] = a[feld]
        if preis_eur and a["status"] in ("vorbestellbar", "nachschub", "angekuendigt"):
            p["preis_eur"] = preis_eur
        if a.get("gruende"):
            p["gruende"] = list(dict.fromkeys((p.get("gruende") or []) + a["gruende"]))[:4]
        p["kurz"] = a["kurz"]
        p["aktualisiert"] = max(p.get("aktualisiert", m.datum), m.datum)
        p["quellen"] = ([_quelle(m, a)] + p["quellen"])[:8]
        if ref:
            p["markt"] = ref
        art = {"vorbestellbar": "vorverkauf", "nachschub": "nachschub"}.get(p["stage"], "neu")
        p["rating"] = bewerten(art, p, p.get("markt"))

        if not gewuenscht(p) or not frisch:
            continue
        titel_zusatz = f" – {p['haendler']}" if p.get("haendler") else ""
        text_kopf = kopf(p) + (f" · {p['preis_eur']:.2f} €".replace(".", ",") if p.get("preis_eur") else "")
        if p["stage"] in ("vorbestellbar", "nachschub") and p["stage"] != alt_stufe \
                and p["stage"] not in p["gemeldet"] and cfg.vorverkauf_sofort:
            p["gemeldet"].append(p["stage"])
            icon = "🟢 Jetzt vorbestellbar" if p["stage"] == "vorbestellbar" else "🔁 Nachschub"
            alarme.append((f"{icon}: {p['name']}{titel_zusatz}"[:120],
                           f"{text_kopf}\n\n{rating_zeilen(p['rating'])}",
                           5 if p["hype"] >= 8 else 4, ["rotating_light"], m.link))
        elif alt_stufe is None and p["hype"] >= cfg.sofort_ab_hype:
            p["gemeldet"].append("neu")
            alarme.append((f"✨ Neu angekündigt: {p['name']}"[:120],
                           f"{text_kopf}\n{p['kurz']}\n\n{rating_zeilen(p['rating'])}", 4, ["sparkles"], m.link))
        elif alt_stufe is None:
            queue.append({"art": "neu", "titel": p["name"], "sterne": p["rating"]["sterne"],
                          "info": p["kurz"], "link": m.link})

    # Senden
    if erster_lauf:
        vb = sum(1 for p in produkte.values() if p["stage"] == "vorbestellbar" and gewuenscht(p))
        ntfy.senden("Pokéradar ist startklar ⚡",
                    f"{len(produkte)} Boxen erfasst, {vb} davon gerade vorbestellbar, {len(deals)} Angebote.\n"
                    "Ab jetzt meldet sich das Radar, sobald etwas Neues auftaucht.",
                    prio=3, tags=["zap"], link=ntfy.dashboard or None)
    for titel, text, prio, tags, link in alarme[:8]:
        ntfy.senden(titel, text, prio=prio, tags=tags, link=link)
    if len(alarme) > 8:
        ntfy.senden(f"… und {len(alarme) - 8} weitere Treffer", "Alle Details im Radar.", prio=3,
                    link=ntfy.dashboard or None)

    # Aufräumen & speichern
    grenze_seen = iso(t_jetzt - timedelta(days=45))
    seen = {k: v for k, v in seen.items() if v >= grenze_seen}
    grenze = iso(t_jetzt - timedelta(days=150))
    produkte = {k: p for k, p in produkte.items() if p.get("aktualisiert", p["erstmals"]) >= grenze}
    grenze_deals = iso(t_jetzt - timedelta(days=30))
    deals = [d for d in deals if d["datum"] >= grenze_deals][:200]
    marktnews = [d for d in marktnews if d["datum"] >= grenze_deals][:100]
    write_json(SEEN, seen, compact=True)
    write_json(PRODUKTE, produkte)
    write_json(DEALS, deals)
    write_json(MARKTNEWS, marktnews)
    write_json(QUEUE, queue[-60:])
    return {"quellen": quellen_status, "ki": ki.aktiv or ki.aufrufe > 0,
            "modell": ki.modell,
            "neu": len(neu), "alarme": len(alarme)}
