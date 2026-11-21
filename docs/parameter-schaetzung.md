# SDE-Parameterschätzung

Skript: [`sde/estimate_params.py`](../sde/estimate_params.py) → Ergebnis pro Profil in `output/sde_params.csv`.

```bash
venv/bin/python sde/estimate_params.py
```

## Modell

NW(t) = C(t) + I(t) − L(t)

| Komponente | Gleichung | Typ |
|---|---|---|
| Depot I | dI = μ_I·I dt + σ_I·I dW₁ | GBM |
| Cash C | dC = (r(C)·C + m + s_monat(t)) dt + σ_C dW₂ + dJ | ABM + Saison + Sprünge |
| Kredit L | dL = (r_L·L − p) dt | deterministisch |

## Datenbasis

`synthetic-cash-balances.csv`: 1.200 Profile × 24 Monate (2025-01 … 2026-12), Feld `net_transactions_chf` = monatlicher Netto-Cashflow X_t.

Befunde der Explorationsanalyse:

- Drei Kalendermonate weichen systematisch ab: **Dezember +** (13. Monatslohn/Bonus), **Februar −** und **August −** (bei Studierenden Studiengebühren).
- Diese Saisoneffekte sind pro Profil **nicht stabil** zwischen den Jahren (Jahr-zu-Jahr-Korrelation 0,05–0,28) → nicht pro Profil, sondern gepoolt schätzen.
- Kein genereller Trend, kaum Autokorrelation, aber schwere Ränder (Ausreisser) → robuste Schätzer.

## Methoden

| Parameter | Methode | Begründung |
|---|---|---|
| C₀, I₀, L₀ | direkt aus `synthetic-assets.csv` / `synthetic-liabilities.csv` | Stichtag 2025-01-01 |
| r_L | direkt `annual_interest_rate` | |
| Saisonmonate | robuste z-Werte je Profil, Wilcoxon-Test je Kalendermonat über alle Profile, Bonferroni (α/12) **und** \|Median z\| ≥ 0,25 | gepoolte Evidenz statt 2 Beobachtungen pro Profil |
| s_k Feb/Aug (Saisoneffekt) | 10 %-getrimmtes Mittel von (X − m̂)/Referenzeinkommen **je Beschäftigungsgruppe**, × eigenes Einkommen; dazu Zusatzstreuung σ_C·√(k²−1), k = Streuungsfaktor des Monats in der Gruppe (≈ 2) | Pooling, skaliert mit Einkommen; getrimmtes Mittel statt Median, damit der Erwartungswert stimmt |
| Dezember | **Markov-Regime** Bonus/kein Bonus, siehe unten | |
| m (Drift) | **Median** der Nicht-Saisonmonate | robust gegen Ausreisser/Einmalkosten |
| Sprünge | \|X − m̂\| > 3 · (1,4826 · MAD) → Rate λ = Anzahl/Jahre, Höhe = Mittel der Sprünge | robuste Erkennung, trennt Diffusion von Einmalereignissen |
| σ_C | **Standardabweichung der Monate ohne Sprünge** (zweistufig: MAD nur zur Sprungerkennung) | Die MAD allein unterschätzt bei schweren Rändern die Varianz von Summen; erster Backtest hatte nur 68 % statt 90 % Abdeckung |
| Trend b | Theil-Sen-Steigung; nur verwendet, wenn Mann-Kendall p < 0,05 | robuste Steigung |
| μ_C (jährlich) | 12·m + Σ s_k + λ·E[J] | Sprung-Kompensator, sonst wird der Erwartungswert verzerrt |
| σ_C (jährlich) | √12 · σ_C,Monat | Brownsche Skalierung |
| p (Kreditrate) | Annuität über 60 Monate (**Annahme**) | Daten haben p = 0 |
| μ_I, σ_I | **Annahme** 4 % / 10 % p.a. | keine Depotzeitreihe in den Daten |
| Haben-/Überziehungszins | **Annahme** 0,5 % / Kreditzins des Profils, sonst 8 % | |
| ρ (Korrelation) | **Annahme** 0 | |

Alle Annahmen stehen zentral in `ASSUMPTIONS` im Skript und sind illustrativ, keine Prognosen.

