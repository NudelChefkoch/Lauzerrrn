const assert = require("node:assert/strict");
const { test } = require("node:test");
const model = require("./model.js");
const story = require("./story.js");
const agent = require("./agent.cjs");

const profile = { ...story.DEMO, age: 27, cash: 18000, income: 5000, expenses: 3600 };
const assumptions = { salaryGrowth: 0, inflation: 0, equityReturn: 0 };
const options = { assumptions, rates: { equity: 0, bonds: 0 }, investMonthly: false };
const children = { id: 103, type: "children", age: 29, count: 2, monthlyCost: 250,
  costYears: 2, leaveMonths: 6, leaveIncome: 50 };
const home = { id: 105, type: "home", age: 30, price: 450000, down: 90000, cost: 8000,
  rate: 1.8, term: 30, housingChange: -900 };

test("parental leave ends on time and child costs expire on their own schedule", () => {
  const { points } = model.simulate(profile, [children], 32, 0, options);
  assert.equal(points[24].income, 5000);
  assert.equal(points[25].income, 2500);
  assert.equal(points[30].income, 2500);
  assert.equal(points[31].income, 5000);
  assert.equal(points[48].expenses, 4100);
  assert.equal(points[49].expenses, 3600);
});

test("marriage and relocation apply personal cash costs and leave salary intact", () => {
  const events = [
    { id: 1, type: "marriage", age: 27, cost: 5000, monthlyChange: -250 },
    { id: 2, type: "move", age: 28, cost: 2300, monthlyChange: 450 },
  ];
  const { points } = model.simulate(profile, events, 29, 0, options);
  assert.equal(points[1].income, 5000);
  assert.equal(points[1].oneOff, 5000);
  assert.equal(points[1].expenses, 3350);
  assert.equal(points[13].oneOff, 2300);
  assert.equal(points[13].expenses, 3800);
});

test("an apprenticeship uses the training budget and then the changed employment income", () => {
  const training = { id: 1, type: "apprentice", age: 27, duration: 18, income: 1300,
    expenses: 1600, cost: 800, payChange: 600 };
  const { points } = model.simulate(profile, [training], 29, 0, options);
  assert.equal(points[1].income, 1300);
  assert.equal(points[18].income, 1300);
  assert.equal(points[19].income, 5600);
  assert.equal(points[19].expenses, 3600);
  assert.notEqual(model.validateEvent({ id: 2, type: "gap", age: 28, duration: 4 }, [training], 27), "");
});

const plan = {
  profile, assumptions: model.DEFAULT_ASSUMPTIONS, events: [children, home], risk: 60, endAge: 65,
};

test("an unfunded home is flagged and financial fixes respect the chosen life priority", () => {
  const direct = story.assess(plan);
  assert.equal(direct.status, "difficult");
  assert.equal(direct.base.home.executed, false);
  const familyOptions = story.alternatives(plan, "family", direct);
  assert.ok(familyOptions.length > 0);
  assert.ok(familyOptions.every(({ event }) => event.id !== children.id));
  assert.ok(familyOptions.some(({ assessment }) => assessment.base.home.executed));
  const homeOptions = story.alternatives(plan, "home", direct);
  assert.ok(homeOptions.every(({ event }) => event.type !== "home" || event.age === home.age));
  assert.equal(plan.events[0].leaveMonths, 6);
  assert.equal(plan.events[1].age, 30);
});

test("agent scenario validation rejects malformed structured input", () => {
  assert.equal(story.validScenario(plan), true);
  assert.equal(story.validScenario({ ...plan, events: [home, null] }), false);
  assert.equal(story.validScenario({ ...plan, assumptions: { ...assumptions, equityReturn: -1 } }), false);
});

test("the agent lets Ollama select a verified option while preserving the chosen priority", async (test) => {
  const requests = [];
  assert.equal((await agent.answer({ scenario: null })).status, 400);
  test.mock.method(globalThis, "fetch", async (url, request) => {
    if (url.endsWith("/tags")) {
      return Response.json({ models: [{ name: process.env.TWIN_OLLAMA_MODEL || "qwen3:4b" }] });
    }
    const body = JSON.parse(request.body);
    requests.push(body);
    return Response.json({ message: { role: "assistant", content: JSON.stringify({ choice: "0" }) } });
  });
  const result = await agent.answer({ scenario: plan, priority: "family", question: "Wie finanziere ich den Hauskauf?" });
  assert.equal(result.status, 200);
  assert.equal(requests.length, 1);
  assert.ok(requests[0].format.properties.choice.enum.includes("0"));
  const sent = requests[0].messages.at(-1);
  assert.match(sent.content, /Kinder und Elternzeit beibehalten/);
  assert.doesNotMatch(sent.content, /Elternzeit kürzer planen/);
  assert.equal(result.tool, "vergleiche_alternativen");
  assert.equal(result.alternative.event.type, "home");
  assert.match(result.answer, /Eigenheim/);
});
