# Prompt: "Lebensweg" – gamifizierter Financial Twin

Baue ein sehr gamifiziertes 3D-Lebenssimulationsspiel im Browser, das einen Finanz-Zwilling (Financial Twin) erlebbar macht. Eigener Stil, keine Kopie bestehender Spiele.

**Look & Feel**
- Verspielter Spielzeug-3D-Stil (rundliche Low-Poly-Formen, weiche Schatten, kräftige Farben), umgesetzt mit three.js.
- Alle Buttons sind abgerundet (Pillenform), grosse Icons, Konfetti, Toasts, Sound-freundliche Mikro-Animationen.

**1. Charakter-Editor (wie in einem Rollenspiel)**
- Die 3D-Figur steht auf einer drehbaren Plattform, links und rechts davon grosse ◀ ▶ Buttons.
- Kategorien als Chips oben: Geschlecht, Hautton, Frisur, Haarfarbe, Hut, Outfit, Farbe, Auto. Die Pfeile wechseln die Variante der aktiven Kategorie, ein 🎲-Button würfelt nur das Aussehen.
- Ziehen dreht die Figur, die Auswahl wird sofort gespeichert.

**2. Spielwelt**
- Eine Insel mit kurviger Straße. Jede Station ist ein Lebensjahr (z. B. 20 bis 35), das Auto mit der Figur fährt animiert von Station zu Station.
- Zwischen den Stationen gibt es **keine Würfel**: Der Spieler **wählt** bei jeder Station aus Kategorien-Tabs (🎓 Bildung, 💼 Karriere, 🏡 Wohnen, 👨‍👩‍👧 Familie, 🏝️ Auszeit, 💰 Geld). Zur Wahl stehen z. B. Bachelor, Master, Lehre, Einstiegs-, Büro- oder Tech-Job, Jobwechsel, Weiterbildung, Startup, Teilzeit, Eigentumswohnung, Haus, Auto, Hochzeit, Kind, Weltreise, Auszeit 3 oder 12 Monate, Sparen und – erst ab der zweiten Station – der Anlagestil (vorsichtig, ausgewogen, mutig).
- Gesperrte Optionen bleiben sichtbar, mit Grund (🔒 „Erst Bachelor abschliessen“, „Eigenkapital fehlt: CHF 98'000“).
- Jede Karte zeigt eine Vorschau aus dem Finanzmodell: 😊 Glück, 💰 Vermögensdifferenz mit 35, 💳 Kreditrisiko, Spanne der möglichen Ergebnisse.

**3. Animationen passend zur Lebenssituation**
- Uniabschluss: Ein Uni-Gebäude erscheint, die Figur geht hinein und kommt mit Doktorhut und Diplom wieder heraus, Konfetti.
- Job: Ein Bürohochhaus erscheint, die Figur kommt im Anzug mit Aktenkoffer heraus, Münzen fliegen.
- Auszeit: Strand mit Schirm, Palme und Handtuch, die Figur trägt Strohhut und Sonnenbrille und entspannt.
- Immobilienkauf: Das Haus fällt von oben auf die Map, Staubwolke, Schlüssel-Emoji, Jubel.
- Kind: Herzen steigen auf, die Figur hält ein Baby im Arm, danach sitzt das Kind hinten im Auto.
- Rente (Finale): graue Haare, Gehstock, Schaukelstuhl, der Himmel färbt sich zum Sonnenuntergang.

**4. Gamification**
- Keine XP und keine Level.
- Zu Beginn wird der Ist-Zustand abgefragt (Alter, Situation, Einkommen, Ausgaben, Miete, Konto, Anlagen, Schulden); Beispielprofile füllen das Formular nur vor.
- Glücks-Meter (0–100) als Gegenspieler zum Vermögen.
- 12 Erfolge (z. B. Erster Job, Notgroschen, 100k-Club, Schuldenfrei, Eigene vier Wände) mit Toast und Ballons beim Freischalten.
- Quests aus den Zielen der Person (z. B. Notgroschen CHF 12'800 bis 25), mit Fortschrittsbalken.
- Am Ende ein Lebens-Score (Vermögen + Glück + Erfolge) mit Sternen, dazu das Perzentil des eigenen Lebens unter allen möglichen Leben mit denselben Entscheidungen.

**5. Finanzlogik (ehrlich und erklärbar)**
- Ein kalibriertes Monte-Carlo-Modell: Cashflow-SDE pro Person, Merton-Sprung-Diffusion fürs Portfolio, Schweizer Regeln (Arbeitslosengeld, Tragbarkeit der Hypothek).
- Das gespielte Leben ist ein konkreter Pfad, der Fächer zeigt, was ab dem aktuellen Punkt noch möglich ist.
- Hinweis im Spiel: synthetische Daten, keine Prognose, keine Anlageberatung.
