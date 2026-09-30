"""Marktpreise aus der öffentlichen Cardmarket-Preisübersicht (EUR, täglich aktualisiert).

Cardmarket liefert für versiegelte Produkte nur den aktuellen Trend- und Tiefstpreis.
Den Verlauf baut das Radar selbst auf: ein kleiner Tages-Schnappschuss pro Tag.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from .common import DATA, Config, http, log, read_json, tokens, write_json

KATALOG_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_6.json"
PREISE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"

PREIS_DIR = DATA / "prices"
KATALOG_DATEI = DATA / "katalog.json"

_FREMD = re.compile(r"chinese|korean|thai|indonesian|\bkr\b|\bcn\b|\bth\b|\bid\b|^(cs|csv|cbb|csm)\d", re.I)
_CASE = re.compile(r"\bcase\b", re.I)
_JP = re.compile(r"\bjp\b|japanese|japan", re.I)
_UPC = re.compile(r"ultra.?premium", re.I)
_TYP_WORTE = re.compile(
    r"pok[eé]mon center|elite trainer box|booster box|ultra.?premium collection|display|"
    r"\(18 boosters\)|\bjp\b|\d+ booster box case|case|:", re.I)


def typ_von(p: dict, cases: bool) -> str | None:
    name, kat = p["name"], p.get("categoryName", "")
    if _FREMD.search(name) or (not cases and _CASE.search(name)):
        return None
    if kat == "Pokémon Elite Trainer Boxes" and "elite trainer box" in name.lower():
        return "etb"
    if kat == "Pokémon Display" and re.search(r"booster box|display", name, re.I) \
            and not re.search(r"sleeved|bundle", name, re.I):
        return "display"
    if kat == "Pokémon Box Set" and _UPC.search(name):
        return "upc"
    return None


def set_von(name: str) -> str:
    """'Delta Reign Pokémon Center Elite Trainer Box' → 'Delta Reign'."""
    s = _TYP_WORTE.sub(" ", name)
    return re.sub(r"\s+", " ", s).strip(" -–:")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def nur_japan_sets() -> set[str]:
    """Setnamen, die es nur in Japan gibt (Abgleich der TCGplayer-Setlisten EN ↔ JP via tcgcsv.com).
    Cardmarket kennzeichnet solche Boxen nicht immer mit 'JP'."""
    try:
        namen = {}
        for kat in (3, 85):
            r = http().get(f"https://tcgcsv.com/tcgplayer/{kat}/groups", timeout=30)
            r.raise_for_status()
            namen[kat] = {_norm(re.sub(r"^[\w.-]+:\s*", "", g["name"])) for g in r.json()["results"]}
        en = namen[3]
        # "SM - Forbidden Light" ist auch englisch → Endungen mit abgleichen
        return {j for j in namen[85] if not any(e == j or e.endswith(" " + j) for e in en)}
    except Exception as e:  # noqa: BLE001
        log.warning("Japan-Setliste nicht abrufbar: %s", e)
        return set()


def laden(cfg: Config) -> tuple[list[dict], str]:
    jp_sets = nur_japan_sets()
    kat = http().get(KATALOG_URL, timeout=90)
    kat.raise_for_status()
    pg = http().get(PREISE_URL, timeout=120)
    pg.raise_for_status()
    kat.encoding = pg.encoding = "utf-8"
    preise = pg.json()
    stand = preise.get("createdAt", "")[:10]
    pmap = {p["idProduct"]: p for p in preise.get("priceGuides", [])}
    produkte = []
    for p in kat.json().get("products", []):
        typ = typ_von(p, cfg.cases)
        if not typ:
            continue
        g = pmap.get(p["idProduct"], {})
        s = set_von(p["name"])
        produkte.append({
            "id": p["idProduct"], "name": p["name"], "typ": typ,
            "sprache": "jp" if _JP.search(p["name"]) or _norm(s) in jp_sets else "int",
            "set": s, "exp": p.get("idExpansion"),
            "seit": (p.get("dateAdded") or "")[:10],
            "trend": g.get("trend"), "low": g.get("low"), "avg": g.get("avg"),
        })
    log.info("Cardmarket-Stand %s: %d beobachtbare Produkte", stand, len(produkte))
    return produkte, stand


def _schnappschuss_pfad(tag: str) -> Path:
    return PREIS_DIR / tag[:4] / f"{tag[5:]}.json"


def schnappschuss(produkte: list[dict], stand: str) -> bool:
    """Speichert Trendpreise des Tages (id → trend). Idempotent."""
    pfad = _schnappschuss_pfad(stand)
    daten = {str(p["id"]): round(p["trend"], 2) for p in produkte if p.get("trend")}
    return write_json(pfad, daten, compact=True)


def verlauf(tage: int, bis: str) -> dict[str, dict[str, float]]:
    """{datum: {id: trend}} der letzten `tage` Tage."""
    ende = date.fromisoformat(bis)
    out = {}
    for i in range(tage, -1, -1):
        tag = (ende - timedelta(days=i)).isoformat()
        d = read_json(_schnappschuss_pfad(tag), None)
        if d:
            out[tag] = d
    return out


def _wert_am(v: dict[str, dict], pid: str, tag: date, toleranz: int = 3) -> float | None:
    for d in range(toleranz + 1):
        for t in (tag - timedelta(days=d), tag + timedelta(days=d)):
            wert = v.get(t.isoformat(), {}).get(pid)
            if wert:
                return wert
    return None


def _aenderung(jetzt: float | None, frueher: float | None) -> float | None:
    if not jetzt or not frueher:
        return None
    return round((jetzt / frueher - 1) * 100, 1)


def auswerten(produkte: list[dict], stand: str, cfg: Config) -> list[dict]:
    v = verlauf(95, stand)
    heute = date.fromisoformat(stand)
    tage = sorted(v)
    out = []
    for p in produkte:
        if not p.get("trend") or p["trend"] < cfg.mindestpreis or p.get("avg") is None:
            continue
        pid = str(p["id"])
        reihe = [[t, v[t][pid]] for t in tage if pid in v[t]]
        werte = [w for _, w in reihe]
        e = dict(p)
        e["ch7"] = _aenderung(p["trend"], _wert_am(v, pid, heute - timedelta(days=7)))
        e["ch30"] = _aenderung(p["trend"], _wert_am(v, pid, heute - timedelta(days=30), 5))
        e["ch90"] = _aenderung(p["trend"], _wert_am(v, pid, heute - timedelta(days=90), 7))
        e["hoch"] = max(werte) if werte else p["trend"]
        e["spark"] = [round(w, 2) for w in werte[-90:]]
        out.append(e)
    return out


def verlauf_tage(stand: str) -> int:
    return len(verlauf(95, stand))


# ── Zuordnung von Angeboten zu Cardmarket-Produkten ─────────────────────────

def katalog_speichern(produkte: list[dict]) -> None:
    write_json(KATALOG_DATEI, [{k: p[k] for k in ("id", "name", "typ", "sprache", "set", "trend", "low")}
                               for p in produkte], compact=True)


def katalog() -> list[dict]:
    return read_json(KATALOG_DATEI, [])


def set_namen(kat: list[dict]) -> list[str]:
    return sorted({p["set"] for p in kat if p["set"]})


def zuordnen(analyse: dict, kat: list[dict], set_en: str | None = None) -> dict | None:
    """Sucht das passende Cardmarket-Produkt zu einer Meldung."""
    typ = analyse.get("typ")
    if typ not in ("etb", "display", "upc") or not kat:
        return None
    sprache = "jp" if analyse.get("sprache") == "jp" else "int"
    kandidaten = [p for p in kat if p["typ"] == typ and p["sprache"] == sprache]
    if not kandidaten:
        return None
    ziel_set = (set_en or analyse.get("set_en") or "").strip().lower()
    if ziel_set:
        exakt = [p for p in kandidaten if p["set"].lower() == ziel_set]
        if exakt:
            kandidaten = exakt
    variante = analyse.get("variante")

    def passt(p: dict) -> float:
        name = p["name"].lower()
        pc = "pokémon center" in name or "pokemon center" in name
        s = 0.0
        if variante == "pokemon-center":
            s += 1 if pc else -1
        elif pc:
            s -= 0.5
        if typ == "display":
            achtzehn = "18 boosters" in name
            s += (1 if achtzehn else -1) if variante == "18er" else (-0.5 if achtzehn else 0)
        if not ziel_set:
            a = tokens(f"{analyse.get('set') or ''} {analyse.get('produkt') or ''}")
            b = tokens(p["set"])
            s += 3 * (len(a & b) / len(b)) if b else 0
        return s

    bester = max(kandidaten, key=passt)
    if not ziel_set:
        a = tokens(f"{analyse.get('set') or ''} {analyse.get('produkt') or ''}")
        b = tokens(bester["set"])
        if not b or len(a & b) / len(b) < 0.99:  # ohne Setnamen nur bei vollem Treffer
            return None
    return bester
