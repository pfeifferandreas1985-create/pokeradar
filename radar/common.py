"""Gemeinsame Helfer: Pfade, Konfiguration, HTTP, JSON-Ablage."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"          # interner Zustand (gesehen, Produkte, Preisverlauf)
SITE_DATA = ROOT / "docs" / "data"  # was das Dashboard lädt

SPRACHEN = ("de", "en", "jp")
PRODUKTE = ("etb", "display", "upc")

USER_AGENT = "Pokeradar/1.0 (privater Release-Monitor; +https://github.com)"

log = logging.getLogger("radar")


@dataclass
class Config:
    sprachen: list[str]
    produkte: list[str]
    sofort_ab_hype: int = 8
    vorverkauf_sofort: bool = True
    schnaeppchen_ab_rating: int = 4
    abenduebersicht: bool = True
    alarm_prozent: float = 15
    mindestpreis: float = 40
    cases: bool = False
    ki_anbieter: list[dict] = field(default_factory=list)
    ki_max: int = 64
    ki_budget: float = 480

    @staticmethod
    def load(path: Path = ROOT / "config.yaml") -> "Config":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        b = raw.get("benachrichtigung") or {}
        m = raw.get("markt") or {}
        k = raw.get("ki") or {}
        sprachen = [s for s in (raw.get("sprachen") or ["de", "en"]) if s in SPRACHEN]
        produkte = [p for p in (raw.get("produkte") or list(PRODUKTE)) if p in PRODUKTE]
        return Config(
            sprachen=sprachen or ["de", "en"],
            produkte=produkte or list(PRODUKTE),
            sofort_ab_hype=int(b.get("sofort_ab_hype", 8)),
            vorverkauf_sofort=bool(b.get("vorverkauf_sofort", True)),
            schnaeppchen_ab_rating=int(b.get("schnaeppchen_ab_rating", 4)),
            abenduebersicht=bool(b.get("abenduebersicht", True)),
            alarm_prozent=float(m.get("alarm_prozent", 15)),
            mindestpreis=float(m.get("mindestpreis", 40)),
            cases=bool(m.get("cases", False)),
            ki_anbieter=[{"name": str(a.get("name", "KI")), "basis_url": str(a["basis_url"]),
                          "schluessel": [a["schluessel"]] if isinstance(a.get("schluessel"), str)
                          else list(a.get("schluessel") or []),
                          "modelle": list(a.get("modelle") or []), "extra": a.get("extra") or {}}
                         for a in (k.get("anbieter") or []) if a.get("basis_url")],
            ki_max=int(k.get("max_meldungen_pro_lauf", 64)),
            ki_budget=float(k.get("zeitbudget_sekunden", 480)),
        )

    def public(self) -> dict:
        return {"sprachen": self.sprachen, "produkte": self.produkte,
                "alarm_prozent": self.alarm_prozent, "mindestpreis": self.mindestpreis}


_session: requests.Session | None = None


def http() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT,
                                 "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,ja;q=0.6"})
    return _session


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKC", s.lower())
    return {t for t in re.findall(r"[\w぀-ヿ一-鿿]+", s) if len(t) > 1}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        log.warning("Beschädigte Datei %s – starte leer", path)
        return default


def write_json(path: Path, obj, *, compact: bool = False) -> bool:
    """Schreibt nur, wenn sich der Inhalt ändert (hält die Git-Historie klein)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)
    text += "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8", newline="\n")
    return True
