# Arbeitsweise & Agenten (global)

## Grundsatz: Token sparen
- Der Hauptagent (Opus) plant, entscheidet und schreibt den Kern-Code selbst.
- Nebenaufgaben werden an günstigere Subagenten (Sonnet/Haiku) delegiert – aber nur, wenn sie wirklich
  eigenständig sind und ihr Ergebnis kurz zurückgemeldet werden kann. Kleine Dinge (eine Datei lesen,
  ein grep, ein Befehl) erledigt der Hauptagent direkt; ein Subagent lohnt sich erst ab mehreren Schritten.
- **Keine automatischen Reviews.** Kein `/code-review`, `/simplify`, `/security-review` und keine
  Review-Agenten, außer ich frage ausdrücklich danach.
- Keine parallelen Agenten-Schwärme. Höchstens 2–3 Subagenten gleichzeitig, und nur bei klar
  unabhängigen Teilaufgaben (z. B. zwei getrennte Recherchefragen).
- Antworten knapp halten, keine langen Zusammenfassungen von dem, was gerade gemacht wurde.

## Wann welcher Agent
| Aufgabe | Agent | Modell |
|---|---|---|
| Web-/Doku-Recherche, Libraries/APIs vergleichen, "wie macht man X" | `researcher` | sonnet |
| Code im Repo finden, "wo wird X benutzt", Überblick über Ordner | `scout` | haiku |
| Klar spezifizierte, mechanische Umsetzung (Boilerplate, Umbenennen über viele Dateien, Tests nach Vorgabe schreiben, Daten/Config-Dateien) | `worker` | sonnet |
| Tests/Build/Lint laufen lassen und nur die Fehler berichten | `test-runner` | haiku |
| Architektur, Debugging schwieriger Bugs, Kernlogik, Entscheidungen | Hauptagent selbst | – |

Regeln für Delegation:
- Prompt an den Subagenten vollständig und konkret formulieren (Ziel, relevante Pfade, gewünschtes
  Ausgabeformat, max. Länge der Antwort). Subagenten kennen den Gesprächskontext nicht.
- Recherche-Ergebnisse als kurze Stichpunkte mit Quellen-URLs zurückfordern, keine Rohdumps.
- Lange Aufgaben (Recherche, Testläufe) im Hintergrund laufen lassen und währenddessen weiterarbeiten.
- Ergebnisse von Subagenten nicht noch einmal komplett selbst nachprüfen – nur stichprobenartig, wenn
  etwas unplausibel wirkt.
- Eingebaute Agenten (`Explore`, `general-purpose`, `Plan`) laufen standardmäßig auf Sonnet
  (`CLAUDE_CODE_SUBAGENT_MODEL=sonnet` in settings.json); `scout` bevorzugen, wenn reine Suche reicht.
