"""News-Lauf: Meldungen sammeln, einordnen, zu Produkten bündeln, Alarme auslösen."""
from __future__ import annotations

import re
from datetime import timedelta

from . import market, setnamen
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
HINWEISE = DATA / "hinweise.json"

PRODUKT_STATUS = ("angekuendigt", "vorbestellbar", "ausverkauft", "erschienen", "nachschub")
STUFE = {"angekuendigt": 1, "vorbestellbar": 2, "ausverkauft": 3, "erschienen": 4, "nachschub": 5}
# Ab so viel Prozent unter Cardmarket ist ein Angebot "zu gut, um wahr zu sein": Preis gegenprüfen und warnen.
# Bei alten Boxen (Trend oft mehrere hundert Euro) ist genau das der Zufallsfund, den man nicht verpassen will.
STUTZIG_AB = 70
# Händler, bei denen ein Traumpreis eher Restposten als Fake-Shop ist
BEKANNTE_HAENDLER = re.compile(
    r"amazon|kaufland|otto|media ?markt|saturn|müller|mueller|rossmann|smyths|galeria|thalia|netto|lidl|aldi|"
    r"edeka|rewe|penny|globus|marktkauf|real\b|toys ?r ?us|bol\.com|walmart|target|best ?buy|gamestop|costco|"
    r"argos|tesco|asda|sainsbury|john lewis|pok[eé]mon ?center", re.I)
FRISCH = timedelta(hours=36)  # ältere Meldungen lösen keine Sofort-Alarme mehr aus
# Unbelegte Forenberichte gelten erst als Meldung, wenn so viele verschiedene Autoren
# innerhalb von ZEUGEN_FENSTER dasselbe über dieselbe Box berichten
BESTAETIGT_AB = 2
ZEUGEN_FENSTER = timedelta(hours=48)
# Wörter, die fast jede Box-Meldung enthält – für den Namensvergleich ohne Aussagekraft
_ALLGEMEIN = set("""pokemon pokémon tcg elite trainer top box boxes etb etbs booster display bundle ultra premium
    collection kollektion upc center pc preorder preorders pre order orders vorbestellbar vorbestellung vorbestellen
    restock restocked nachschub live now up is are at on the and for in of new jetzt ist sind bei der die das und mit
    available stock sold out again wieder anniversary celebration jubiläum jubilaeum jubiläums
    amazon walmart target gamestop bestbuy kaufland netto rewe edeka rossmann müller smyths otto mediamarkt saturn""".split())


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
    return fx.get("kurse") or {"USD": 1.1, "GBP": 0.85, "JPY": 160.0}


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


def _name(a: dict) -> str:
    """Produktname immer mit Set: 'Elite Trainer Box' + 'Delta Reign' → 'Delta Reign Elite Trainer Box'."""
    name = (a.get("produkt") or "").strip()
    s = (a.get("set_en") or a.get("set") or "").strip()
    if s and s.lower() not in name.lower():
        name = f"{s} {name}".strip()
    return name[:100]


def _preis_im_text(m: Meldung, preis: float | None) -> bool:
    """Steht der Preis wirklich so in der Meldung? Bei Traumpreisen verlesen sich KI-Modelle gern."""
    if preis is None:
        return False
    for z in re.findall(r"\d{1,5}(?:[.,]\d{1,2})?", f"{m.titel} {m.text} {m.preis_hinweis or ''}"):
        if abs(float(z.replace(",", ".")) - preis) < 0.01:
            return True
    return False