## Kriterien

Pro Profil wird jedes Kriterium als PASS/NO gespeichert (`crit_*`-Spalten).

| Kriterium | Test | Bei NO |
|---|---|---|
| Datenmenge ausreichend | 24 Monate, ≥ 12 ohne Saison | Gruppenwerte verwenden |
| Unabhängige Inkremente | \|ρ₁\| < 2/√n | Brownsche Annahme fraglich → OU-Prozess erwägen |
| Kein Trend | Mann-Kendall p ≥ 0,05 | Theil-Sen-Trend in den Drift aufnehmen |
| Residuen normal | Shapiro-Wilk p ≥ 0,05 (ohne Sprünge) | heavy tails → t-Verteilung oder mehr Sprünge |
| Median ≈ Mittelwert | \|x̄ − x̃\| < 0,5·σ̂ | Schiefe → Sprungkomponente wichtig |
| Wenige Sprünge | ≤ 1 Ausreisser > 3σ̂ | Jump-Diffusion statt reiner ABM |
| Backtest | \|μ_C − beobachteter Jahresschnitt\| < 2 Standardfehler | Parameter manuell prüfen |

## Ergebnisse (alle 1.200 Profile)

| Kriterium | PASS-Quote |
|---|---|
| Datenmenge ausreichend | 100,0 % |
| Unabhängige Inkremente | 95,9 % |
| Kein Trend | 94,7 % |
| Residuen normal | 95,8 % |
| Median ≈ Mittelwert | 95,7 % |
| Max. 1 Sprung | 89,7 % |
| Backtest Jahres-Cashflow | 93,2 % |
| **Alle erfüllt** | **71,9 %** |

Die Einzelquoten von ~95 % entsprechen dem, was man bei α = 0,05 auch unter korrektem Modell erwartet. Backtest-z über alle Profile: Mittel 0,23, Std 1,01 → nahezu unverzerrt. Backtest-Fehler betreffen v. a. Angestellte (63 von 79): der Dezember-Bonus ist innerhalb der Gruppe uneinheitlich (manche mit 13. Monatslohn, manche ohne).

### Saisonquoten (Anteil am Monatseinkommen)

| Gruppe | Feb | Aug | Dez |
|---|---|---|---|
| employed | −0,04 | −0,04 | +0,30 |
| self_employed | −0,10 | −0,09 | +0,24 |
| part_time | −0,07 | −0,09 | +0,01 |
| retired | −0,08 | −0,08 | +0,01 |
| student | −1,11 | −0,16 | −0,06 |
| unemployed | −0,37 | −0,24 | −0,02 |

### Beispiel Alexia (P00001, Studentin)

| Parameter | Wert |
|---|---|
| NW₀ | CHF 8.000 |
| m (Median) / Mittelwert | −700 / −907 CHF/Monat |
| σ_C (MAD) / Std | 286 / 495 CHF/Monat |
| Sprünge | 3 in 24 Monaten, Ø −1.137 CHF |
| μ_C jährlich | −10.005 CHF |

| Kriterium | Status |
|---|---|
| Datenmenge ausreichend | PASS |
| Unabhängige Inkremente | PASS |
| Kein Trend | PASS |
| Residuen normal | NO |
| Median ≈ Mittelwert | NO |
| Max. 1 Sprung | NO |
| Backtest | PASS |

→ Für Alexia ist die Sprungkomponente nötig. Mit ihr stimmt der Backtest (z = 0,49).

## Dezember als Markov-Regime

Skript: [`sde/december_regime.py`](../sde/december_regime.py)

Der Dezember ist zweigipflig: entweder ≈ normaler Monat oder ein Bonus von 0,1–1,3 Monatslöhnen. Ein fester Saisoneffekt bildet das schlecht ab. Deshalb:

- **Klassifikation:** Dezember mit z = (X_Dez − m̂)/σ̂ > 3 → Zustand B = 1 (Bonus), sonst B = 0.
- **Übergangsmatrix** je Beschäftigungsgruppe aus den Übergängen Dez 2025 → Dez 2026, mit Laplace-Glättung (Beta(1,1)-Prior):
  P = [[1 − p₀₁, p₀₁], [p₁₀, 1 − p₁₀]]
