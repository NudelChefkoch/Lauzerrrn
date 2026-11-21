"use strict";

const model = require("./model.js");
const story = require("./story.js");
const agent = require("./agent.cjs");

const STAGES = {
  Berufseinstieg: { topic: "budget", subject: "Ausbildung und Berufseinstieg",
    tip: "Prüfe, wie lange deine Rücklagen mit dem Einkommen während der Ausbildung reichen.",
    question: "Möchtest du einen finanziellen Puffer für deine Ausbildung einplanen?" },
  Auszeit: { topic: "budget", subject: "Dauer und Budget der Auszeit ohne Erwerbseinkommen",
    tip: "Plane die laufenden Kosten deiner Auszeit zusätzlich zum Reisebudget ein.",
    question: "Möchtest du die Dauer der Auszeit oder das Reisebudget zuerst festlegen?" },
  Partnerschaft: { topic: "budget", subject: "Hochzeit und persönlicher Anteil an den Haushaltskosten",
    tip: "Trenne deinen Anteil an den Hochzeitskosten von deinen künftigen monatlichen Ausgaben.",
    question: "Welche laufenden Kosten verändern sich für dich nach der Hochzeit?" },
  Familie: { topic: "budget", subject: "Kinderkosten, Elternzeit und vorübergehend reduzierter Lohn",
    tip: "Teste die Kinderkosten und den tieferen Lohn während der Elternzeit gemeinsam.",
    question: "Wie lange möchtest du Elternzeit nehmen und welchen Lohn erwartest du dabei?" },
  Wohnen: { topic: "housing", subject: "Kaufzeitpunkt, Wohnkosten und Eigenkapital",
    tip: "Prüfe neben dem Eigenkapital auch die laufenden Wohnkosten nach dem Kauf.",
    question: "Was soll beim Eigenheim möglichst gleich bleiben, das Budget oder der Kaufzeitpunkt?" },
  Rente: { topic: "budget", subject: "Rentenbeginn und monatliche Ausgaben nach der Pensionierung",
    tip: "Vergleiche deine erwartete Nettorente mit den geplanten laufenden Ausgaben.",
    question: "Welche Ausgaben erwartest du nach deinem Rentenbeginn?" },
  Rückblick: { topic: "risk", subject: "Finanzielle Tragbarkeit, persönlicher Puffer und geschützte Ziele",
    tip: "Schaue zuerst auf die Finanzierungslücken und entscheide, welche Lebensentscheidung erhalten bleiben soll.",
    question: "Was möchtest du bei möglichen Änderungen auf jeden Fall beibehalten?" },
};
const PRIORITIES = ["", ...Object.keys(story.PRIORITIES)];
const COMPARISON_FOCUS = {
  home: { subject: "Vergleich des Kaufzeitpunkts bei gleichem Kaufbudget",
    match: /kauf|eigenheim|eigenkapital|hypothek|wohn/iu,
    tip: "Vergleiche das Eigenkapital und den Puffer am gewünschten Kaufzeitpunkt.",
    question: "Soll das Kaufbudget bei deinem neuen Kaufzeitpunkt gleich bleiben?" },
  children: { subject: "Vergleich von Dauer und Lohnanteil der Elternzeit",
    match: /elternzeit|lohn|pensum|kinder/iu,
    tip: "Vergleiche den Monat mit reduziertem Lohn mit dem Budget nach der Elternzeit.",
    question: "Welchen Lohnanteil möchtest du bei dieser Elternzeit einplanen?" },
  gap: { subject: "Vergleich der Dauer der Auszeit und des nötigen Puffers",
    match: /auszeit|reise|unterbruch|erwerbspause/iu,
    tip: "Vergleiche die laufenden Kosten bei beiden Auszeitdauern.",
    question: "Welche Reisekosten sollen bei der geänderten Auszeit gleich bleiben?" },
};
const TOPIC_FOCUS = {
  reserve: { subject: "Finanzieller Puffer und absehbare Ausgaben",
    tip: "Plane deinen Puffer anhand deiner laufenden Ausgaben und fälligen Einmalzahlungen.",
    question: "Wie viele Monate deiner laufenden Ausgaben möchtest du als Puffer bereithalten?" },
  saving: { subject: "Monatliche Sparrate, Anlagedauer und verfügbare Liquidität",
    tip: "Vergleiche die monatlichen Einzahlungen mit deinem verfügbaren Überschuss.",
    question: "Wann könntest du das Geld aus deinem Sparplan wieder benötigen?" },
  alternatives: { subject: "Alternative Lebensentscheidungen und feste Prioritäten",
    tip: "Teste jeweils eine Änderung und vergleiche ihre Folgen für den Puffer.",
    question: "Was möchtest du bei der nächsten Variante unbedingt beibehalten?" },
};
const TIP = /^(Plane|Prüfe|Behalte|Setze|Rechne|Vergleiche|Berücksichtige|Kläre|Trenne|Teste|Halte) [A-Za-zÄÖÜäöüßéàè ,\-]{9,100}\.$/u;
const QUESTION = /^(Wie|Was|Welche|Welches|Ist|Willst|Möchtest|Soll|Wäre|Worauf|Hast|Würdest|Gibt|Wann|Kannst|Magst) [A-Za-zÄÖÜäöüßéàè ,\-]{7,100}\?$/u;
const format = {
  type: "object", additionalProperties: false, required: ["tip", "question"],
  properties: {
    tip: { type: "string", pattern: TIP.source },
    question: { type: "string", pattern: QUESTION.source },
  },
};

