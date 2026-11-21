(function (root) {
  "use strict";

  const model = typeof module === "object" && module.exports ? require("./model.js") : root.FinancialTwin;
  const DEMO = {
    name: "Alexia", age: 20, education: "Schulabschluss",
    cash: 8000, portfolio: 0, income: 4200, expenses: 3000,
  };
  const CHAPTERS = [
    { title: "Berufseinstieg", prompt: "Was kommt nach der Schule?", offset: 0, scene: "city", choices: [
      { label: "Studieren", type: "study", scene: "study", text: "Hörsaal, Studienkosten und ein späterer Berufseinstieg." },
      { label: "Eine Berufslehre machen", type: "apprentice", scene: "apprentice", text: "In der Werkstatt lernen und schon während der Ausbildung verdienen." },
      { label: "Direkt arbeiten", scene: "work", text: "Das reguläre Einkommen beginnt direkt." },
    ] },
    { title: "Auszeit", prompt: "Möchtest du dir eine Auszeit nehmen?", offset: 6, scene: "gap", choices: [
      { label: "Mit dem Rucksack los", type: "gap", scene: "gap", text: "Eine Reise mit eigenem Budget und mehreren Monaten ohne Gehalt." },
      { label: "Im Beruf bleiben", scene: "work", text: "Einkommen und Alltag laufen weiter." },
    ] },
    { title: "Partnerschaft", prompt: "Möchtest du eine Hochzeit einplanen?", offset: 10, scene: "marriage", choices: [
      { label: "Hochzeit feiern", type: "marriage", scene: "marriage", text: "Plane deinen persönlichen Anteil an den Kosten." },
      { label: "Weiter durchs Leben", scene: "city", text: "Dein bisheriger finanzieller Plan läuft weiter." },
    ] },
    { title: "Familie", prompt: "Sind Kinder Teil dieser Zukunft?", offset: 13, scene: "children", choices: [
      { label: "Mit Kindern planen", type: "children", scene: "children", text: "Lege Kinderkosten fest und entscheide, ob du Elternzeit nimmst." },
      { label: "Zum nächsten Kapitel", scene: "city", text: "Dein aktuelles Monatsbudget läuft weiter." },
    ] },
    { title: "Wohnen", prompt: "Wie möchtest du künftig wohnen?", offset: 16, scene: "home", choices: [
      { label: "Ein Eigenheim kaufen", type: "home", scene: "home", text: "Prüfe Kaufpreis, Eigenkapital und laufende Kosten." },
      { label: "In eine andere Wohnung ziehen", type: "move", scene: "move", text: "Plane die Kosten des Umzugs und die Veränderung deiner Miete." },
      { label: "In der Wohnung bleiben", scene: "city", text: "Deine geplanten Wohnkosten bleiben bestehen." },
    ] },
    { title: "Rente", prompt: "Wie planst du deinen Ruhestand?", offset: 45, scene: "retire", choices: [
      { label: "Rente einplanen", type: "retire", scene: "retire", text: "Wähle den Start und das erwartete Monatseinkommen." },
      { label: "Bisherigen Plan fortsetzen", scene: "city", text: "Dein bisheriges Einkommen gilt bis zum Ende der Projektion." },
    ] },
  ];
  const PRIORITIES = {
    family: "Kinder und Elternzeit beibehalten",
    break: "Auszeit unverändert lassen",
    marriage: "Die Hochzeit so feiern wie geplant",
    home: "Kaufzeitpunkt für das Eigenheim halten",
    education: "Die Ausbildung wie geplant machen",
    retirement: "Zum geplanten Zeitpunkt in Rente gehen",
    buffer: "Den finanziellen Puffer verbessern",
  };

  function chapterAge(chapter, profileAge, earlier) {
    const latest = earlier.at(-1);
    const end = latest?.age + Math.ceil((latest?.event?.duration ?? latest?.event?.leaveMonths ?? 0) / 12);
    const suggested = chapter.title === "Rente" ? Math.max(65, profileAge + 8) : profileAge + chapter.offset;
    return Math.min(model.MAX_AGE - 1, Math.max(suggested, end || profileAge));
  }

  function evaluate(scenario, rates) {
    const run = model.simulate(scenario.profile, scenario.events, scenario.endAge, scenario.risk,
      { assumptions: scenario.assumptions, rates });
    const minimum = run.points.reduce((lowest, point) => Math.min(lowest, point.liquid), Infinity);
    const home = scenario.events.find((event) => event.type === "home" && event.age < scenario.endAge);
    const purchase = home ? run.eventResults[home.id] : null;
    return {
      minimum, realNet: run.points.at(-1).realNet,
      shortfallMonth: run.firstShortfall,
      firstShortfall: run.firstShortfall >= 0 ? -run.points[run.firstShortfall].liquid : 0,
      home: home ? { age: home.age, executed: purchase?.executed ?? false, missing: purchase?.missing ?? 0 } : null,
    };
  }

  function assess(scenario) {
    const rates = model.returnCases(scenario.assumptions.equityReturn);
    const base = evaluate(scenario, rates.central);
    const weak = evaluate(scenario, rates.weak);
    const hasGap = base.shortfallMonth >= 0 || base.home?.executed === false;
    const hasStress = weak.shortfallMonth >= 0 || weak.home?.executed === false;
    return { base, weak, status: hasGap ? "difficult" : hasStress ? "risk" : "feasible" };
  }

  function alternativeChanges(scenario, priority) {
    const changes = [];
    for (const event of scenario.events) {
      switch (event.type) {
        case "study":
        case "apprentice":
          if (priority !== "education" && event.expenses >= 2) {
            changes.push({ title: "Budget während der Ausbildung anpassen", group: "education", event: {
              ...event, expenses: Math.round(event.expenses * 0.8),
            }, detail: "Die Ausbildungsdauer bleibt gleich. Die angesetzten Monatsausgaben sinken um rund 20 %." });
          }
          break;
        case "home":
          if (priority !== "home") {
            for (const years of [1, 2, 3, 5, 8]) {
              if (event.age + years < scenario.endAge) {
                changes.push({ title: "Eigenheim später kaufen", group: "home-date",
                  event: { ...event, age: event.age + years }, detail: "Kauf mit " + (event.age + years) +
                    " statt " + event.age + " Jahren. Das Kaufbudget in heutigen CHF bleibt gleich." });
              }
            }
          }
          for (const factor of [0.9, 0.8, 0.7]) {
            changes.push({ title: "Günstigeres Eigenheim", group: "home-price", event: {
              ...event, price: Math.round(event.price * factor), down: Math.round(event.down * factor),
              cost: Math.round(event.cost * factor),
            }, detail: "Kauf im selben Alter mit " + Math.round((1 - factor) * 100) + " % kleinerem Budget." });
          }
          break;
        case "gap":
          if (priority !== "break" && event.cost >= 2) {
            changes.push({ title: "Reisebudget senken", group: "gap", event: {
              ...event, cost: Math.round(event.cost * 0.7),
            }, detail: "Die Auszeit bleibt gleich lang. Das einmalige Reisebudget sinkt um rund 30 %." });
          }
          break;
        case "marriage":
          if (priority !== "marriage" && event.cost >= 2) {
            changes.push({ title: "Kleiner Hochzeit feiern", group: "marriage", event: {
              ...event, cost: Math.round(event.cost * 0.65),
            }, detail: "Die Hochzeit findet wie geplant statt. Dein einmaliges Budget sinkt um rund 35 %." });
          }
          break;
        case "children":
          if (priority !== "family" && event.leaveMonths > 1) {
            const leaveMonths = Math.ceil(event.leaveMonths / 2);
            changes.push({ title: "Elternzeit kürzer planen", group: "children", event: {
              ...event, leaveMonths,
            }, detail: leaveMonths + " statt " + event.leaveMonths + " Monate Elternzeit. Kinderkosten bleiben gleich." });
          }
          break;
        case "retire":
          if (priority !== "retirement" && event.age + 2 < scenario.endAge) {
            changes.push({ title: "Ruhestand später beginnen", group: "retirement", event: { ...event, age: event.age + 2 },
              detail: "Der Übergang in die Rente verschiebt sich um zwei Jahre. Das Rentenbudget bleibt gleich." });
          }
          break;
      }
    }
    return changes;
  }

  const problems = (facts) => Number(facts.shortfallMonth >= 0) + Number(facts.home?.executed === false);
  const burden = (facts) => Math.max(0, -facts.minimum) + (facts.home?.missing ?? 0);

  function alternatives(scenario, priority, facts = assess(scenario)) {
    const candidates = alternativeChanges(scenario, priority).flatMap((change) => {
      const events = scenario.events.map((item) => item.id === change.event.id ? change.event : item);
      if (model.validateEvent(change.event, events, scenario.profile.age)) return [];
      const assessment = assess({ ...scenario, events });
      const resolved = problems(facts.base) - problems(assessment.base);
      const stressResolved = problems(facts.weak) - problems(assessment.weak);
      const relief = burden(facts.base) - burden(assessment.base);
      const stressRelief = burden(facts.weak) - burden(assessment.weak);
      const cashGain = assessment.base.minimum - facts.base.minimum;
      if (resolved < 0 || stressResolved < 0) return [];
      if (!(resolved > 0 || stressResolved > 0 || relief > 10 || stressRelief > 10 || cashGain > 10)) return [];
      return [{ ...change, assessment, resolved, stressResolved, relief, stressRelief, cashGain }];
    });
    candidates.sort((a, b) => b.resolved - a.resolved || b.stressResolved - a.stressResolved ||
      b.relief - a.relief || b.stressRelief - a.stressRelief || b.cashGain - a.cashGain);
    const seen = new Set();
    return candidates.filter((candidate) => {
      if (seen.has(candidate.group)) return false;
      seen.add(candidate.group);
      return true;
    }).slice(0, 3);
  }

  const fields = {
    study: ["duration", "income", "expenses", "cost", "payChange"],
    apprentice: ["duration", "income", "expenses", "cost", "payChange"],
    gap: ["duration", "expenses", "cost"],
    marriage: ["cost", "monthlyChange"],
    move: ["cost", "monthlyChange"],
    children: ["count", "monthlyCost", "costYears", "leaveMonths", "leaveIncome"],
    home: ["price", "down", "cost", "rate", "term", "housingChange"],
    expense: ["cost"],
    retire: ["income", "expenses"],
  };

  function validScenario(scenario) {
    const within = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;
    const profile = scenario?.profile;
    const assumptions = scenario?.assumptions;
    if (!profile || typeof profile.name !== "string" || profile.name.length > 40 ||
        !Number.isInteger(profile.age) || !within(profile.age, 18, 99) ||
        !Number.isInteger(scenario.endAge) || !within(scenario.endAge, profile.age + 1, 100) ||
        !within(scenario.risk, 0, 100) || !assumptions ||
        !within(assumptions.inflation, -0.05, 0.2) || !within(assumptions.salaryGrowth, -0.1, 0.2) ||
        !within(assumptions.equityReturn, -0.2, 0.25) ||
        !["cash", "portfolio", "income", "expenses"].every((key) => within(profile[key], 0, 100000000)) ||
        !Array.isArray(scenario.events) || scenario.events.length > 24 ||
        !scenario.events.every((event) => event && typeof event === "object")) return false;
    const ids = new Set(scenario.events.map((event) => event.id));
    return ids.size === scenario.events.length && scenario.events.every((event) => {
      if (!event || !Object.hasOwn(fields, event.type) || !Number.isInteger(event.id) ||
          model.validateEvent(event, scenario.events, profile.age)) return false;
      return fields[event.type].every((key) => {
        const limits = { duration: [1, 120], term: [1, 60], rate: [0, 25], count: [1, 20],
          costYears: [0, 80], leaveMonths: [0, 36], leaveIncome: [0, 100] };
        const signed = ["payChange", "monthlyChange", "housingChange"].includes(key);
        return within(event[key], ...(limits[key] ?? [signed ? -100000000 : 0, 100000000]));
      });
    });
  }

  root.TwinStory = { DEMO, CHAPTERS, PRIORITIES, chapterAge, assess, alternatives, validScenario };
  if (typeof module === "object" && module.exports) module.exports = root.TwinStory;
})(globalThis);