- **Bonushöhe:** Anteil am Monatseinkommen ~ N(Mittel, Std) der Bonus-Dezember der Gruppe (Fallback gepoolt bei < 5 Fällen), abgeschnitten bei 0.
- **Erster Dezember** der Simulation: B aus der stationären Verteilung π = p₀₁/(p₀₁ + p₁₀).
- **Persistenz-Test:** Fisher-Test, ob B₂₀₂₆ von B₂₀₂₅ abhängt.

| Gruppe | P(N→B) | P(B→B) | π(Bonus) | Bonus / Einkommen | Persistenz p |
|---|---|---|---|---|---|
| employed | 0,53 | 0,58 | 0,56 | 0,60 ± 0,23 | 0,25 |
| self_employed | 0,26 | 0,52 | 0,36 | 0,93 ± 0,19 | **0,03** |
| part_time, retired, student, unemployed | ≤ 0,05 | (Prior) | ≤ 0,09 | gepoolt | – |

Lesart: Bei Angestellten ist der Bonus **ohne Gedächtnis** (P(N→B) ≈ P(B→B)), die Markov-Kette fällt dort auf einen Münzwurf zurück. Nur bei Selbständigen gibt es signifikante Persistenz. Für die übrigen Gruppen ist ein Bonus selten. Ihre P(B→B) beruht nur auf dem Prior und spielt praktisch keine Rolle.

## Simulation

Skript: [`sde/simulate.py`](../sde/simulate.py), monatlich, 10 Jahre ab 2025-01-01.

- Depot: exakter GBM-Schritt.
- Kredit: Annuität, Rate wird vom Cash abgezogen.
- Cash: Euler-Schritt mit m, σ_C, Feb/Aug-Saison, Sprüngen (Bernoulli mit λ/12) und Dezember-Bonus aus der Markov-Kette. Zins abhängig vom Vorzeichen.

**Backtest 2025–26** (Simulation vs. beobachtetes Ledger, ohne Zinsen/Kreditraten, die das Ledger nicht enthält):

| Kennzahl | Soll | Ist |
|---|---|---|
| Beobachtung im 90 %-Band | 90 % | 88 % |
| Beobachtung im 50 %-Band | 50 % | 47 % |
| z-Mittel / z-Std | 0 / 1 | −0,10 / 1,04 |

Achtung: in-sample (Parameter aus denselben 24 Monaten). Ein echter Out-of-Sample-Test bräuchte mehr Daten.

## Lebenszyklus

Ohne Lebenszyklus bleibt die Drift 10 Jahre konstant: Studierende studieren ewig, Angestellte gehen nie in Rente. Deshalb hat jeder Pfad einen Zustand (Studium / Arbeit / arbeitslos / Rente), der sich monatlich ändern kann.

Einkommen und Ausgaben werden getrennt: Ausgaben = Referenzeinkommen − m (so bleibt der geschätzte Cashflow m am Start exakt erhalten).

| Übergang | Regel | Default | Quelle |
|---|---|---|---|
| Studium → Arbeit | nach Rest-Studienzeit; Lohn = Einstiegslohn, Ausgaben ≥ Lohn·(1 − Sparquote) | 2 J., 8'163 CHF, 54,7 % | **Daten** (S001, Median Angestellte ≤ 27 J., Median m/Lohn) |
| Arbeit → arbeitslos | Jobverlust-Rate p.a.; Taggeld = Anteil letzter Lohn, befristet, danach 0 | 2 %, 70 %, 18 Mt. | Annahme |
| arbeitslos → Arbeit | Wiedereinstieg-Rate pro Monat; letzter Lohn bzw. Wiedereinstiegslohn | 12 %/Mt., 7'738 CHF | Annahme / **Daten** (Median Angestellte) |
| alle → Rente | ab Rentenalter; Rente = Anteil letzter Lohn | 65 J., 50 % | Annahme / **Daten** (Median Rente / Median Lohn 55–64) |
| Wachstum | Löhne mit Lohnwachstum, Ausgaben und Renten mit Inflation | 1 %, 1 % | Annahme |
| Sparen | Anteil des Cash über Puffer (x Monatsausgaben) geht monatlich ins Depot | 0 %, 3 Mt. | Annahme |

