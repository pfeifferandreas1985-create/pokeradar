"""Deutsche → englische Setnamen (TCGdex), damit deutsche Angebote einen Cardmarket-Vergleich bekommen.

Cardmarket führt nur englische Namen. Ohne Übersetzung bekommt z. B. eine "Dunkelnacht Top-Trainer-Box"
(= Pitch Black) keinen Marktpreis – und damit nie mehr als 3 Pokébälle.
"""
from __future__ import annotations

from .common import DATA, http, log, now, read_json, write_json
from .market import _norm

DATEI = DATA / "setnamen.json"
URL = "https://api.tcgdex.net/v2/{}/sets"
# Deutsche Setnamen, die zugleich gewöhnliche Wörter in Schlagzeilen sind
MEHRDEUTIG = {"evolution", "triumph", "expedition", "entfesselt", "unerschrocken"}


def laden() -> dict[str, str]:
    """{deutscher Name: englischer Name}, einmal pro Tag frisch von TCGdex."""
    d = read_json(DATEI, {})
    heute = now().strftime("%Y-%m-%d")
    if d.get("tag") == heute:
        return d["namen"]
    try:
        de = {s["id"]: s["name"] for s in http().get(URL.format("de"), timeout=30).json()}
        en = {s["id"]: s["name"] for s in http().get(URL.format("en"), timeout=30).json()}
        namen = {de[i]: en[i] for i in de if i in en and _norm(de[i]) != _norm(en[i])
                 and _norm(de[i]) not in MEHRDEUTIG}
        if namen:
            write_json(DATEI, {"tag": heute, "namen": namen})
            return namen
    except Exception as e:  # noqa: BLE001
        log.warning("Setnamen (TCGdex) nicht abrufbar: %s", e)
    return d.get("namen") or {}


def englisch(texte: list[str | None], namen: dict[str, str]) -> str | None:
    """Englischer Name des deutschen Setnamens, der in den Texten steht.

    Bei mehreren Treffern zählt der späteste ("Mega-Entwicklung Erhabene Helden" → Erhabene Helden),
    bei gleicher Stelle der längste ("30 Jahre: Klassische Sammlung" vor "30 Jahre").
    """
    bester, rang = None, (-1, 0)
    for t in texte:
        if not t:
            continue
        text = f" {_norm(t)} "
        for de, en in namen.items():
            pos = text.find(f" {_norm(de)} ")
            if pos >= 0 and (pos, len(de)) > rang:
                bester, rang = en, (pos, len(de))
    return bester
