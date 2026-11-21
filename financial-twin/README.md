# Financial Twin

Lokaler spielbarer Prototyp für die UBS-Challenge am LauzHack. Doppelklicke in Windows auf **start.cmd**. Der Starter verwendet vorhandenes Node.js oder die in Visual Studio Code enthaltene Laufzeit und öffnet das Lebensspiel im Standardbrowser. Lass das Startfenster offen. Die Browser-Adresse steht auch im Startfenster und lautet normalerweise **http://127.0.0.1:8765/**.

Mit installiertem Node.js kannst du den lokalen Server auch mit `node serve.cjs` starten. Spiel, Szenariovergleich und Simulation laufen offline. Ein Neuladen startet ein neues Spiel.

## Demo

1. Wähle Aussehen und Ausgangslage oder starte **Demo mit Alexia**. Spiele Berufseinstieg, Auszeit, Partnerschaft, Familie, Wohnen und Rente. Bei Studium und Berufslehre werden Dauer sowie Einkommen während und nach der Ausbildung erfasst.
2. Wähle im Familienkapitel **Elternzeit einplanen**. Dauer und Lohnanteil sind verstellbar. Ehe, Kinderkosten und Umzug werden aus der Perspektive einer Person gerechnet.
3. Im Rückblick nennt der ältere Avatar einen berechneten Engpass, wenn der Basispfad oder der schwache Renditepfad einen aufweist. Setze eine Priorität und vergleiche eine Alternative im Diagramm oder spiele ihre Szene. Festgelegte Prioritäten bleiben bei der Suche erhalten.
4. **Statistiken ansehen** öffnet das Dashboard mit dem gespielten Plan. Ziehe Ereignisse auf dem Zeitstrahl, um die Simulation zu ändern. Im Vergleich **Zwei Lebenswege** werden ursprünglicher und ausgewählter Plan unter denselben Modellannahmen berechnet.

## Lokaler Finanzagent

Der Zwilling-Chat begleitet jedes Kapitel. Qwen formuliert auf Basis des aktuellen Monatsbudgets und des bisherigen Gesprächs einen Tipp und eine persönliche Rückfrage. Du kannst vor dem Abspielen bereits den ausgefüllten Entwurf besprechen. Frag zum Beispiel «Was wäre mit 6 Monaten Elternzeit?» oder «Können wir den Hauskauf mit 40 durchrechnen?». Berechnete Alternativen lassen sich aus dem Chat direkt im Dashboard vergleichen. Das Gespräch bleibt während des Spiels im Browser-Tab.

Installiere dafür Ollama, starte es und lade das Modell mit `ollama pull qwen3:4b`. Der Server sucht auf `127.0.0.1:11434` nach dem Modell. Mit `TWIN_OLLAMA_MODEL` lässt sich der Modellname überschreiben. Das Finanzmodell berechnet die Zahlen und Änderungen für den Planvergleich. Ist das Modell vorübergehend nicht erreichbar, zeigt der Chat berechnete Simulationshinweise an. [Ollama für Windows](https://docs.ollama.com/windows) · [Qwen3-4B](https://ollama.com/library/qwen3:4b)

## Modell

- Die Projektion rechnet in Monatsschritten und nominalen CHF. Das Nettovermögen ist die Summe von Kontostand, Aktien, Anleihen und Immobilienwert abzüglich Resthypothek. Die Ergebnisübersicht zeigt zusätzlich die Kaufkraft in heutigen CHF. [SNB-Glossar zu Inflation und Kaufkraft](https://www.snb.ch/de/services-events/digital-services/glossary)
- Das Erwerbseinkommen folgt ab Start dem eingestellten Gehaltspfad. Für Auszeit, Studium, Berufslehre und Rente gelten die Eingaben des Ereignisses. Kosten sowie Ausbildungs- und Renteneinkommen werden in heutigen CHF eingegeben und auf den Zahlungsmonat hochgerechnet. Kinderkosten gelten ab dem Startalter für die eingegebene Dauer. Elternzeit setzt den regulären Lohn zeitweise auf den eingegebenen Anteil.
- Das Modell investiert höchstens 70 % des laufenden Monatsüberschusses. Es behält drei Monatsausgaben und einen zusätzlichen Betrag für erwartete Liquiditätsengpässe innerhalb der nächsten 36 Monate. Beim Vergleich ohne monatlichen Sparplan bleiben die bestehenden Anlagen investiert.
- Bei einem Hauskauf gleicht das Modell den Kaufpreis durch Eigenkapital und Hypothek aus. Kaufnebenkosten und Hypothekarzinsen reduzieren das Nettovermögen. Tilgung reduziert Kontostand und Verbindlichkeiten um denselben Betrag. Ausgaben, die sich auch nach Verkäufen von Anlagen nicht decken lassen, erscheinen als negativer Kontostand. Unterfinanzierte Hauskäufe werden ausgesetzt.
- Der Aktienpfad verwendet einen wiederholbaren Zwölfjahreszyklus mit schwankenden Monatsrenditen. Der geometrische Durchschnitt über den Zyklus entspricht der eingestellten Rendite. Das Renditeband zeigt alternative Durchschnittsrenditen als Sensitivitätsanalyse. Alle Renditen und das Profil sind illustrative Demowerte.
- Die Challenge-Unterlagen aus dem beigefügten ZIP und das Starter-Kit dienten als fachliche Referenz. Das synthetische Demo-Profil und das Browser-Modell sind eigenständig. Challenge-Konzept und Framework stammen von Stefania Stan. [Investor.gov zu Zinseszinseffekt und Anlagerisiko](https://www.investor.gov/introduction-investing)

## Verifikation

Mit installiertem Node.js lassen sich die Tests im Projektordner mit `node --test model.test.js story.test.js dialog.test.cjs` ausführen. Sie prüfen unter anderem Kontenabgleich, Elternzeit, Finanzierungslücken, den Gesprächskontext und Änderungen aus dem Chat.