def _deal(m: Meldung, a: dict, ref: dict | None, preis_eur: float | None, deals: list[dict]) -> dict | None:
    """Legt ein Angebot an. None, wenn kein Preis bekannt ist oder es das Angebot schon gibt."""
    if not preis_eur:
        return None
    rabatt = round((1 - preis_eur / ref["trend"]) * 100, 1) if ref and ref.get("trend") else None
    pruefen, fake_risiko = None, False
    if rabatt is not None and rabatt > STUTZIG_AB:
        if not _preis_im_text(m, a["preis"]):
            return None  # Traumpreis, der so nicht in der Meldung steht → falsch gelesen
        fake_risiko = not BEKANNTE_HAENDLER.search(" ".join([a["haendler"] or ""] + m.belege))
        pruefen = ("Unbekannter Shop – Fake-Shop-Risiko: Impressum, Bewertungen und Zahlart prüfen" if fake_risiko
                   else "Prüfen, ob es genau diese Box ist (keine Neuauflage, kein leerer Karton)")
    d = {"id": m.id, "titel": m.titel, "link": m.link, "quelle": m.quelle, "datum": m.datum,
         "produkt": ref["name"] if ref else _name(a), "typ": a["typ"], "sprache": a["sprache"], "preis": a["preis"],
         "waehrung": a["waehrung"], "preis_eur": preis_eur, "haendler": a["haendler"],
         "lieferwelle": a.get("lieferwelle"), "liefertermin": a.get("liefertermin"),
         "hype": a["hype"], "kurz": a["kurz"], "markt": ref, "rabatt": rabatt, "status": a["status"],
         "pruefen": pruefen, "fake_risiko": fake_risiko}
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


def _belegt(m: Meldung, a: dict) -> bool:
    """Tatsachenbericht aus der Presse – oder aus einem Forum mit direktem Link zum Händler."""
    return a["aussage"] == "fakt" and (not m.forum or bool(m.belege))


def _hinweis(m: Meldung, a: dict, key: str) -> dict:
    return {"id": m.id, "key": key, "titel": m.titel, "link": m.link, "quelle": m.quelle, "autor": m.autor,
            "forum": m.forum, "datum": m.datum, "aussage": a["aussage"], "status": a["status"],
            "typ": a["typ"], "sprache": a["sprache"], "produkt": _name(a) or m.titel[:100], "kurz": a["kurz"]}


def _aehnlichkeit(a: str, b: str, enthalten: bool = False) -> float:
    """Namensvergleich nur über die unterscheidenden Wörter ('151', 'Delta Reign'), nicht 'Elite Trainer Box'.
    enthalten: b gilt als Treffer, wenn alle seine unterscheidenden Wörter in a vorkommen (Box-Name in Schlagzeile)."""
    t, u = tokens(a) - _ALLGEMEIN, tokens(b) - _ALLGEMEIN
    if enthalten and u and u <= t:
        return 1.0
    return len(t & u) / len(t | u) if t & u else 0.0


def _gleiche_box(x: dict, h: dict) -> bool:
    """Gleicher Produktschlüssel – oder (ohne KI-Setnamen) sehr ähnlicher Produktname."""
    if x["key"] == h["key"]:
        return True
    if (x["typ"], x["sprache"]) != (h["typ"], h["sprache"]):
        return False
    return _aehnlichkeit(x["produkt"], h["produkt"]) >= 0.5


def _zeugen(hinweise: list[dict], h: dict) -> list[dict]:
    """Unabhängige Forenberichte (je Autor einer), die dasselbe über dieselbe Box als Tatsache melden."""
    if h["aussage"] != "fakt" or not h["forum"]:
        return []
    grenze = iso(parse_iso(h["datum"]) - ZEUGEN_FENSTER)
    autoren: dict[str, dict] = {}
    for x in hinweise:
        if x["status"] == h["status"] and x["aussage"] == "fakt" and x["forum"] and x["datum"] >= grenze \
                and _gleiche_box(x, h):
            autoren.setdefault(x.get("autor") or x["id"], x)
    return list(autoren.values())


def offene_hinweise(seit: timedelta) -> list[dict]:
    """Unbestätigte Hinweise, die einen Blick wert sind (keine Fragen, Meinungen, Werbung) – je Box und Stufe einmal."""
    grenze = iso(now() - seit)
    out: list[dict] = []
    for h in sorted(read_json(HINWEISE, []), key=lambda x: x["datum"], reverse=True):
        if h["datum"] >= grenze and not h.get("bestaetigt") and h["aussage"] in ("fakt", "geruecht") \
                and not any(x["status"] == h["status"] and _gleiche_box(x, h) for x in out):
            out.append(h)
    return out


