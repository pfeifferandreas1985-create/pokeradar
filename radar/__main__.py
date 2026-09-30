"""Aufruf:  python -m radar [news|markt|abend|alles] [--trocken]

  news   – Quellen prüfen, einordnen, Sofort-Alarme (alle 20 Minuten)
  markt  – Cardmarket-Preise holen, Verlauf fortschreiben, Preisalarme (täglich)
  abend  – Abendübersicht senden (täglich ~19 Uhr)
  alles  – markt + news (für den ersten Lauf)
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
