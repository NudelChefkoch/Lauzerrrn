# Financial Twin

Lokaler Prototyp für die UBS-Challenge am LauzHack. Doppelklicke in Windows auf **start.cmd**. Der Starter verwendet vorhandenes Node.js oder die in Visual Studio Code enthaltene Laufzeit und öffnet den Prototyp im Standardbrowser. Lass das Startfenster offen. Die Browser-Adresse steht auch im Startfenster und lautet normalerweise **http://127.0.0.1:8765/**.

Mit installiertem Node.js kannst du den lokalen Server auch mit `node serve.cjs` starten. Die Simulation läuft offline im Browser. Ein Neuladen setzt das fiktive Demo-Profil zurück.

## Demo

1. Öffne **Profil bearbeiten**. Kontostand, Anlagen, Alter, Ausbildung, Einkommen und Ausgaben bestimmen die Ausgangslage.
2. Ziehe den Hauskauf auf dem **Zeitstrahl** von Alter 36 auf 39. Fahre über den Pfeil, um das Nettoeinkommen und die Ausgaben am jeweiligen Zeitpunkt zu sehen. Ein Klick auf den Pfeil öffnet den Editor für ein neues Ereignis. Mit der Tastatur lassen sich fokussierte Ereignisse mit der linken und rechten Pfeiltaste um ein Jahr verschieben.
3. Wechsle im Chart zwischen **Sparplan** und **Lebensereignisse**. Der erste Vergleich variiert die monatlichen Einzahlungen. Der zweite vergleicht den Zeitstrahl mit dem Ausgangsbudget ohne Ereignisse.
4. Verstelle **Gehaltswachstum**, **Inflation** oder **Ø Aktienrendite** im Anlageplan. Füge **Kind(er)** hinzu und prüfe im Zeitstrahl, wie sich die monatlichen Kosten ab dem Startalter verändern.

## Modell

- Die Projektion rechnet in Monatsschritten und nominalen CHF. Das Nettovermögen ist die Summe von Kontostand, Aktien, Anleihen und Immobilienwert abzüglich Resthypothek. Die Ergebnisübersicht zeigt zusätzlich die Kaufkraft in heutigen CHF. [SNB-Glossar zu Inflation und Kaufkraft](https://www.snb.ch/de/services-events/digital-services/glossary)
- Das Erwerbseinkommen folgt ab Start dem eingestellten Gehaltspfad. Während Auszeit, Studium oder Rente gelten die Eingaben des Ereignisses. Studien- und Renteneinkommen, laufende Kosten und einmalige Zahlungen sind inflationsbereinigt einzugeben und werden auf den jeweiligen Zahlungsmonat hochgerechnet. Kinderkosten fallen ab dem Startalter bis zum Ende der Projektion an.
- Das Modell investiert höchstens 70 % des laufenden Monatsüberschusses. Es behält drei Monatsausgaben und einen zusätzlichen Betrag für erwartete Liquiditätsengpässe innerhalb der nächsten 36 Monate. Beim Vergleich ohne monatlichen Sparplan bleiben die bestehenden Anlagen investiert.
- Bei einem Hauskauf gleicht das Modell den Kaufpreis durch Eigenkapital und Hypothek aus. Kaufnebenkosten und Hypothekarzinsen reduzieren das Nettovermögen. Tilgung reduziert Kontostand und Verbindlichkeiten um denselben Betrag. Ausgaben, die sich auch nach Verkäufen von Anlagen nicht decken lassen, erscheinen als negativer Kontostand. Unterfinanzierte Hauskäufe werden ausgesetzt.
- Der Aktienpfad verwendet einen wiederholbaren Zwölfjahreszyklus mit schwankenden Monatsrenditen. Der geometrische Durchschnitt über den Zyklus entspricht der eingestellten Rendite. Das Renditeband zeigt alternative Durchschnittsrenditen als Sensitivitätsanalyse. Alle Renditen und das Profil sind illustrative Demowerte.
- Die Challenge-Unterlagen aus dem beigefügten ZIP und das Starter-Kit dienten als fachliche Referenz. Das synthetische Demo-Profil und das Browser-Modell sind eigenständig. Challenge-Konzept und Framework stammen von Stefania Stan. [Investor.gov zu Zinseszinseffekt und Anlagerisiko](https://www.investor.gov/introduction-investing)

## Verifikation

Mit installiertem Node.js lassen sich die Tests im Projektordner mit `node --test model.test.js` ausführen. Sie prüfen unter anderem Kontenabgleich, Ereignisübergänge, Hypothek, Finanzierungslücken und die Wirkung des Risikoreglers auf das Modell.
