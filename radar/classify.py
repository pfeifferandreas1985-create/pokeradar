"""Einordnung der Meldungen – per kostenlosem LLM (GLM-Flash) oder eingebauten Regeln."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

from .common import Config, http, log
from .sources import Meldung

STATUS = ("angekuendigt", "vorbestellbar", "ausverkauft", "erschienen",
          "nachschub", "angebot", "markt", "sonstiges")

SYSTEM_PROMPT = """Du bist Analyst für versiegelte Pokémon-TCG-Produkte und hilfst einem Sammler aus Deutschland,
limitierte, begehrte Boxen rechtzeitig zu kaufen. Du bekommst nummerierte Meldungen (News, Deals, Community-Posts).

Relevant sind NUR diese Produktarten:
- "etb": Elite Trainer Box / Top-Trainer-Box (auch Pokémon-Center-Edition)
- "display": Booster-Box / Display (36er, 18er, japanische 30er-Boxen, Deluxe-/High-Class-Boxen)
- "upc": Ultra-Premium-Kollektion / Ultra Premium Collection
Außerdem relevant: Meldungen über starke Preisbewegungen dieser Produkte (status "markt").
Meldet eine Nachricht den Vorverkauf eines ganzen Sets (z. B. "Pokémon Center Pre-Orders für Set X sind live"),
ordne sie der wichtigsten betroffenen Produktart zu – meist "etb" mit variante "pokemon-center".
Nicht relevant: Einzelkarten, einzelne Booster, Tins, Blister, Spiele, Merch, Pokémon GO, Filme usw.

Status:
- angekuendigt: Produkt wurde enthüllt/angekündigt, noch nicht bestellbar
- vorbestellbar: Vorbestellung/Pre-Order/予約/抽選 ist JETZT offen (auch Pokémon-Center-Warteschlange)
- ausverkauft: Vorbestellung oder Ware ist ausverkauft
- erschienen: Produkt ist im Handel erschienen
- nachschub: Restock / wieder verfügbar / Nachlieferung
- angebot: konkretes Angebot mit Preis bei einem Händler (Deal, Rabatt, Tiefpreis)
- markt: Bericht über Preisanstieg oder -verfall am Sammlermarkt
- sonstiges: alles andere

Hype 1–10 (wie begehrt und knapp wird es voraussichtlich?):
- 9–10: Special-/Jubiläums-Set, Pokémon-Center-exklusiv, Fan-Lieblinge (Glurak/Charizard, Evoli-Entwicklungen,
  Pikachu, Mew/Mewtu, Nachtara/Umbreon, Gengar), Vorgänger schnell ausverkauft, deutlich limitierte Auflage
- 7–8: beliebtes Hauptset, Ultra-Premium-Kollektion, klare Knappheitssignale
- 4–6: normales Hauptset-Produkt
- 1–3: Reprint, Massenware, Restposten

Antworte ausschließlich mit JSON der Form {"items":[...]} – ein Objekt pro Meldung, gleiche Reihenfolge:
{"i": <Nummer>, "relevant": bool, "typ": "etb"|"display"|"upc"|"andere",
 "sprache": "de"|"en"|"jp" (Sprachversion des PRODUKTS, nicht des Artikels),
 "status": <Status>, "set": "<Setname wie in der Meldung>", "set_en": "<englischer Setname oder null>",
 "produkt": "<kurzer Produktname>", "variante": "pokemon-center"|"18er"|null,
 "vorverkauf_ab": "YYYY-MM-DD"|null, "erscheint_am": "YYYY-MM-DD"|null,
 "preis": Zahl|null, "waehrung": "EUR"|"USD"|"JPY"|null, "haendler": "<Händler>"|null,
 "lieferwelle": 1|2|3|null (Liefer-/Zuteilungswelle bei Vorbestellungen, z. B. "Welle 1", "2. Welle", "second wave"),
 "liefertermin": "<voraussichtliche Lieferung, z. B. 2026-11-07, KW 45, Dezember 2026>"|null,
 "hype": 1-10, "trend": "steigt"|"faellt"|null,
 "gruende": ["<bis zu 3 kurze deutsche Gründe, warum begehrt/lohnend oder nicht>"],
 "kurz": "<ein deutscher Satz: was ist passiert und was bedeutet es für Sammler>"}