const amount = new Intl.NumberFormat("de-CH", { maximumFractionDigits: 0 });
const money = (value) => (value < -0.5 ? "−" : "") + "CHF " + amount.format(Math.abs(value));
const delta = (value) => (value > 0.5 ? "+" : "") + money(value);

function prepare(payload) {
  const { scenario, stage, age, draft, history, priority, preference = "", opening } = payload ?? {};
  if (!scenario || !story.validScenario(scenario) || !Object.hasOwn(STAGES, stage) ||
      !Number.isInteger(age) || age < scenario.profile.age || age > 100 ||
      !PRIORITIES.includes(priority) || !PRIORITIES.includes(preference) ||
      typeof opening !== "boolean" || !Array.isArray(history) || history.length > 10 ||
      !history.every((turn) => turn && ["user", "assistant"].includes(turn.role) &&
        (turn.stage === undefined || Object.hasOwn(STAGES, turn.stage)) &&
        typeof turn.content === "string" && turn.content.length <= 680) ||
      (!opening && (history.at(-1)?.role !== "user" || !history.at(-1).content.trim()))) return null;

  let plan = scenario;
  if (draft && typeof draft === "object") {
    const candidate = { ...scenario, endAge: Math.min(100, Math.max(scenario.endAge, draft.age + 1)),
      events: [...scenario.events.filter((event) => event.id !== draft.id), draft] };
    if (story.validScenario(candidate)) plan = candidate;
  }
  return { plan, draft: plan === scenario ? null : draft, stage, age, history, priority, preference, opening };
}

function budgetAt(plan, run, age) {
  const month = Math.min(run.points.length - 1, (age - plan.profile.age) * 12 + 1);
  const point = run.points[month];
  return { point, age: Math.min(age, plan.endAge - 1), previous: run.points[month - 1] };
}

function explicitChange(context, topic) {
  if (context.opening) return null;
  const question = context.history.at(-1).content;
  const nearby = context.history.slice(-3).map((turn) => turn.content).join(" ");
  const targetAge = question.match(/(?:\bmit |\bab |im alter(?: von)? |\balter |\bauf\s+)(\d{2})(?!\d)/iu);
  const months = question.match(/\b(\d{1,3})\s*Monat(?:e|en)?\b/iu);
  const percent = question.match(/\b(\d{1,3})\s*(?:%|Prozent)/iu);
  const house = targetAge && (topic === "housing" || context.stage === "Wohnen" ||
    /hauskauf|eigenheim|haus kaufen/iu.test(nearby));
  const explicitGap = /auszeit|gap year/iu.test(question);
  const explicitLeave = /elternzeit/iu.test(question);
  const leave = (months || percent) && (explicitLeave || !explicitGap && /elternzeit/iu.test(nearby));
  const gap = months && (explicitGap || !explicitLeave &&
    (context.stage === "Auszeit" || /auszeit|gap year/iu.test(nearby)));
  const type = house ? "home" : leave ? "children" : gap ? "gap" : null;
  const original = context.draft?.type === type ? context.draft :
    context.plan.events.find((event) => event.type === type);
  if (!original) return null;

  const event = { ...original };
  if (type === "home") event.age = Number(targetAge[1]);
  if (type === "children") {
    if (months) event.leaveMonths = Number(months[1]);
    if (percent) event.leaveIncome = Number(percent[1]);
    if (event.leaveIncome === original.leaveIncome && event.leaveMonths === original.leaveMonths) return null;
  }
  if (type === "gap") event.duration = Number(months[1]);
  if ((type === "home" && event.age === original.age) ||
      (type === "gap" && event.duration === original.duration)) return null;
  if (!story.validScenario({ ...context.plan, events: context.plan.events.map((item) =>
    item.id === event.id ? event : item) }) || event.age >= context.plan.endAge) return { invalid: true };
  return { event, title: type === "home" ? "Hauskauf mit " + event.age : type === "children" ?
    event.leaveMonths + " Monate Elternzeit bei " + event.leaveIncome + " % Lohn" : event.duration + " Monate Auszeit" };
}

