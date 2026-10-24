"""Nachrichtenquellen: RSS/Atom-Feeds von News, Deals und Community."""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlsplit

from .common import http, iso, log, now, parse_iso, sha

MAX_ALTER_TAGE = 21


@dataclass
class Meldung:
    id: str
    titel: str
    link: str
    quelle: str
    sprache: str          # Sprachhinweis der Quelle: de / en / jp
    art: str              # news / deal / community
    datum: str
    text: str = ""
    preis_hinweis: str | None = None
    haendler_hinweis: str | None = None
    autor: str | None = None
    forum: bool = False   # Nutzerbeitrag, nicht redaktionell geprüft
    belege: list[str] = field(default_factory=list)  # Händler, auf die der Beitrag direkt verweist
    extra: dict = field(default_factory=dict)


def _gnews(q: str, sprache: str) -> str:
    region = {"de": "hl=de&gl=DE&ceid=DE:de",
              "en": "hl=en-US&gl=US&ceid=US:en",
              "jp": "hl=ja&gl=JP&ceid=JP:ja"}[sprache]
    return f"https://news.google.com/rss/search?q={quote_plus(q + ' when:7d')}&{region}"


# (Name, URL, Sprache, Art)
QUELLEN: list[tuple[str, str, str, str]] = [
    # Deutsch
    ("Google News", _gnews("Pokémon Top-Trainer-Box", "de"), "de", "news"),
    ("Google News", _gnews("Pokémon Display vorbestellen", "de"), "de", "news"),
    ("Google News", _gnews("Pokémon Ultra-Premium-Kollektion", "de"), "de", "news"),
    ("Google News", _gnews("Pokémon Sammelkartenspiel Erweiterung", "de"), "de", "news"),
    ("Google News", _gnews("Pokémon Top-Trainer-Box günstig", "de"), "de", "news"),
    ("mydealz", "https://www.mydealz.de/rss/gruppe/pokemon", "de", "deal"),
    ("Preisjäger", "https://www.preisjaeger.at/rss/gruppe/pokemon", "de", "deal"),  # Österreich, EU-Versand
    # Englisch
    ("Google News", _gnews("Pokemon TCG Elite Trainer Box", "en"), "en", "news"),
    ("Google News", _gnews("Pokemon TCG booster box preorder", "en"), "en", "news"),
    ("Google News", _gnews("Pokemon Ultra Premium Collection", "en"), "en", "news"),
    ("Google News", _gnews("Pokemon Center exclusive TCG", "en"), "en", "news"),
    ("Google News", _gnews("Pokemon TCG sealed prices", "en"), "en", "news"),
    ("Google News", _gnews("Pokemon elite trainer box deal", "en"), "en", "news"),
    ("hotukdeals", "https://www.hotukdeals.com/rss/tag/pokemon", "en", "deal"),  # UK, gleiche Plattform wie mydealz
    ("Reddit", "https://www.reddit.com/r/PKMNTCGDeals/new/.rss", "en", "deal"),
    ("Reddit", "https://www.reddit.com/r/PokeInvesting/new/.rss", "en", "community"),
    # Japanisch
    ("Google News", _gnews("ポケモンカード 予約 BOX", "jp"), "jp", "news"),
    ("Google News", _gnews("ポケモンカード 新弾 発売", "jp"), "jp", "news"),
    ("Google News", _gnews("ポケカ 拡張パック 抽選", "jp"), "jp", "news"),
]

# Foren: Beiträge von Nutzern. Sie lösen nur mit Händler-Beleg einen Sofort-Alarm aus.
FOREN = {"Reddit", "mydealz", "Preisjäger", "hotukdeals"}

NS = {"atom": "http://www.w3.org/2005/Atom",
      "media": "http://search.yahoo.com/mrss/",
      "pepper": "http://www.pepper.com/rss"}

_TAG = re.compile(r"<[^>]+>")
_HREF = re.compile(r'href="([^"]+)"')
# Links, die keinen Händler belegen: Diskussion, Bilder, Chats, Marktplätze von Privatleuten
_KEIN_SHOP = re.compile(r"(^|\.)(reddit\.com|redd\.it|imgur\.com|discord\.gg|discord\.com|youtube\.com|youtu\.be|"
                        r"twitter\.com|x\.com|instagram\.com|tiktok\.com|facebook\.com|ebay\.[a-z.]+)$", re.I)
# Anzeigen und Bot-Beiträge (z. B. "… $149 Promotion by eBay!" vom AutoModerator)
_WERBUNG = re.compile(r"promotion by ebay|\bsponsored\b|\[(ad|anzeige|werbung)\]", re.I)
_BOTS = {"/u/AutoModerator"}
_WS = re.compile(r"\s+")

