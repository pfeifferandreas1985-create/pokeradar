# Pokéradar ⚡

Findet limitierte **Pokémon-TCG-Boxen** (Elite-Trainer-Boxen, Displays, Ultra-Premium-Kollektionen),
bevor sie weg sind: Ankündigungen, Vorverkaufsstarts, Nachschub, Schnäppchen und Preisbewegungen.
Jede Meldung bekommt ein **Radar-Rating** (1–5 Pokébälle) mit Begründung, landet als Push auf dem Handy
und im Dashboard.

```
Google News (DE/EN/JP) ─┐
mydealz · Reddit ───────┼─► KI-Einordnung (GLM-Flash, gratis) ─► Rating ─► ntfy-Push
Cardmarket-Preise ──────┘        oder eingebaute Regeln           │
                                                                  └─► Dashboard (GitHub Pages)
```

## Was du bekommst

| Push | Wann |
|---|---|
| 🟢 **Jetzt vorbestellbar** / 🔁 **Nachschub** | sofort, sobald eine passende Box bestellbar ist |
| ✨ **Neu angekündigt** | sofort ab Hype 8/10, sonst in der Abendübersicht |
| 💸 **Schnäppchen** | Angebot ab 4 Pokébällen – gerechnet gegen den Cardmarket-Trendpreis |
| 📈 / 📉 **Stark gestiegen / gefallen** | ±15 % in 7 Tagen (ab ca. 8 Tagen Preisverlauf) |
| 🌙 **Abendübersicht** | täglich gegen 19 Uhr, nur wenn es etwas gibt |

Jede Nachricht enthält Rating und Gründe, z. B.:

```
💸 Schnäppchen: 30th Celebration Elite Trainer Box
Elite-Trainer-Box · EN · Amazon · 79,25 €

●●●●○  Lohnt sich
• 41 % unter Cardmarket-Trend (79,25 € statt 135,27 €)
• Lieferwelle 1 – Lieferung zum Release
```

**Lieferwellen:** Bei Vorbestellungen erkennt das Radar „Welle 1/2/3“ und den Liefertermin.
Welle 1 bedeutet Lieferung zum Release, spätere Wellen kosten einen Pokéball (spätere Lieferung, Kürzungen möglich).

## Einrichtung (einmalig, ca. 10 Minuten)

1. **ntfy-App** installieren (Android/iOS, kostenlos, kein Konto) → „Thema abonnieren“ →
   deinen geheimen Themennamen eintragen (steht im GitHub-Secret `NTFY_TOPIC`).
2. **Kostenloser KI-Schlüssel** (optional, macht das Radar deutlich klüger). Einer reicht, mehrere
   dienen als Reserve – das Radar nimmt den ersten, der funktioniert:

   | Anbieter | Modelle (gratis) | Secret |
   |---|---|---|
   | [SiliconFlow](https://cloud.siliconflow.com) – Handynummer nötig, großzügige Limits | Qwen3-8B, GLM-4-9B | `SILICONFLOW_API_KEY` |
   | [OpenRouter](https://openrouter.ai) – nur E-Mail, ca. 50 Anfragen/Tag | Qwen 3.8 27B | `OPENROUTER_API_KEY` |
   | [Z.ai](https://z.ai/manage-apikey/apikey-list) – API-Schlüssel, **nicht** der Coding-Plan | GLM-4.7/4.5-Flash | `ZAI_API_KEY` |

   Speichern im Terminal, z. B. `gh secret set OPENROUTER_API_KEY` (Schlüssel einfügen, Enter).
   Ohne Schlüssel arbeitet das Radar mit eingebauten Regeln.
3. Fertig. Der Workflow läuft alle 20 Minuten, die Preise einmal täglich.

## Einstellungen

Alles in [`config.yaml`](config.yaml): Sprachen (`de`, `en`, `jp`), Produktarten, ab welchem Hype/Rating
sofort gepusht wird, Preisalarm-Schwelle, Mindestpreis. Im Dashboard lassen sich Sprache und Produktart
zusätzlich live filtern.

## Lokal ausprobieren

```bash
pip install -r requirements.txt
python -m radar alles --trocken     # ohne Push, nur Ausgabe
python -m http.server 8765 --directory docs
```

## Gut zu wissen

- **Preisverlauf:** Cardmarket veröffentlicht für versiegelte Produkte nur den Tagespreis. Das Radar speichert
  täglich einen Schnappschuss (`data/prices/`); 7-Tage-Bewegungen gibt es daher nach etwa einer Woche,
  30-Tage-Trends nach einem Monat.
- **DE/EN im Markt:** Cardmarket führt deutsche und englische Boxen als ein Produkt – der Preis gilt für beide.
- **US-Angebote** (Reddit, US-News) werden in Euro umgerechnet, bekommen aber einen Pokéball Abzug,
  weil Versand und Zoll fehlen.
- **Kein Auto-Kauf.** Das Radar meldet, du entscheidest und bestellst selbst.
- **Radar-Rating** ist eine Einschätzung aus Hype, Preisabstand, Preisverlauf und Lieferwelle – keine Anlageberatung.
- GitHub pausiert geplante Workflows nach 60 Tagen ohne Aktivität; die regelmäßigen Daten-Commits halten das Repo aktiv.

Inoffizielles Fanprojekt. Pokémon ist eine Marke von Nintendo, Creatures und GAME FREAK.