Gruppenabhängige Teile (Saison Feb/Aug, Dezember-Regime) folgen dem **aktuellen** Zustand: Eine Studentin, die zu arbeiten beginnt, bekommt ab dann die Saison und Bonus-Kette der Angestellten. In Rente oder Arbeitslosigkeit wird kein Bonus ausgezahlt.

Alle Defaults stehen in `SimConfig` ([`sde/simulate.py`](../sde/simulate.py)); `data_defaults()` leitet die mit „Daten“ markierten Werte beim Start neu ab.

Achtung: Die synthetischen Daten haben eine sehr hohe Sparquote (Median 55 % bei Angestellten). Mit Lebenszyklus wachsen Net Worths deshalb schnell, z. B. Alexia von 8k auf ~450k in 10 Jahren. Das ist eine Eigenschaft der Daten, nicht des Modells.

## Szenarien

Dateien: [`sde/interventions.py`](../sde/interventions.py) (Bausteine), [`sde/scenarios.py`](../sde/scenarios.py) (Bibliothek)

Alle **120 Szenarien** aus `scenario-catalog.csv` sind als Paar **Baseline → Intervention** abgebildet. Der Katalog liefert nur Texte. Die Zahlen sind deshalb einstellbare, illustrative Annahmen. Einzige Ausnahme ist die Studiengebühr in S001/S010, die aus `scenario-assumptions.csv` kommt. Profilabhängige Defaults (Miete, Einkommen, Kaufpreis ≈ 5 Jahreseinkommen) werden beim Profilwechsel neu gesetzt.

### Bausteine

| Baustein | Wirkung |
|---|---|
| `Income(start, end, factor/set/add)` | Einkommen im Zeitfenster ersetzen, skalieren oder ergänzen |
| `Expense(start, end, factor/add, growth)` | Ausgaben im Fenster; Zuschläge real (mit Inflation indexiert) |
| `OneOff(month, amount, prob)` | Einmalbetrag, optional nur mit Wahrscheinlichkeit (Exit, Equity) |
| `Loan(month, principal, rate, term, disburse, rate_step)` | Annuitätenkredit, optional mit Zinsstufe |
| `Property(month, price, down, fees, rate, …)` | Eigenkapital + Gebühren aus Cash, Hypothek, Unterhalt, eingesparte Miete; Wert H als GBM (μ_H 1,5 %, σ_H 5 %) |
| `DepotShock`, `PropertyShock` | einmalige Wertänderung |
| `DepotDrift`, `Inflation`, `JobRisk` | Rendite, Inflation oder Jobverlust-Risiko für ein Zeitfenster verändern |
| `Invest(start, end, amount)` | Sparplan Cash → Depot (nur aus positivem Cash) |
| Overrides | `SimConfig` (z. B. Rentenalter, Rendite) und Profilwerte (z. B. Kreditzins, σ_C) |

Net Worth mit Immobilie: NW = C + I + H − L.

### Vergleich

- **Baseline:** Ohne eigene Baseline im Katalog ist sie der Status quo, also die Simulation mit den aktuellen Einstellungen. Wo der Katalog eine konkrete Alternative nennt, wird sie eigens gebaut, z. B. S011 (Baseline = Master), S034/S035/S038–S040 (Baseline = Kauf mit Standardannahmen), S063 (Baseline = nur Aktien).
- **Gleiche Zufallszahlen:** Baseline und Szenario laufen mit demselben Seed. Jede Zufallsquelle (Depot, Cash, Sprünge, Lebenszyklus, Dezember, Saison, Immobilie, Ereignisse) hat einen eigenen RNG-Stream. Die Differenz ΔNW = NW_Szenario − NW_Baseline zeigt dadurch pfadweise den Effekt der Entscheidung, nicht unterschiedliches Rauschen.
- **Kennzahlen:**
  - Median/P5/P95 von NW für beide Läufe.
  - Δ Median, Δ Mittel und P(Szenario besser). Bei Wahrscheinlichkeitsereignissen wie Exit oder Equity ist der Median oft 0, dort zählt das Mittel.
  - P(Cash jemals < 0) für beide, als Hinweis auf Liquiditätsengpässe (z. B. Hauskauf ohne genug Eigenkapital).
  - Zielerreichung für beide.