Erfinde keine Daten: Unbekanntes ist null. Heute ist __HEUTE__."""


# ── Regeln (Rückfall ohne KI) ────────────────────────────────────────────────

_TYP = [
    ("upc", re.compile(r"ultra.?premium|\bupc\b", re.I)),
    ("etb", re.compile(r"elite.?trainer|\betbs?\b|top.?trainer", re.I)),
    ("display", re.compile(r"booster.?box|booster.?display|\bdisplay\b|36er|18er|"
                           r"(拡張パック|ハイクラスパック|強化拡張パック).*(box|ボックス)|box.*(拡張パック)", re.I)),
]
_STATUS = [
    ("nachschub", re.compile(r"restock|wieder (verfügbar|da|erhältlich)|nachschub|nachliefer|再販|再入荷", re.I)),
    ("ausverkauft", re.compile(r"sold.?out|ausverkauft|vergriffen|完売|売り切れ", re.I)),
    ("vorbestellbar", re.compile(r"pre.?order|vorbestell|preorders? (are )?(live|open)|queue|予約|抽選|jetzt bestell", re.I)),
    ("markt", re.compile(r"price|preis(anstieg|explosion|verfall)|market value|marktwert|skyrocket|"
                         r"investment|value (up|down)|高騰|相場", re.I)),
    ("angekuendigt", re.compile(r"reveal|announc|angekündigt|enthüllt|vorgestellt|first look|発表|公開|新弾", re.I)),
    ("erschienen", re.compile(r"out now|release[sd]? today|jetzt erhältlich|erschienen|発売中|本日発売", re.I)),
]
_HYPE_PLUS = re.compile(r"glurak|charizard|evoli|eevee|umbreon|nachtara|pikachu|mew|gengar|151|"
                        r"pok[eé]mon center|limit|exclusive|exklusiv|special|jubil|anniversary|30th|"
                        r"sold.?out|ausverkauft|prismatic|prismatisch", re.I)
_PREIS = re.compile(r"(\d{1,4}(?:[.,]\d{2})?)\s?(€|eur|\$|usd|円)|(\$|€)\s?(\d{1,4}(?:[.,]\d{2})?)", re.I)


def _preis(text: str) -> tuple[float | None, str | None]:
    statt = re.search(r"(\d{1,4}(?:,\d{2})?)\s?(?:€|euro|eur)?\s+statt\b", text, re.I)
    if statt:
        return float(statt.group(1).replace(",", ".")), "EUR"
    m = _PREIS.search(text)
    if not m:
        return None, None
    wert = m.group(1) or m.group(4)
    sym = (m.group(2) or m.group(3) or "").lower()
    try:
        zahl = float(wert.replace(".", "").replace(",", ".") if "," in wert else wert)
    except ValueError:
        return None, None
    return zahl, {"€": "EUR", "eur": "EUR", "$": "USD", "usd": "USD", "円": "JPY"}.get(sym)


_WELLE = re.compile(r"(?:welle|wave)\s*(\d)|(\d)\s*\.?\s*(?:welle|wave)|(first|second|third|erste|zweite|dritte)\s*(?:welle|wave)", re.I)
_WORTZAHL = {"first": 1, "erste": 1, "second": 2, "zweite": 2, "third": 3, "dritte": 3}
_TERMIN = re.compile(r"(?:lieferung|liefertermin|versand|ships?|delivery|auslieferung)[^.\n]{0,25}?"
                     r"((?:kw\s?\d{1,2})|(?:\d{1,2}\.\d{1,2}\.(?:\d{2,4})?)|"
                     r"(?:januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember|"
                     r"january|february|march|may|june|july|october|december)\s?\d{0,4})", re.I)


def _welle(text: str) -> int | None:
    m = _WELLE.search(text)
    if not m:
        return None
    if m.group(3):
        return _WORTZAHL[m.group(3).lower()]
    n = int(m.group(1) or m.group(2))
    return n if 0 < n < 10 else None


def _liefertermin(text: str) -> str | None:
    m = _TERMIN.search(text)
    return m.group(1).strip() if m else None


_DEAL = re.compile(r"under market|below market|down to market|marked down|\bsave\b|\bdeal\b|for under|"
                   r"\bstatt\b|sparpreis|reduziert|rabatt|tiefpreis|bestpreis|günstig|angebot|"
                   r"(für|for|um|nur|at)\s+\$?\d{1,4}([.,]\d{2})?\s?(€|euro|\$)?", re.I)


def regeln(m: Meldung) -> dict:
    blob = f"{m.titel} {m.text[:400]}"
    typ = next((t for t, rx in _TYP if rx.search(m.titel)), None) or \
        next((t for t, rx in _TYP if rx.search(blob)), "andere")
    status = next((s for s, rx in _STATUS if rx.search(m.titel)), None) or \
        next((s for s, rx in _STATUS if rx.search(blob)), "sonstiges")
    preis, waehrung = _preis(m.preis_hinweis or "") if m.preis_hinweis else (None, None)
    if preis is None and (m.art == "deal" or _DEAL.search(m.titel)):
        preis, waehrung = _preis(m.titel)
    if waehrung is None and preis is not None:
        waehrung = "EUR" if m.sprache == "de" else ("USD" if m.sprache == "en" else "JPY")
    if preis and (m.art == "deal" or _DEAL.search(m.titel)) and status not in ("vorbestellbar", "nachschub"):
        status = "angebot"
    if re.search(r"englisch|english version", blob, re.I):
        sprache = "en"
    elif re.search(r"japan|japanisch|\bjp\b|[぀-ヿ]", blob, re.I):
        sprache = "jp"
    else:
        sprache = m.sprache
    treffer = len(set(x.lower() for x in _HYPE_PLUS.findall(blob)))
    hype = max(1, min(10, 5 + 2 * treffer - (2 if re.search(r"reprint|restposten", blob, re.I) else 0)))
    gruende = []
    if re.search(r"pok[eé]mon center", blob, re.I):
        gruende.append("Pokémon-Center-Produkt – meist kleinere Stückzahl")
    if re.search(r"glurak|charizard|evoli|eevee|umbreon|nachtara|pikachu", blob, re.I):
        gruende.append("Fan-Liebling im Produkt – treibt die Nachfrage")
    if re.search(r"sold.?out|ausverkauft", blob, re.I):
        gruende.append("Bereits Ausverkauf gemeldet")
    return {
        "lieferwelle": _welle(blob), "liefertermin": _liefertermin(blob),
        "relevant": typ != "andere" or status == "markt",
        "typ": typ, "sprache": sprache, "status": status,
        "set": None, "set_en": None, "produkt": m.titel[:90], "variante":
            "pokemon-center" if re.search(r"pok[eé]mon center", blob, re.I) else
            ("18er" if re.search(r"18er|18 booster", blob, re.I) else None),
        "vorverkauf_ab": None, "erscheint_am": None,
        "preis": preis, "waehrung": waehrung, "haendler": m.haendler_hinweis,
        "hype": hype, "trend": "steigt" if re.search(r"skyrocket|steig|rise|高騰", blob, re.I) else
            ("faellt" if re.search(r"drop|fall|crash|sink", blob, re.I) else None),
        "gruende": gruende, "kurz": m.titel[:140], "_quelle": "regeln",
    }


# ── KI ───────────────────────────────────────────────────────────────────────

class KI:
    """Probiert der Reihe nach alle Anbieter/Modelle, für die ein Schlüssel hinterlegt ist."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ziele: list[dict] = []  # je Eintrag: Anbieter + Modell
        for a in cfg.ki_anbieter:
            key = next((os.environ.get(n, "").strip() for n in a["schluessel"] if os.environ.get(n, "").strip()), "")
            if key:
                for modell in a["modelle"]:
                    self.ziele.append({"anbieter": a["name"], "url": a["basis_url"].rstrip("/"), "key": key,
                                       "modell": modell, "extra": dict(a.get("extra") or {}), "json": True})
        self.idx = 0
        self.aufrufe = 0
        self.modell: str | None = None

    @property
    def aktiv(self) -> bool:
        return self.idx < len(self.ziele)

    def _weiter(self, grund: str) -> None:
        z = self.ziele[self.idx]
        log.warning("%s/%s: %s – nächster Kandidat", z["anbieter"], z["modell"], grund)
        self.idx += 1

    def chat(self, system: str, user: str) -> dict | None:
        while self.aktiv:
            z = self.ziele[self.idx]
            body = {"model": z["modell"], "temperature": 0.2,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}], **z["extra"]}
            if z["json"]:
                body["response_format"] = {"type": "json_object"}
            headers = {"Authorization": f"Bearer {z['key']}", "X-Title": "Pokeradar"}
            try:
                r = http().post(f"{z['url']}/chat/completions", json=body, timeout=150, headers=headers)
                if r.status_code == 429:
                    log.info("%s: Limit erreicht – kurze Pause", z["anbieter"])
                    time.sleep(10)
                    r = http().post(f"{z['url']}/chat/completions", json=body, timeout=150, headers=headers)
            except Exception as e:  # noqa: BLE001
                self._weiter(f"nicht erreichbar ({e})")
                continue
            self.aufrufe += 1
            if r.status_code == 400 and (z["extra"] or z["json"]):
                # Zusatzparameter werden nicht von jedem Modell verstanden → schrittweise weglassen
                if z["extra"]:
                    z["extra"] = {}
                else:
                    z["json"] = False
                continue
            if r.status_code in (401, 403):
                # Schlüssel ungültig oder kein Guthaben → alle Modelle dieses Anbieters überspringen
                log.error("%s: Zugriff verweigert (HTTP %s) %s", z["anbieter"], r.status_code, r.text[:160])
                anbieter = z["anbieter"]
                while self.aktiv and self.ziele[self.idx]["anbieter"] == anbieter:
                    self.idx += 1
                continue
            if r.status_code >= 400:
                self._weiter(f"HTTP {r.status_code} {r.text[:160]}")
                continue
            try:
                inhalt = r.json()["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, ValueError) as e:
                self._weiter(f"unerwartete Antwort ({e})")
                continue
            inhalt = re.sub(r"<think>.*?</think>", "", inhalt, flags=re.S).strip()
            inhalt = re.sub(r"^```(?:json)?|```$", "", inhalt, flags=re.M).strip()
            treffer = re.search(r"\{.*\}", inhalt, re.S)
            try:
                antwort = json.loads(treffer.group(0) if treffer else inhalt)
            except ValueError:
                log.warning("%s/%s: Antwort ist kein JSON", z["anbieter"], z["modell"])
                return None
            self.modell = f"{z['anbieter']} · {z['modell']}"
            return antwort
        return None


def _bereinigen(d: dict, m: Meldung) -> dict:
    typ = d.get("typ") if d.get("typ") in ("etb", "display", "upc") else "andere"
    status = d.get("status") if d.get("status") in STATUS else "sonstiges"
    sprache = d.get("sprache") if d.get("sprache") in ("de", "en", "jp") else m.sprache

    def datum(x):
        try:
            return datetime.strptime(str(x), "%Y-%m-%d").strftime("%Y-%m-%d") if x else None
        except ValueError:
            return None

    try:
        preis = float(d["preis"]) if d.get("preis") not in (None, "") else None
    except (TypeError, ValueError):
        preis = None
    try:
        hype = max(1, min(10, int(d.get("hype") or 5)))
    except (TypeError, ValueError):
        hype = 5
    gruende = [str(g)[:120] for g in (d.get("gruende") or []) if g][:3]
    welle = d.get("lieferwelle")
    welle = int(welle) if isinstance(welle, (int, float, str)) and str(welle).isdigit() and 0 < int(welle) < 10 else None
    return {
        "lieferwelle": welle or _welle(f"{m.titel} {m.text}"),
        "liefertermin": str(d["liefertermin"])[:40] if d.get("liefertermin") else _liefertermin(f"{m.titel} {m.text}"),
        "relevant": bool(d.get("relevant")) and (typ != "andere" or status == "markt"),
        "typ": typ, "sprache": sprache, "status": status,
        "set": (d.get("set") or None), "set_en": (d.get("set_en") or None),
        "produkt": str(d.get("produkt") or m.titel)[:100],
        "variante": d.get("variante") if d.get("variante") in ("pokemon-center", "18er") else None,
        "vorverkauf_ab": datum(d.get("vorverkauf_ab")), "erscheint_am": datum(d.get("erscheint_am")),
        "preis": preis, "waehrung": d.get("waehrung") if d.get("waehrung") in ("EUR", "USD", "JPY") else None,
        "haendler": (d.get("haendler") or m.haendler_hinweis or None),
        "hype": hype, "trend": d.get("trend") if d.get("trend") in ("steigt", "faellt") else None,
        "gruende": gruende, "kurz": str(d.get("kurz") or m.titel)[:220], "_quelle": "ki",
    }


def einordnen(meldungen: list[Meldung], cfg: Config, ki: KI) -> dict[str, dict]:
    """Liefert {meldung.id: analyse}. Meldungen über dem Kontingent bleiben für den nächsten Lauf."""
    ergebnis: dict[str, dict] = {}
    if not ki.aktiv:
        for m in meldungen:
            ergebnis[m.id] = regeln(m)
        return ergebnis
    heute = datetime.now().strftime("%Y-%m-%d")
    system = SYSTEM_PROMPT.replace("__HEUTE__", heute)
    stapel = meldungen[: cfg.ki_max]
    for start in range(0, len(stapel), 8):
        teil = stapel[start:start + 8]
        user = "\n\n".join(
            f"[{i}] Quelle: {m.quelle} ({m.art}, {m.sprache}) · {m.datum[:10]}\n"
            f"Titel: {m.titel}\n"
            + (f"Preis laut Quelle: {m.preis_hinweis}" + (f" bei {m.haendler_hinweis}" if m.haendler_hinweis else "") + "\n"
               if m.preis_hinweis else "")
            + f"Text: {m.text[:450]}"
            for i, m in enumerate(teil))
        antwort = ki.chat(system, user)
        items = (antwort or {}).get("items") if isinstance(antwort, dict) else None
        if not isinstance(items, list):
            if not ki.aktiv:
                break
            log.warning("KI-Stapel ohne verwertbare Antwort – Regeln für %d Meldungen", len(teil))
            for m in teil:
                ergebnis[m.id] = regeln(m)
            continue
        for pos, d in enumerate(items):
            if not isinstance(d, dict):
                continue
            idx = d.get("i", pos)
            if isinstance(idx, int) and 0 <= idx < len(teil):
                ergebnis[teil[idx].id] = _bereinigen(d, teil[idx])
        for m in teil:
            ergebnis.setdefault(m.id, regeln(m))
        time.sleep(1.2)
    if not ki.aktiv:  # Schlüssel/Modelle ausgefallen: Rest mit Regeln
        for m in stapel:
            ergebnis.setdefault(m.id, regeln(m))
    return ergebnis