# Grober Vorfilter, damit die KI nur Kandidaten sieht
_POKE = re.compile(r"pok[eé]mon|pkmn|ポケモン|ポケカ|\btcg\b|glurak|charizard|pikachu|evoli|eevee", re.I)
_PROD = re.compile(
    r"elite.?trainer|\betb\b|top.?trainer|booster.?box|booster.?display|\bdisplay\b|"
    r"ultra.?premium|\bupc\b|premium.?(collection|kollektion)|36er|18er|"
    r"\bbox\b|ボックス|BOX|拡張パック|ハイクラス|強化拡張|予約|抽選|"
    r"pre.?order|vorbestell|restock|nachschub|sealed|set|erweiterung|expansion",
    re.I)


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", "".join(el.itertext())))).strip()


def _shops(roh: str) -> list[str]:
    """Händler-Domains aus den Links eines Forenbeitrags."""
    out = []
    for link in _HREF.findall(html.unescape(roh)):
        host = (urlsplit(link).hostname or "").removeprefix("www.")
        if host and not _KEIN_SHOP.search(host) and host not in out:
            out.append(host)
    return out


def werbung(m: Meldung) -> bool:
    return m.autor in _BOTS or bool(_WERBUNG.search(m.titel))


def _datum(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return iso(parsedate_to_datetime(s))
    except (TypeError, ValueError):
        pass
    try:
        return iso(parse_iso(s))
    except ValueError:
        return None


def _parse(xml: bytes, name: str, sprache: str, art: str) -> list[Meldung]:
    root = ET.fromstring(xml)
    out: list[Meldung] = []
    items = root.findall(".//item")
    if items:  # RSS 2.0
        for it in items:
            titel = _text(it.find("title"))
            link = (it.findtext("link") or "").strip()
            guid = (it.findtext("guid") or link).strip()
            merchant = it.find("pepper:merchant", NS)
            quelle = name
            src = it.find("source")
            if name == "Google News" and src is not None and src.text:
                quelle = src.text.strip()
                titel = re.sub(r"\s+-\s+" + re.escape(quelle) + r"$", "", titel)
            out.append(Meldung(
                id=sha(guid or titel), titel=titel, link=link, quelle=quelle,
                sprache=sprache, art=art,
                datum=_datum(it.findtext("pubDate") or "") or iso(now()),
                text=_text(it.find("description"))[:700],
                preis_hinweis=merchant.get("price") if merchant is not None else None,
                haendler_hinweis=merchant.get("name") if merchant is not None else None,
                forum=name in FOREN,
                # Deals auf mydealz & Co. verlinken immer den Händler; der steht im merchant-Feld
                belege=[merchant.get("name") or "mydealz"] if merchant is not None else [],
            ))
        return out
    for en in root.findall("atom:entry", NS):  # Atom (Reddit)
        titel = _text(en.find("atom:title", NS))
        link_el = en.find("atom:link", NS)
        link = link_el.get("href", "") if link_el is not None else ""
        eid = en.findtext("atom:id", default=link, namespaces=NS)
        datum = en.findtext("atom:published", default="", namespaces=NS) or \
            en.findtext("atom:updated", default="", namespaces=NS)
        inhalt = en.find("atom:content", NS)
        out.append(Meldung(
            id=sha(eid or titel), titel=titel, link=link, quelle=name, sprache=sprache,
            art=art, datum=_datum(datum) or iso(now()),
            text=_text(inhalt)[:700],
            autor=(en.findtext("atom:author/atom:name", default="", namespaces=NS) or "").strip() or None,
            forum=name in FOREN,
            belege=_shops("".join(inhalt.itertext())) if inhalt is not None else [],
        ))
    return out


def relevant(m: Meldung) -> bool:
    blob = f"{m.titel} {m.text[:300]}"
    poke = _POKE.search(blob) or m.quelle in ("Reddit",)
    return bool(poke and _PROD.search(blob))


def sammeln() -> tuple[list[Meldung], dict[str, str]]:
    """Holt alle Quellen. Fehler einzelner Quellen stoppen den Lauf nicht."""
    grenze = now() - timedelta(days=MAX_ALTER_TAGE)
    gesehen_titel: set[str] = set()
    alle: list[Meldung] = []
    status: dict[str, str] = {}
    for name, url, sprache, art in QUELLEN:
        key = f"{name} ({sprache})" if name != "Google News" else f"Google News ({sprache})"
        try:
            r = None
            for versuch in range(2):
                if name == "Reddit":  # Reddit drosselt schnelle Folgeanfragen
                    time.sleep(4 + 6 * versuch)
                r = http().get(url, timeout=25)
                if r.status_code != 429:
                    break
            r.raise_for_status()
            meldungen = _parse(r.content, name, sprache, art)
        except Exception as e:  # noqa: BLE001 – jede Quelle darf ausfallen
            log.warning("Quelle %s nicht erreichbar: %s", key, e)
            status.setdefault(key, "fehler")
            continue
        status[key] = "ok"
        for m in meldungen:
            if parse_iso(m.datum) < grenze or werbung(m) or not relevant(m):
                continue
            norm = re.sub(r"\W+", "", m.titel.lower())
            if norm in gesehen_titel:
                continue
            gesehen_titel.add(norm)
            alle.append(m)
    alle.sort(key=lambda m: m.datum, reverse=True)
    log.info("%d relevante Meldungen aus %d Quellen", len(alle), len(QUELLEN))
    return alle, status