def _alarm(titel: str, text: str, prio: int, tags: list[str], link: str | None,
           vorbehalt: str = "") -> tuple[str, str, int, list[str], str | None]:
    """Unbestätigte Meldungen bekommen einen Warnhinweis und höchstens normale Priorität."""
    if vorbehalt:
        return titel, vorbehalt + text, min(prio, 3), tags, link
    return titel, text, prio, tags, link


def _produkt_finden(produkte: dict, a: dict, m: Meldung, cm: dict | None) -> str:
    """Schlüssel der Box: gleiches Cardmarket-Produkt = gleiche Box, sonst Setname, sonst Namensähnlichkeit."""
    gleich = [k for k, p in produkte.items() if p["typ"] == a["typ"] and p["sprache"] == a["sprache"]
              and p.get("variante") == a.get("variante")]
    if cm:
        for k in gleich:
            if (produkte[k].get("markt") or {}).get("id") == cm["id"]:
                return k
    basen = ([cm["set"]] if cm else []) + [b for b in (a.get("set_en"), a.get("set")) if b]
    for basis in basen:
        key = slug(f"{basis}-{a['typ']}-{a['sprache']}-{a.get('variante') or ''}")
        if key in produkte:
            return key
    name = f"{a.get('produkt') or ''} {a.get('set_en') or a.get('set') or ''}"
    bester, score = None, 0.0
    for k in gleich:
        j = _aehnlichkeit(name, f"{produkte[k]['name']} {produkte[k].get('set') or ''}", enthalten=True)
        if j > score:
            bester, score = k, j
    if bester and score >= 0.5:
        return bester
    if basen:
        return slug(f"{basen[0]}-{a['typ']}-{a['sprache']}-{a.get('variante') or ''}")
    return slug(f"{a.get('produkt') or m.titel}")[:70]


# ── Hauptlauf ────────────────────────────────────────────────────────────────

