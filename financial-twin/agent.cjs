"use strict";

const story = require("./story.js");

const modelName = process.env.TWIN_OLLAMA_MODEL || "qwen3:4b";
const ollama = "http://127.0.0.1:11434";
const priorities = Object.keys(story.PRIORITIES);
const money = new Intl.NumberFormat("de-CH", { style: "currency", currency: "CHF", maximumFractionDigits: 0 });

async function status() {
  try {
    const response = await fetch(ollama + "/api/tags", { signal: AbortSignal.timeout(1700) });
    const { models } = await response.json();
    return { available: Boolean(models?.some((item) => item.name === modelName || item.model === modelName)), model: modelName };
  } catch {
    return { available: false, model: modelName };
  }
}

async function requestChat(messages, format, { maxTokens = 32, temperature = 0.1, signal } = {}) {
  const timeout = AbortSignal.timeout(45000);
  const response = await fetch(ollama + "/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    body: JSON.stringify({
      model: modelName, think: false, stream: false, keep_alive: "15m",
      messages, format, options: { temperature, num_predict: maxTokens, num_ctx: 4096 },
    }),
  });
  if (!response.ok) throw new Error("Ollama hat keine Antwort geliefert.");
  return JSON.parse((await response.json()).message.content);
}

async function choose(question, choices, priority, facts) {
  const reply = await requestChat([{
        role: "system",
        content: "Wähle ausschliesslich den Schlüssel der passenden Aktion im vorgegebenen JSON. Bevorzuge eine konkrete Alternative, wenn nach einer Verbesserung gefragt wird.",
      }, {
        role: "user", content: JSON.stringify({
          frage: question,
          prioritaet: story.PRIORITIES[priority] ?? null,
          planstatus: facts.status,
          aktionen: Object.fromEntries(choices),
        }) + " /no_think",
      }], {
        type: "object", properties: { choice: { type: "string", enum: [...choices.keys()] } },
        required: ["choice"], additionalProperties: false,
  });
  const decision = reply.choice;
  if (!choices.has(decision)) throw new Error("Unbekannte Aktion.");
  return decision;
}

function planSummary(facts, plan) {
  const chosen = facts.status === "risk" ? facts.weak : facts.base;
  const lines = [];
  if (chosen.home?.executed === false) {
    lines.push("Für den geplanten Hauskauf mit " + chosen.home.age + " fehlen mir " + money.format(chosen.home.missing) + ".");
  }
  if (chosen.shortfallMonth >= 0) {
    const month = chosen.shortfallMonth - 1;
    const age = plan.profile.age + Math.floor(month / 12);
    lines.push("Im " + (month % 12 + 1) + ". Monat mit " + age +
      " Jahren fehlen mir erstmals " + money.format(chosen.firstShortfall) + " für laufende Zahlungen.");
  }
  if (!lines.length) return "Ich kann die erfassten Ausgaben auch im getesteten schwachen Renditepfad decken.";
  return (facts.status === "risk" ? "Bei schwacher Rendite wird es für mich eng. " : "") + lines.join(" ");
}

function alternativeSummary(item, original) {
  const outcome = [];
  if (item.assessment.base.home?.executed && original.base.home?.executed === false) {
    outcome.push("Damit kann ich das Eigenheim im Basispfad finanzieren.");
  }
  if (item.assessment.weak.home?.executed && original.weak.home?.executed === false) {
    outcome.push("Der Kauf klappt auch im schwachen Renditepfad.");
  }
  if (item.assessment.base.shortfallMonth < 0 && original.base.shortfallMonth >= 0) {
    outcome.push("Die Zahlungslücke im Basispfad entfällt.");
  }
  if (item.assessment.base.home?.executed === false) {
    outcome.push("Für das Eigenheim fehlen im Basispfad weiterhin " + money.format(item.assessment.base.home.missing) + ".");
  }
  if (item.cashGain <= -1) {
    outcome.push("Mein tiefster Kontostand sinkt im Basispfad um " + money.format(-item.cashGain) + ".");
  }
  if (!outcome.length && item.cashGain >= 1) {
    outcome.push("Mein tiefster Kontostand steigt im Basispfad um " + money.format(item.cashGain) + ".");
  }
  return ["Ich würde diese Variante ausprobieren. " + item.title + ".", item.detail, ...outcome].join(" ");
}

async function answer({ scenario, priority, question }) {
  if (!story.validScenario(scenario) || typeof question !== "string" ||
      question.trim().length === 0 || question.length > 400 ||
      (priority !== "" && !priorities.includes(priority))) {
    return { status: 400, error: "Die Anfrage enthält ungültige Eingaben." };
  }
  if (!(await status()).available) {
    return { status: 503, error: "Das lokale Modell " + modelName + " ist noch nicht verfügbar." };
  }
  const assessment = story.assess(scenario);
  const options = priority ? story.alternatives(scenario, priority, assessment) : [];
  const choices = new Map([
    ["plan", "Finanzielle Tragbarkeit und Engpässe des aktuellen Plans erklären"],
    ["other", "Frage liegt ausserhalb dieser Finanzsimulation"],
  ]);
  if (priority) {
    for (const [index, option] of options.entries()) {
      choices.set(String(index), option.title + ". " + option.detail);
    }
    if (!options.length) choices.set("changes", "Änderungen für die festgelegte Priorität prüfen");
  } else {
    for (const key of priorities) choices.set(key, "Alternativen prüfen. " + story.PRIORITIES[key]);
  }

  try {
    const decision = await choose(question.trim(), choices, priority, assessment);
    if (decision === "plan") {
      return { status: 200, answer: planSummary(assessment, scenario), model: modelName, tool: "pruefe_lebensplan" };
    }
    if (decision === "other") {
      return { status: 200, answer: "Frag mich nach meinem Lebensplan, einem Engpass oder einer Änderung, die wir simulieren können.",
        model: modelName };
    }
    const chosen = priority ? options[Number(decision)] :
      story.alternatives(scenario, decision, assessment)[0];
    const reply = chosen ? alternativeSummary(chosen, assessment) :
      "Für diese Priorität hat der Simulator bei den getesteten Einzeländerungen keine Verbesserung gefunden.";
    return { status: 200, answer: reply, model: modelName, tool: "vergleiche_alternativen", alternative: chosen };
  } catch {
    return { status: 503, error: "Das lokale Modell konnte die Frage gerade nicht beantworten. Die berechneten Alternativen stehen im Rückblick." };
  }
}

module.exports = { status, answer, requestChat, planSummary, alternativeSummary };
