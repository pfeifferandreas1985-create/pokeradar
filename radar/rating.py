"""Radar-Rating: 1–5 Pokébälle plus nachvollziehbare Begründung.

Das Rating fasst nur die vorliegenden Fakten zusammen (Hype, Abstand zum Marktpreis,
Preisverlauf, Lieferwelle). Es ist eine Einschätzung, keine Anlageberatung.
"""
from __future__ import annotations

URTEIL = {5: "Top-Chance", 4: "Lohnt sich", 3: "Interessant", 2: "Abwarten", 1: "Eher nicht"}


def _eur(x: float | None) -> str:
    return "–" if x is None else f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x: float) -> str:
    return f"{x:+.0f} %".replace("-", "−")


def _welle(p: dict, gruende: list[str]) -> int:
    welle = p.get("lieferwelle")
    termin = p.get("liefertermin")
    if welle == 1:
        gruende.append("Lieferwelle 1 – Lieferung zum Release" + (f" ({termin})" if termin else ""))
        return 0
    if welle and welle >= 2:
        gruende.append(f"Nur Lieferwelle {welle}" + (f" ({termin})" if termin else "")
                       + " – spätere Lieferung, Kürzungen möglich")
        return -1
    if termin:
        gruende.append(f"Lieferung voraussichtlich {termin}")
    return 0


def _clamp(x: float) -> int:
    return int(max(1, min(5, round(x))))


def bewerten(art: str, p: dict, markt: dict | None = None) -> dict:
    """art: neu | vorverkauf | nachschub | angebot | markt"""
    gruende: list[str] = []
    hype = p.get("hype") or 5
    ch7 = (markt or {}).get("ch7")
    ch30 = (markt or {}).get("ch30")
    trend = (markt or {}).get("trend")

    if art == "angebot":
        preis = p.get("preis_eur")
        rabatt = p.get("rabatt")
        if rabatt is not None and trend:
            sterne = 5 if rabatt >= 35 else 4 if rabatt >= 25 else 3 if rabatt >= 15 else 2 if rabatt >= 5 else 1
            if rabatt > 0:
                gruende.append(f"{rabatt:.0f} % unter Cardmarket-Trend ({_eur(preis)} statt {_eur(trend)})")
            else:
                gruende.append(f"Kein Vorteil: {_eur(preis)} liegt über dem Cardmarket-Trend ({_eur(trend)})")
        else:
            sterne = 2 + (1 if hype >= 8 else 0)
            gruende.append("Kein Cardmarket-Vergleich gefunden – Preis bitte selbst prüfen")
        if ch30 is not None and ch30 >= 8:
            sterne += 1
            gruende.append(f"Marktpreis steigt ({_pct(ch30)} in 30 Tagen)")
        elif ch7 is not None and ch7 <= -10:
            sterne -= 1
            gruende.append(f"Marktpreis fällt gerade ({_pct(ch7)} in 7 Tagen)")
        if hype >= 8:
            gruende.append(f"Begehrtes Produkt (Hype {hype}/10)")
        sterne += _welle(p, gruende)
        if p.get("waehrung") not in (None, "EUR"):
            sterne -= 1
            gruende.append("Händler außerhalb der EU – Versand/Zoll nicht eingerechnet")

    elif art == "markt":
        sterne = 3
        if ch7 is not None and ch7 >= 0:
            if ch30 is not None and ch30 >= 20:
                sterne = 4
                gruende.append(f"Anhaltender Aufwärtstrend ({_pct(ch30)} in 30 Tagen)")
            gruende.append(f"{_pct(ch7)} in 7 Tagen – Nachfrage zieht an, Einstieg wird teurer")
            if (markt or {}).get("hoch") and trend and trend >= markt["hoch"] * 0.99:
                gruende.append("Auf Allzeithoch seit Beobachtungsbeginn")
        elif ch7 is not None:
            if ch30 is not None and ch30 > 0:
                gruende.append(f"Rücksetzer ({_pct(ch7)} in 7 Tagen) nach Anstieg – mögliche Einstiegschance")
            else:
                sterne = 2
                gruende.append(f"Preis fällt ({_pct(ch7)} in 7 Tagen, {_pct(ch30 or 0)} in 30 Tagen) – abwarten")
        if (markt or {}).get("low") and trend and markt["low"] < trend * 0.85:
            gruende.append(f"Günstigstes Angebot ab {_eur(markt['low'])}")

    else:  # neu / vorverkauf / nachschub
        sterne = 5 if hype >= 9 else 4 if hype >= 8 else 3 if hype >= 6 else 2 if hype >= 4 else 1
        gruende.extend(p.get("gruende") or [])
        if art == "vorverkauf":
            gruende.insert(0, "Vorbestellung ist offen – bei begehrten Boxen oft in Stunden weg")
        if art == "nachschub":
            gruende.insert(0, "Nachschub – kurze Gelegenheit zum Originalpreis")
        if markt and trend and p.get("preis_eur") and trend > p["preis_eur"] * 1.2:
            sterne += 1
            gruende.append(f"Marktpreis schon {_eur(trend)} – über dem Angebotspreis")
        sterne += _welle(p, gruende)

    sterne = _clamp(sterne)
    # Doppelte Gründe entfernen, Reihenfolge behalten
    seen, gr = set(), []
    for g in gruende:
        if g and g not in seen:
            seen.add(g)
            gr.append(g)
    return {"sterne": sterne, "urteil": URTEIL[sterne], "gruende": gr[:4]}


def baelle(sterne: int) -> str:
    return "●" * sterne + "○" * (5 - sterne)