function comparison(plan, alternative, original = story.assess(plan)) {
  const modified = { ...plan, events: plan.events.map((event) =>
    event.id === alternative.event.id ? alternative.event : event) };
  const updated = alternative.assessment ?? story.assess(modified);
  const minimum = Math.abs(updated.base.minimum - original.base.minimum) < 0.5
    ? "Tiefster Kontostand in beiden Varianten · " + money(updated.base.minimum) + "."
    : "Tiefster Kontostand im Basispfad " + money(original.base.minimum) + " → " + money(updated.base.minimum) + ".";
  const lines = [agent.planSummary(updated, modified), minimum,
    "Nettovermögen in heutiger Kaufkraft mit " + plan.endAge + " · " + delta(updated.base.realNet - original.base.realNet) + " Unterschied."];
  return { title: alternative.title, lines, compare: { original: plan, modified } };
}

function calculate(context, topic, priority, run, change) {
  const { plan, draft } = context;
  if (change?.event) return comparison(plan, change);
  if (change?.invalid) return { title: "Zeitpunkt oder Dauer ausserhalb deines Plans", lines: [
    "Prüfe im Kapitel den zulässigen Zeitraum und mögliche Überschneidungen.",
  ] };

  if (["risk", "housing", "alternatives"].includes(topic)) {
    const facts = story.assess(plan);
    if (topic === "alternatives") {
      const choice = story.alternatives(plan, priority || "buffer", facts)[0];
      if (choice) return comparison(plan, choice, facts);
    }
    if (topic !== "housing" || facts.base.home) return {
      title: topic === "housing" ? "Dein geplanter Hauskauf" : "Planprüfung",
      lines: [agent.planSummary(facts, plan), "Tiefster Kontostand im Basispfad · " + money(facts.base.minimum) + "."],
    };
  }
  if (topic === "saving") {
    const cashOnly = model.simulate(plan.profile, plan.events, plan.endAge, plan.risk,
      { assumptions: plan.assumptions, investMonthly: false });
    const difference = run.points.at(-1).realNet - cashOnly.points.at(-1).realNet;
    return { title: "Monatlichen Sparplan vergleichen", lines: [
      "Bis " + plan.endAge + " ergibt der Sparplan im Basispfad " + delta(difference) +
      " Nettovermögen in heutiger Kaufkraft gegenüber demselben Plan ohne monatliche Einzahlungen.",
    ] };
  }
  const { point, age, previous } = budgetAt(plan, run, context.age);
  if (topic === "reserve") return { title: "Dein Liquiditätspuffer", lines: [
    "Kontostand zu Monatsbeginn · " + money(previous.liquid) + ".",
    "Liquiditätsziel des Sparplans mit " + age + " · " + money(point.reserve) + ".",
  ] };
  return { title: (draft ? "Vorschau auf deine Eingaben" : "Dein Monatsbudget") + " mit " + age, lines: [
    "Nettoeinkommen " + money(point.income) + " · laufende Ausgaben " + money(point.expenses) + ".",
    "Überschuss vor Einmalzahlungen " + delta(point.income - point.expenses) + ".",
    ...(point.oneOff > 0 ? ["Einmalige Zahlungen in diesem Monat · " + money(point.oneOff) + "."] : []),
  ] };
}

function requestedTopic(message, defaultTopic) {
  if (/sparplan|investier|sparrate/iu.test(message)) return "saving";
  if (/alternativ|verbessern|optimier|stellschraube|empfiehl|empfehl/iu.test(message)) return "alternatives";
  if (/hauskauf|eigenheim|haus kaufen|hypothek/iu.test(message)) return "housing";
  if (/puffer|reserve/iu.test(message)) return "reserve";
  if (/finanzierungslücke|engpass|riskant|tragbar|fehlt .*geld/iu.test(message)) return "risk";
  return defaultTopic;
}