### Geprüft

- Alle 120 Szenarien laufen für Studentin, Rentner, Angestellte, Profil mit Kredit und Arbeitslose ohne Fehler, in rund 0,1–0,2 s pro Vergleich.
- **Hauskauf (S033, Samir):** Das Net Worth sinkt im Kaufmonat exakt um die Gebühren (−17'100 bei 570k), die Hypothek beträgt 80 %.
- **Exit (S120):** Die Erfolgsquote in der Simulation (24 %) entspricht der eingestellten Wahrscheinlichkeit (25 %).

### Grobe Näherungen

S029 und S105 (FX als mehr Streuung), S051 (Notgroschen als Trade-off Reserve vs. Anlage), S055 (gesperrtes Konto als Depot), S068 (Rebalancing als geringere Volatilität), S079 (Kreditlimit als Strafzins), S093 (3a als Depot, Steuerersparnis als Einkommen), S097 (dynamische Entnahme als Ausgabenkürzung), S098 (verlängert nur den Horizont), S119 (Kredit fliesst ins Geschäft ohne privaten Gegenwert). Szenarien zur Rente (S095–S097, S100) wirken ab dem Rentenbeginn, bei Pensionierten also sofort. Kapitalbezug S099 nur vor der Pensionierung.

## GUI

```bash
venv/bin/python sde/gui.py
```

[`sde/gui.py`](../sde/gui.py) (PySide6):

- **Szenario-Panel:** Kategorie, Szenario (120), Baseline/Intervention aus dem Katalog, Startmonat und die Parameter des Szenarios. Mit Szenario zeigt die rechte Seite Baseline vs. Szenario, die Verteilung von ΔNW, Komponenten inkl. Immobilie und eine Warnung bei Liquiditätsengpass.
- **Links:** Profilauswahl (1'200 Profile, durchsuchbar) und alle Parameter.
  - Profilwerte (C₀, I₀, L₀, Einkommen, m, σ_C, Sprünge, Kreditzins, Alter): aus den Daten geschätzt, überschreibbar.
  - Annahmen: Markt, Lebenszyklus, Sparen, Modellschalter (Dezember-Regime, Saison, Sprünge), Simulation (Pfade, Horizont, Seed, real/nominal).
  - Zwei Reset-Knöpfe: Profilwerte bzw. Annahmen zurück auf die Defaults.
- **Rechts:**
  - Kennzahlen: P5/Median/P95, P(NW < 0), P(Cash jemals < 0).
  - Fan-Chart mit Lebenszyklus-Ereignissen, Komponenten (Cash/Depot/Schulden), Anteil der Lebenszyklus-Zustände.
  - Tabelle der Ziele aus `synthetic-goals.csv` mit P(erreicht).
- Jede Änderung simuliert nach 250 ms automatisch neu (~0,1 s bei 2'000 Pfaden).

## Grafiken

Skript: [`sde/plots.py`](../sde/plots.py) → `output/plots/`

- `fan_<Profil>.png`: Backtest Cash 2025–26 + Fan-Chart Net Worth über 10 Jahre
- `december_regime.png`: Klassifikation, Übergangswahrscheinlichkeiten, simulierte Boni
- `overview.png`: Kalibrierung des Backtests + Net Worth je Gruppe

## Grenzen

- 24 Monate sind wenig: σ̂ und Saisoneffekte sind unsicher. Gruppen-Pooling reduziert das.
- Depotrendite, Zinsen und Kredittilgung sind nicht aus den Daten schätzbar.
- Daten sind synthetisch. Die Befunde beschreiben den Generator, nicht echte Haushalte.
- Der Lebenszyklus ist regelbasiert. Berufseinstieg und Rente kommen deterministisch zu einem festen Zeitpunkt, nur Jobverlust und Wiedereinstieg sind zufällig. Die Bänder unterschätzen daher die Unsicherheit im Lebensverlauf.
- Die Zahlen der Szenarien sind illustrative Annahmen (der Katalog liefert keine), einstellbar in der GUI. Steuern sind nur in S093/S107 grob abgebildet.
