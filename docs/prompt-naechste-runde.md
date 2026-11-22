# Prompt: nächste Runde „YOUR LIFE · YOUR CHOICE“ (Financial Twin, LauzHack 2026)

> Diesen Prompt in eine neue Claude-Code-Session im Repo `Lauzerrrn` geben.
> **Chat-Sprache: Deutsch. Alle Texte in der App (Spiel + Analyse) bleiben Englisch.**

---

## Kontext

Wir bauen für die UBS-Challenge am LauzHack 2026 einen **Financial Twin** als spielbaren Lebenssimulator. Morgen ist der
Pitch (5 min Pitch + 5 min Q&A, Live-Demo). Leitidee der Challenge:

- „Think beyond Monte Carlo“: Eine Simulation allein ist noch kein digitaler Zwilling. Der Zwilling soll den finanziellen
  Zustand verstehen, auf Lebensentscheidungen reagieren, sich mit neuen Daten aktualisieren und **Trade-offs erklären**.
- Open-Source-LLMs (Llama, Qwen, Mistral) für einen **interaktiven Finanz-Agenten**; Entscheidungen als spielbarer
  Lebenssimulator. „Don't predict the future – make it explorable.“
- Für die Demo zählt: Hook (eine Person, ein Dilemma), „show, don't tell“, Stabilität, ein Backup falls die Live-Demo hängt.

**Wichtig:** Lies zuerst `README.md` und `twin/frontend3d/CONTRACT.md` (Payload-Vertrag Python ↔ JS). Architektur:

| Datei | Rolle |
|---|---|
| `twin/session.py` | `GameSession`: Zustandsmaschine (phase boot / play / end / ride), erzeugt den Payload |
| `twin/game.py` | Entscheidungskarten (`OPTIONS`), Sperrgründe, `life_span` (1 Station = 1 Jahr bis 65), `animations()` |
| `twin/engine.py`, `twin/scenarios.py` | Monatliche Monte-Carlo-Engine, Ereignisse (`Study`, `Job`, `HouseBuy`, `ExpenseChange`, …) |
| `twin/ist_zustand.py` | Status quo aus dem Startformular → `Person` |
| `twin/daten_update.py` | `aktualisiere_aus_daten`: spätere Monatsdaten (CSV) einlesen, nachkalibrieren, Aussagen |
| `twin/tipps.py` | Regelbasierte Tipps + Vergleich der Anlagestile (Analyse) |
| `twin/frontend3d/engine.js` | three.js-Welt: Insel, Straße, Stationen, Gebäude (`spot()`, `placeAt()`), Animationen, Intro, Filmfahrt |
| `twin/frontend3d/character.js` | Figuren (Frauen im A-Linien-Kleid wie das WC-Piktogramm), Requisiten, Auto |
| `twin/frontend3d/ui.js`, `ui.css` | Bildschirme, HUD, Karten, Start-Panel, Filmfahrt-Overlay |
| `ui/analyse.py` | Streamlit-Analyse (🙋 eigene Daten zuerst, Reiter „💡 Tips & investing“) |
| `tests/` | pytest (40 Tests) – müssen am Ende grün sein |

Starten: `./start.sh` (Port 8501). Tests: `venv/bin/python -m pytest -q`. Die Challenge-Daten liegen in
`../ai-financial-twin-lauzhack-2026/Data` (nicht im Repo).

---

## Aufgaben

