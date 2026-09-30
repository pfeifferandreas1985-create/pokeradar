"""Aufruf:  python -m radar [news|markt|abend|alles] [--trocken]

  news   – Quellen prüfen, einordnen, Sofort-Alarme (alle 20 Minuten)
  markt  – Cardmarket-Preise holen, Verlauf fortschreiben, Preisalarme (täglich)
  abend  – Abendübersicht senden (täglich ~19 Uhr)
  alles  – markt + news (für den ersten Lauf)
  ki-test – ordnet die 8 neuesten Meldungen per KI ein und zeigt das Ergebnis (speichert nichts)
  --trocken  keine Push-Nachrichten, nur Ausgabe im Log
"""
from __future__ import annotations

import logging
import sys

from . import marktlauf, news, site
from .common import Config, log
from .notify import Ntfy


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    modus = next((a for a in argv if not a.startswith("-")), "news")
    if modus == "ki-test":
        return ki_test(Config.load())
    if modus not in ("news", "markt", "abend", "alles"):
        print(__doc__)
        return 2
    cfg = Config.load()
    ntfy = Ntfy(trocken="--trocken" in argv)
    if ntfy.trocken and "--trocken" not in argv:
        log.warning("NTFY_TOPIC fehlt – Nachrichten werden nur protokolliert")
    info: dict = {}
    if modus in ("markt", "alles"):
        try:
            info.update(marktlauf.lauf(cfg, ntfy))
        except Exception as e:  # noqa: BLE001 – der News-Teil soll trotzdem laufen
            log.error("Markt-Lauf fehlgeschlagen: %s", e)
            if modus == "markt":
                raise
    if modus in ("news", "alles"):
        info.update(news.lauf(cfg, ntfy, marktlauf.markt_index()))
    if modus == "abend":
        marktlauf.abend(cfg, ntfy)
    site.bauen(cfg, info)
    return 0


def ki_test(cfg: Config) -> int:
    from .classify import KI, einordnen
    from .sources import sammeln
    ki = KI(cfg)
    if not ki.aktiv:
        log.error("Keine KI verfügbar (kein Schlüssel / kein lokaler Server)")
        return 1
    meldungen = sammeln()[0][:8]
    ergebnis = einordnen(meldungen, cfg, ki)
    for m in meldungen:
        a = ergebnis.get(m.id)
        if a:
            print(f"{a['_quelle']:6} {a['typ']:7} {a['status']:13} {a['sprache']} hype {a['hype']:>2}  "
                  f"{m.titel[:70]}\n       → {a['kurz'][:110]}")
    print(f"Modell: {ki.modell} · {ki.aufrufe} Aufrufe")
    return 0 if ki.modell else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
