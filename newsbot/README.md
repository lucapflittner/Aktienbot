# newsbot

Ereignisgetriebener Paper-Trading-Bot. Er liest **SEC-Meldungen** (8-K), **Insider-Trades** (Form 4) und **Weltnachrichten** (GDELT, optional RSS). Ein **lokales Sprachmodell** bewertet sie, und der Bot reagiert mit Paper-Trades. Nichts verlässt deinen Rechner außer den Abrufen bei SEC, GDELT und Yahoo.

Ableger vom [Aktienbot](https://github.com/lucapflittner/Aktienbot): Kostenmodell, Paper-Trading-Prinzip, Telegram und die Lehre aus Iteration 73 (*nie* Informationen verwenden, die zum Entscheidungszeitpunkt noch nicht öffentlich waren) sind von dort übernommen.

## Wie es funktioniert

```
SEC EDGAR (8-K, Form 4) ─┐
GDELT Weltnachrichten ───┼─► events (SQLite) ─► Bewertung ─► Signale ─► Paper-Broker ─► Telegram
RSS (optional) ──────────┘                       │                          │
                                                 ├ Insider: feste Regeln    └ NAV vs. SPY
                                                 └ News/8-K/Welt: lokales LLM
```

| Quelle | Was | Wer bewertet |
|---|---|---|
| Form 4 | Insider-Käufe/-Verkäufe am offenen Markt (Code P/S) von S&P-500-Firmen | Regeln: Käufe von CEO/CFO/Direktoren ab 100k $ sind ein gut belegtes Signal, Verkäufe kaum |
| 8-K | Quartalszahlen (Item 2.02), Übernahmen, Wechsel im Management, Abschreibungen, Cyber-Vorfälle … inkl. Pressemitteilung (EX-99) | LLM: Richtung, Stärke, Sicherheit, Horizont, Neuheit |
| GDELT | Schlagzeilen zu 8 Themen (Zölle, Notenbanken, Öl, Geopolitik, Chips, Gesundheit, Banken, Lieferketten), nur etablierte Medien | LLM: welche **Branchen** (Sektor-ETFs XLE, XLK, …) bewegt das |
| RSS | beliebige Feeds, Zuordnung zu Aktien über $TICKER / Firmenname | LLM |

**Signal** pro Aktie bzw. Sektor-ETF = Summe aus Richtung × Stärke × Sicherheit × Neuheit, mit Halbwertszeit 48 h.
**Broker:** nur Long-Positionen, max. 10 Positionen, je 1/10 des Kapitals, Verkauf nach 5 Handelstagen oder wenn das Signal verblasst. 7,5 bp Spread + 1 € pro Order.

### Ehrlichkeitsregeln (eingebaut und getestet)
- Ein Signal ist erst **30 min nach Veröffentlichung** handelbar. Gekauft wird zum **ersten Schlusskurs danach**, nie zu einem früheren Kurs. Eine Meldung um 15:45 New Yorker Zeit wird also erst am nächsten Tag gehandelt.
- `evaluate` misst für jede bewertete Meldung die Rendite nach 1/3/5/10 Tagen **relativ zum Sektor-ETF**, getrennt nach Quelle. Nur das zählt. Liefert eine Quelle nach ein paar hundert Meldungen keinen positiven Mittelwert mit |t| > 2, wird sie abgeschaltet.
- **Kein Backtest mit dem LLM.** Das Modell kennt die Kursentwicklung bis zu seinem Trainings-Stichtag. Alte News bewerten hieße in die Zukunft schauen. Deshalb nur Vorwärtstest.

## Installation (Windows)

1. **Python-Pakete** (z. B. im bestehenden conda-Env):
   ```
   pip install -r requirements.txt
   ```
2. **Lokales Modell**, z. B. mit [Ollama](https://ollama.com):
   ```
   ollama pull <qwen3.6-35b-a3b-tag>     # exakten Tag in der Ollama-Library nachschauen
   ollama list                           # Name merken -> LLM_MODEL in .env
   ```
   Alternativ LM Studio (`http://localhost:1234/v1`) oder `llama-server --jinja` (`http://localhost:8080/v1`).
   Das 35B-MoE-Modell hat nur ~3B aktive Parameter und läuft daher auch teilweise auf der CPU flott. In Q4 braucht es ~20–24 GB RAM+VRAM. Zu groß? Dann ein kleineres Qwen (z. B. 8B oder 14B) eintragen, der Rest bleibt gleich.
3. **Konfiguration:** `.env.example` nach `.env` kopieren und mindestens setzen:
   - `SEC_USER_AGENT=newsbot deine@mail.de`: Pflicht bei der SEC, ohne wird man geblockt
   - `LLM_MODEL=` den Namen aus `ollama list`
   - optional Telegram (gleicher Bot wie beim Aktienbot)
4. **Einrichten und testen:**
   ```
   python -m newsbot setup      # Universum: 503 S&P-Ticker + SEC-CIKs + Sektoren
   python -m newsbot check      # erreicht er das LLM? Test-Bewertung
   python -m newsbot run        # einmal komplett: ingest -> score -> trade
   python -m newsbot report
   ```
5. **Automatisch alle 30 min:** `scripts\install_task.bat` einmal ausführen (legt die Windows-Aufgabe „Newsbot“ an). Deaktivieren: `schtasks /Delete /TN Newsbot /F`.
   Ollama muss dafür laufen. Der PC muss an sein, damit Meldungen bewertet werden. War er aus, holt der Bot die SEC-Meldungen beim nächsten Lauf nach (bis zu 1000 pro Formular-Typ).

## Befehle

| Befehl | Was |
|---|---|
| `python -m newsbot setup [--sectors]` | Universum laden (`--sectors`: Sektoren neu von Yahoo holen) |
| `python -m newsbot check` | LLM-Server erreichbar? Modellname korrekt? |
| `python -m newsbot ingest` | neue SEC-Meldungen, Weltnachrichten, RSS holen |
| `python -m newsbot score` | unbewertete Meldungen bewerten (bei LLM-Ausfall: nächster Lauf) |
| `python -m newsbot trade` | Kurse aktualisieren, Paper-Broker bis zum letzten Schlusskurs |
| `python -m newsbot run` | ingest + score + trade |
| `python -m newsbot report` | NAV vs. SPY, Positionen, stärkste Signale, letzte Bewertungen |
| `python -m newsbot evaluate` | **die ehrliche Auswertung**: Trefferquote und Mehrrendite pro Quelle |
| `python -m pytest` | Tests (offline, inkl. Look-ahead-Tests) |

Alle Parameter (Positionen, Haltedauer, Schwellen, Kosten …) stehen in `newsbot/config.py` und lassen sich per `.env` überschreiben.

## Daten

Alles liegt in `data/newsbot.sqlite` (nicht in Git): Meldungen, Bewertungen, Kurse, Positionen, Trades, NAV. Zum Reinschauen eignet sich z. B. [DB Browser for SQLite](https://sqlitebrowser.org).

## Bekannte Grenzen

- **Tagesschlusskurse:** Bei Meldungen nach Börsenschluss wird der Sprung über Nacht verpasst, gekauft wird erst am nächsten Schlusskurs. Das ist bewusst konservativ, ein echter Broker könnte am nächsten Morgen kaufen.
- **Universum:** fester S&P-500-Stand aus dem Aktienbot (`data/sp500_tickers.txt`). Seitdem übernommene Firmen (z. B. EA, HOLX, KVUE) liefern einfach keine Meldungen mehr.
- **GDELT** drosselt stark: höchstens 1 Anfrage alle 5 s, und Cloud-IPs werden oft abgewiesen. Fällt GDELT aus, laufen die übrigen Quellen normal weiter.
- **Long-only:** negative Signale verhindern nur Käufe bzw. lösen Verkäufe aus.