### 1. Nach dem Abschluss: Gap year **oder** Job wählen
Heute folgt auf Bachelor/Master automatisch „First job“ (`Study.salary_after`, Animation `job` in `game.animations`).
- Nach Bachelor oder Master (und Lehre) **kein automatischer Job** mehr. Der Spieler ist danach „graduated / looking“
  und bekommt an der nächsten Station die Wahl: **Gap year** (12 Monate ohne Lohn, eigene Reise-Animation) **oder**
  den passenden Job (Einstieg mit dem Lohn des Abschlusses: Bachelor CHF 5'200, Master CHF 6'300, Lehre CHF 5'000).
- Umsetzung z. B.: `Study` ohne `salary_after` (Zustand nach Ende: „ohne Job“, kein ALV), neue Optionen
  `grad_job` (lock: nur direkt nach Abschluss) und `gap_year`. Die Abschluss-Animation endet ohne Büro.

### 2. Reiter „Time off“: nur noch **Gap year**
Weltreise, 3-Monats-Auszeit und Sabbatjahr entfernen; nur „Gap year“ (12 Monate, danach gleicher Job bzw. Jobsuche).

### 3. Karte: Gebäude an falschen Stellen + größere Karte
- Gebäude landen ab und zu auf der Straße, im Wasser oder in anderen Gebäuden. `spot()` in `engine.js` robuster machen:
  Mindestabstand zur Straße (inkl. Bordstein, ≥ 3 Einheiten zum Gebäuderand, nicht nur zur Mitte), innerhalb der Insel,
  Abstand zu allen bisherigen Gebäuden (`S.used`) **und** zu den Deko-Häusern; Gebäudegröße (Kapelle, Büro-Turm, Uni) als
  Radius berücksichtigen.
- Die Insel **größer** machen (Straße mit 40+ Jahres-Stationen ist eng): Radius ~1.6×, Straße (`ROAD_PTS`) skalieren
  bzw. mehr Kurven, Stationen weiter auseinander. Kamera-Offsets, Intro-Flug und Nebel anpassen.

### 4. Animationen: Figuren laufen nicht ineinander
Hochzeitsgäste, Partner und Avatar überschneiden sich (z. B. beim Gang zum Auto). Einfache Kollisionsvermeidung in
`walkTo` (Wegpunkte um andere Figuren herum oder seitlicher Versatz) und feste, nicht überlappende Stellplätze.

### 5. **Skip**-Button: mehrere Jahre überspringen
Neben „DRIVE ON“ ein Button „SKIP ▶▶“ mit Auswahl (z. B. +5 Jahre, +10 Jahre, bis zum nächsten Ereignis). Python:
neue Aktion `{"action": "skip", "years": n}` → n-mal `choose("stay")` in einem Schritt; die Engine fährt die Strecke in
einem Zug (Animationen der übersprungenen Jahre nur kurz bzw. zusammengefasst).

### 6. Rente als **eigene Option**, danach weiterspielen
Rente ist heute das feste Ende mit 65. Stattdessen: Karte „Retire“ (ab ~60, wählbar; Einkommen = AHV + Pensionskasse,
vereinfacht z. B. 60 % des letzten Lohns) mit der Schaukelstuhl-Animation – danach **weiterspielen** bis z. B. 85
(Lebensspanne in `life_span` / `RETIRE_AGE` entsprechend; Ende = „Life summary“ mit 85). Horizont der Engine ≤ 50 Jahre
beachten (ggf. auf 65 erhöhen).

### 7. **Kinder**kosten einstellbar, bis ca. 18
Bei „Have a child“ Kosten pro Monat einstellbar (Slider/Stepper auf der Karte, Default CHF 1'100) und die Kosten
**enden mit 18** (Auszug). In `scenarios.py`: `ExpenseChange` mit Enddatum (neues Feld `months` oder ein zweites
Ereignis mit negativem Betrag nach 216 Monaten). Animation „Kind zieht aus“ mit 18 (Kind steigt aus dem Auto).

### 8. **Hauspreis** einstellbar
Bei „Buy a home“ Preis einstellbar (z. B. CHF 400'000–2'000'000, Schritt 50'000); Eigenkapital-Sperre (20 % + 2 %
Nebenkosten) und Vorschau rechnen mit dem gewählten Preis. Payload-Erweiterung: Karte bekommt `params`
(`{"price": {"min", "max", "step", "default"}}`), `choose` schickt `{"key", "params"}`.

### 9. **Monatliche Kosten** einstellbar
Im Spiel eine Karte bzw. Einstellung „Adjust monthly costs“ (± CHF pro Monat ab jetzt, `ExpenseChange`).
Hinweis zur CSV: Die hochgeladene CSV enthält nur den **tatsächlichen Nettofluss pro Monat** der Vergangenheit
(Einnahmen minus Ausgaben, optional Kontostand) – sie stellt keine künftigen Kosten ein. Die monatlichen Kosten für die
Zukunft kommen aus dem Status quo (Startformular: Ausgaben, Miete) und den Entscheidungen im Spiel; nach einer Filmfahrt
schätzt `aktualisiere_aus_daten` den typischen Monat neu.

### 10. Analyse: **Graph aus dem Juli-Branch**
Im Branch `origin/Juli` gibt es unter `financial-twin/` einen eigenen Prototyp mit Canvas-Diagramm
(`chart.js`: Vermögensverlauf über das Alter mit Vergleichslinie, Tooltip/Readout pro Monat, Renditeband; `timeline.js`:
Ereignisse auf einem ziehbaren Zeitstrahl). Diesen Graph (Look & Interaktion: Hover-Readout pro Monat, Vergleich
„zwei Lebenswege“, Ereignis-Marker) in die Streamlit-Analyse übernehmen – z. B. als Custom Component oder mit Plotly
nachgebaut – und mit unseren Simulationsdaten (`res.percentiles`, `res.plan.labels`) füttern. Code mit
`git show origin/Juli:financial-twin/chart.js` lesen; nicht den ganzen Branch mergen.

### 11. Analyse: **Avatar mit Chatbot** (Tipps + Fragen beantworten)
- Auf der Analyse-Seite die Spielfigur des Spielers (Avatar aus `game_session.avatar`, als SVG/3D-Snapshot) mit
  Sprechblase/Chat (`st.chat_input`, `st.chat_message`).
- Der Bot kennt den Zustand: Person (`analysis_person`), Kennzahlen, `tipps()`, Ergebnis der Filmfahrt
  (`ride_data["statements"]`), gespielte Entscheidungen. Er gibt **proaktiv 2–3 Tipps** und beantwortet Fragen
  („Was, wenn ich mit 30 ein Haus kaufe?“, „Lohnt sich die Säule 3a?“).
- **Zahlen rechnet immer unser Modell**, das LLM formuliert nur: Tool-Calls bzw. ein kleines Intent-Mapping auf
  `simulate`/`tipps` (z. B. „Hauskauf mit 40 zu CHF 900k“ → Szenario rechnen → Antwort mit Median/Spanne).
- LLM: **Open-Source lokal über Ollama** (z. B. `qwen3:4b`, wie im Juli-Branch: `127.0.0.1:11434`,
  Modell über `TWIN_OLLAMA_MODEL`). **Fallback ohne Modell**: regelbasierte Antworten aus `tipps()`, damit die Demo
  nie hängt. Antworten auf Englisch, kurz, mit Hinweis „not investment advice“.

---

## Rahmen & Qualität
- GUI-Texte Englisch, Chat mit mir Deutsch. Keine XP/Erfolge/Glück (bewusst entfernt). UBS bleibt die Bank beim Hauskauf.
- Payload-Vertrag in `CONTRACT.md` und `README.md` nachziehen; Standalone-Demo (`main.js`) nicht brechen.
- Tests ergänzen (Gap year nach Abschluss, Skip, Rente als Option, Kinder enden mit 18, Hauspreis, Kosten, Chat-Fallback)
  und `venv/bin/python -m pytest -q` grün halten.
- Im Browser prüfen (`./start.sh`, Port 8501 oder eigener Testport): Abschluss → Wahl Gap year/Job, Skip, Rente,
  Hochzeit ohne Überschneidungen, Gebäude-Platzierung auf der größeren Karte, Analyse-Graph und Chatbot (mit und
  ohne Ollama).
- Für den Pitch: Demo-Pfad stabil halten (Beispieldaten → Filmfahrt → Tipps → Chat), Backup-Aufnahme möglich.
- Am Ende committen und nach `main` pushen (Fast-forward, nichts überschreiben).