def lauf(cfg: Config, ntfy: Ntfy, markt_idx: dict) -> dict:
    seen: dict[str, str] = read_json(SEEN, {})
    erster_lauf = not seen
    produkte: dict[str, dict] = read_json(PRODUKTE, {})
    deals: list[dict] = read_json(DEALS, [])
    marktnews: list[dict] = read_json(MARKTNEWS, [])
    queue: list[dict] = read_json(QUEUE, [])
    hinweise: list[dict] = read_json(HINWEISE, [])
    kat = market.katalog()
    kurse = wechselkurse()
    namen = setnamen.laden()

    def zuordnen(m: Meldung, a: dict, ki_set: str | None = None) -> dict | None:
        """Cardmarket-Produkt: Setname der Analyse, sonst deutsche Setnamen-Tabelle, sonst KI-Zuordnung."""
        cm = market.zuordnen(a, kat)
        if not cm and "de" in (m.sprache, a["sprache"]):
            en = setnamen.englisch([a.get("set"), a.get("produkt"), m.titel], namen)
            cm = market.zuordnen(a, kat, en) if en else None
        return cm or (market.zuordnen(a, kat, ki_set) if ki_set else None)

    meldungen, quellen_status = sammeln()
    neu = [m for m in meldungen if m.id not in seen]
    ki = KI(cfg)
    log.info("%d neue Meldungen · KI %s", len(neu), "aktiv" if ki.aktiv else "aus (Regeln)")
    analysen = einordnen(neu, cfg, ki)

    # Setnamen für Marktvergleich klären (nur wo nötig)
    offen = [(m, a) for m in neu if (a := analysen.get(m.id)) and a["relevant"]
             and a["typ"] in cfg.produkte and a["status"] in ("angebot", "vorbestellbar", "nachschub", "angekuendigt")
             and not zuordnen(m, a)]
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
        cm = zuordnen(m, a, set_map.get(m.id))
        ref = _markt_ref(cm, markt_idx)
        preis_eur = in_eur(a["preis"], a["waehrung"], kurse)
        key = _produkt_finden(produkte, a, m, cm)

        # Nur belegte Meldungen legen Boxen an und lösen Alarme aus. Fragen, Meinungen, Gerüchte und
        # Forenbeiträge ohne Händler-Link werden als Hinweis gemerkt (Dashboard, Abendübersicht).
        vorbehalt = ""
        h = _hinweis(m, a, key)
        if _belegt(m, a):
            for x in hinweise:
                if not x.get("bestaetigt") and _gleiche_box(x, h):
                    x["bestaetigt"] = m.quelle
        else:
            hinweise.insert(0, h)
            zeugen = _zeugen(hinweise, h)
            if len(zeugen) < BESTAETIGT_AB:
                continue
            for x in zeugen:
                x["bestaetigt"] = "foren"
            vorbehalt = (f"⚠️ Unbestätigt: {len(zeugen)} Forenberichte, noch keine Händler- oder Presse-Quelle\n\n")

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
            if d and vorbehalt:
                d["unbestaetigt"] = True
            if d and gewuenscht(d) and frisch and d["rating"]["sterne"] >= cfg.schnaeppchen_ab_rating:
                preis_txt = f"{d['preis_eur']:.2f} €".replace(".", ",")
                haendler = f" · {d['haendler']}" if d["haendler"] else ""
                warnung = f"⚠️ Ungewöhnlich günstig ({d['rabatt']:.0f} % unter Cardmarket): {d['pruefen']}\n\n" \
                    if d["pruefen"] else ""
                # Echter Zufallsfund bei einem bekannten Händler → höchste Priorität
                prio = 5 if (d["rabatt"] or 0) >= 50 and not d["fake_risiko"] else 4
                alarme.append(_alarm(f"💸 Schnäppchen: {d['produkt']}"[:120],
                                     f"{warnung}{kopf(d)}{haendler} · {preis_txt}\n\n{rating_zeilen(d['rating'])}",
                                     prio, ["moneybag"], m.link, vorbehalt))
            elif d and gewuenscht(d) and d["rating"]["sterne"] >= 3:
                queue.append({"art": "angebot", "titel": d["produkt"], "sterne": d["rating"]["sterne"],
                              "info": d["rating"]["gruende"][0] if d["rating"]["gruende"] else "", "link": m.link})
            if a["status"] == "angebot":
                continue

        if a["status"] not in PRODUKT_STATUS or a["typ"] not in ("etb", "display", "upc"):
            continue

        # Produkte bündeln
        p = produkte.get(key)
        alt_stufe = p["stage"] if p else None
        if p is None:
            p = produkte[key] = {
                "key": key, "name": cm["name"] if cm else _name(a),
                "set": cm["set"] if cm else a.get("set_en") or a.get("set"), "typ": a["typ"],
                "sprache": a["sprache"], "variante": a.get("variante"), "stage": a["status"],
                "hype": a["hype"], "erstmals": m.datum, "quellen": [], "gemeldet": [],
            }
            if vorbehalt:
                p["unbestaetigt"] = True
        if not vorbehalt:
            p.pop("unbestaetigt", None)
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
        if p.get("set") and p["set"].lower() not in p["name"].lower():
            p["name"] = f"{p['set']} {p['name']}"[:100]
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
            alarme.append(_alarm(f"{icon}: {p['name']}{titel_zusatz}"[:120],
                                 f"{text_kopf}\n\n{rating_zeilen(p['rating'])}",
                                 5 if p["hype"] >= 8 else 4, ["rotating_light"], m.link, vorbehalt))
        elif alt_stufe is None and p["hype"] >= cfg.sofort_ab_hype:
            p["gemeldet"].append("neu")
            alarme.append(_alarm(f"✨ Neu angekündigt: {p['name']}"[:120],
                                 f"{text_kopf}\n{p['kurz']}\n\n{rating_zeilen(p['rating'])}", 4, ["sparkles"], m.link,
                                 vorbehalt))
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
    grenze_hinweise = iso(t_jetzt - timedelta(days=14))
    hinweise = [h for h in hinweise if h["datum"] >= grenze_hinweise][:300]
    write_json(SEEN, seen, compact=True)
    write_json(PRODUKTE, produkte)
    write_json(DEALS, deals)
    write_json(MARKTNEWS, marktnews)
    write_json(QUEUE, queue[-60:])
    write_json(HINWEISE, hinweise)
    return {"quellen": quellen_status, "ki": ki.aktiv or ki.aufrufe > 0,
            "modell": ki.modell,
            "neu": len(neu), "alarme": len(alarme)}
