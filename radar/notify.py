"""Push-Nachrichten über ntfy (App für Android/iOS, kein Konto nötig)."""
from __future__ import annotations

import os

from .common import http, log
from .rating import baelle

SPRACH_LABEL = {"de": "DE", "en": "EN", "jp": "JP", "int": "DE/EN"}
TYP_LABEL = {"etb": "Elite-Trainer-Box", "display": "Display", "upc": "Ultra-Premium-Kollektion"}


class Ntfy:
    def __init__(self, trocken: bool = False):
        self.server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        self.topic = os.environ.get("NTFY_TOPIC", "").strip()
        self.token = os.environ.get("NTFY_TOKEN", "").strip()
        self.trocken = trocken or not self.topic
        self.dashboard = os.environ.get("DASHBOARD_URL", "").strip()
        self.gesendet: list[dict] = []

    def senden(self, titel: str, text: str, *, prio: int = 3, tags: list[str] | None = None,
               link: str | None = None) -> bool:
        body = {"topic": self.topic, "title": titel[:250], "message": text[:3900],
                "priority": prio, "tags": tags or []}
        if link:
            body["click"] = link
        actions = []
        if link:
            actions.append({"action": "view", "label": "Öffnen", "url": link})
        if self.dashboard:
            actions.append({"action": "view", "label": "Radar", "url": self.dashboard})
        if actions:
            body["actions"] = actions
        self.gesendet.append(body)
        if self.trocken:
            log.info("[Trocken] %s\n%s", titel, text)
            return True
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            r = http().post(self.server, json=body, headers=headers, timeout=20)
            r.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            log.error("ntfy-Versand fehlgeschlagen: %s", e)
            return False


def rating_zeilen(r: dict) -> str:
    zeilen = [f"{baelle(r['sterne'])}  {r['urteil']}"]
    zeilen += [f"• {g}" for g in r["gruende"]]
    return "\n".join(zeilen)


def kopf(p: dict) -> str:
    teile = [TYP_LABEL.get(p.get("typ"), ""), SPRACH_LABEL.get(p.get("sprache"), "")]
    return " · ".join(t for t in teile if t)