function expressedPriority(message) {
  for (const sentence of message.split(/[.!?;\n]/u)) {
    if (!/bleib|beibehalten|unverändert|wichtig|priorität|unbedingt|auf keinen fall/iu.test(sentence)) continue;
    if (/elternzeit|familienzeit|kinder/iu.test(sentence)) return "family";
    if (/auszeit|gap year/iu.test(sentence)) return "break";
    if (/hochzeit/iu.test(sentence)) return "marriage";
    if (/kaufzeitpunkt|hauskauf|eigenheim/iu.test(sentence)) return "home";
    if (/ausbildung|studium|lehre/iu.test(sentence)) return "education";
    if (/rente|ruhestand/iu.test(sentence)) return "retirement";
    if (/puffer|reserve/iu.test(sentence)) return "buffer";
  }
  return "";
}

async function reply(payload, { signal } = {}) {
  const context = prepare(payload);
  if (!context) return { status: 400, error: "Die Chat-Anfrage enthält ungültige Eingaben." };
  const { plan, stage, age, draft, history, opening } = context;
  const stageInfo = STAGES[stage];
  const latest = opening ? "" : history.at(-1).content;
  const priority = context.priority || expressedPriority(latest) || context.preference;
  const topic = requestedTopic(latest, stageInfo.topic);
  const change = explicitChange(context, topic);
  const focus = COMPARISON_FOCUS[change?.event?.type] ?? TOPIC_FOCUS[topic] ?? stageInfo;
  const run = model.simulate(plan.profile, plan.events, plan.endAge, plan.risk, { assumptions: plan.assumptions });
  const insight = calculate(context, topic, priority, run, change);
  const { point } = budgetAt(plan, run, age);
  const surplus = point.income - point.expenses;
  const budgetNote = surplus < 0 ? "Das laufende Monatsbudget ist im Minus." :
    surplus > 0 ? "Im laufenden Monatsbudget bleibt ein Überschuss." : "Das laufende Monatsbudget ist ausgeglichen.";
  const relevantHistory = history.filter((turn) => turn.role === "user" || !turn.stage || turn.stage === stage);
  const promptHistory = change?.event ? relevantHistory.slice(-1) : relevantHistory.slice(opening ? -2 : -3);
  const connection = await agent.status();
  let generated;
  if (connection.available && !signal?.aborted) {
    try {
      generated = await agent.requestChat([{
        role: "system",
        content: "Du bist der Finanz-Zwilling in einem Spiel. Sprich Deutsch mit du. Schreibe einen kurzen Budgettipp im Imperativ und eine neue konkrete Frage. Gehe auf das aktuelle Thema und die jüngste Nachricht ein. Wiederhole keine Frage. Verwende kurze Hauptsätze ohne Geldbeträge, Währungen oder Produkte.",
      }, {
        role: "user",
        content: [
          "Kapitel " + stage + ". Aktuelles Thema: " + focus.subject + ".",
          budgetNote + (point.liquid < 0 ? " Es besteht eine Finanzierungslücke." : "") +
            (point.oneOff ? " In diesem Monat sind Einmalzahlungen geplant." : ""),
          draft ? "Aktueller Entwurf " + draft.type + "." : "",
          priority ? "Priorität: " + story.PRIORITIES[priority] + "." : "",
          promptHistory.map(({ role, content }) =>
            (role === "user" ? "Spieler: " : "Zwilling: ") + content.slice(0, 280)).join("\n"),
          opening ? "Eröffne das Kapitel mit Tipp und Frage. /no_think" :
            "Antworte auf die letzte Nachricht mit Tipp und Frage. /no_think",
        ].filter(Boolean).join("\n"),
      }], format, { maxTokens: 95, temperature: 0.55, signal });
    } catch {}
  }
  const valid = generated && typeof generated.tip === "string" && TIP.test(generated.tip) &&
    typeof generated.question === "string" && QUESTION.test(generated.question) &&
    (!focus.match || focus.match.test(generated.tip) && focus.match.test(generated.question)) &&
    !history.some((turn) => turn.role === "assistant" && turn.content.includes(generated.question)) &&
    !/aufgabe|prompt|anweisung|auf deutsch|als digitaler zwilling|\bCHF\b|franken|\beuro\b|\bdollar\b/iu
      .test(generated.tip + " " + generated.question);
  return { status: 200, tip: valid ? generated.tip : focus.tip,
    question: valid ? generated.question : focus.question, priority,
    insight, source: valid ? connection.model : "simulation" };
}

module.exports = { reply, prepare, explicitChange };
