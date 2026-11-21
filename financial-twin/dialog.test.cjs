const assert = require("node:assert/strict");
const { test } = require("node:test");
const model = require("./model.js");
const story = require("./story.js");
const dialog = require("./dialog.cjs");

const plan = {
  profile: { ...story.DEMO, income: 5000, expenses: 3200, cash: 24000 },
  risk: 60, endAge: 75,
  assumptions: { ...model.DEFAULT_ASSUMPTIONS, salaryGrowth: 0, inflation: 0 },
  events: [{ id: 105, type: "home", age: 36, price: 400000, down: 80000, cost: 6000,
    rate: 1.8, term: 30, housingChange: -900 }],
};
const children = { id: 104, type: "children", age: 32, count: 1, monthlyCost: 800,
  costYears: 18, leaveMonths: 6, leaveIncome: 50 };
const context = { scenario: plan, stage: "Familie", age: 32, opening: false, priority: "" };

function mockModel(t, messages, response) {
  t.mock.method(globalThis, "fetch", async (url, request) => {
    if (url.endsWith("/tags")) {
      return Response.json({ models: [{ name: process.env.TWIN_OLLAMA_MODEL || "qwen3:4b" }] });
    }
    messages.push(JSON.parse(request.body).messages);
    return Response.json({ message: { content: JSON.stringify(response) } });
  });
}

test("a model question receives the player's history and draft without committing the event", async (t) => {
  const prompts = [];
  mockModel(t, prompts, {
    tip: "Teste dein Monatsbudget mit dem geringeren Lohn während der Elternzeit.",
    question: "Welche Kinderkosten möchtest du in den laufenden Ausgaben berücksichtigen?",
  });
  const reply = await dialog.reply({ ...context, draft: children, history: [
    { role: "assistant", content: "Was möchtest du bei der Elternzeit beibehalten?" },
    { role: "user", content: "Meine sechs Monate Elternzeit sollen bleiben." },
  ] });
  assert.equal(reply.status, 200);
  assert.equal(reply.source, process.env.TWIN_OLLAMA_MODEL || "qwen3:4b");
  assert.equal(reply.priority, "family");
  assert.match(prompts[0].at(-1).content, /Meine sechs Monate Elternzeit sollen bleiben/);
  assert.match(reply.question, /Kinderkosten/);
  assert.match(reply.insight.title, /Vorschau/);
  assert.match(reply.insight.lines[0], /Nettoeinkommen.*2.?500.*laufende Ausgaben.*4.?000/);
  assert.equal(plan.events.length, 1);
});

test("a follow-up with a new age compares the planned house purchase without moving the real event", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ models: [] }));
  const reply = await dialog.reply({ ...context, stage: "Rückblick", age: 75, history: [
    { role: "assistant", content: "Welchen Zeitpunkt möchtest du für den Hauskauf vergleichen?" },
    { role: "user", content: "Und mit 40?" },
  ] });
  assert.equal(reply.source, "simulation");
  assert.equal(reply.insight.compare.original.events[0].age, 36);
  assert.equal(reply.insight.compare.modified.events[0].age, 40);
  assert.equal(plan.events[0].age, 36);
});

test("partial model sentences fall back to a complete contextual question", async (t) => {
  mockModel(t, [], { tip: "Plane deine Elternzeit mit den laufenden Kinderkosten.", question: "Welche Kosten erwartest du" });
  const reply = await dialog.reply({ ...context, opening: true, history: [] });
  assert.equal(reply.source, "simulation");
  assert.match(reply.question, /Elternzeit.*Lohn.*?$/);
});

test("a repeated question from another chapter is replaced with one about the requested comparison", async (t) => {
  const prompts = [];
  const repeated = "Welche Ausgaben möchtest du bei der Elternzeit einplanen?";
  mockModel(t, prompts, { tip: "Prüfe den Puffer beim geplanten Hauskauf.", question: repeated });
  const reply = await dialog.reply({ ...context, stage: "Wohnen", age: 36, history: [
    { role: "assistant", stage: "Familie", content: repeated },
    { role: "user", stage: "Wohnen", content: "Hauskauf mit 40 durchrechnen?" },
  ] });
  assert.doesNotMatch(prompts[0].at(-1).content, /Welche Ausgaben möchtest du/);
  assert.match(reply.question, /Kaufbudget.*Kaufzeitpunkt/);
  assert.equal(reply.insight.compare.modified.events[0].age, 40);
});

test("an invalid requested age is reported and a monthly saving question uses the simulator", async (t) => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ models: [] }));
  const invalid = await dialog.reply({ ...context, stage: "Wohnen", age: 36,
    history: [{ role: "user", content: "Hauskauf mit 99?" }] });
  assert.match(invalid.insight.title, /ausserhalb/);
  assert.equal(invalid.insight.compare, undefined);
  const investing = await dialog.reply({ ...context,
    history: [{ role: "user", content: "Was bringt der monatliche Sparplan?" }] });
  assert.match(investing.insight.title, /Sparplan/);
  assert.match(investing.insight.lines[0], /heutiger Kaufkraft/);
});
