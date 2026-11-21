const assert = require("node:assert/strict");
const { test } = require("node:test");
const { compare, DEFAULT_ASSUMPTIONS, DEMO_EVENTS, DEMO_PROFILE, simulate, validateEvent } = require("./model.js");

const flat = {
  rates: { equity: 0, bonds: 0 },
  assumptions: { salaryGrowth: 0, inflation: 0, equityReturn: 0 },
};
const cashOnly = { ...flat, investMonthly: false };
const profile = { age: 30, cash: 8000, portfolio: 0, income: 3000, expenses: 1800 };
const home = { id: 1, type: "home", age: 30, price: 200000, down: 40000,
  cost: 2000, rate: 0, term: 20, housingChange: 0 };

test("monthly balances reconcile and transfers into investments preserve net wealth at zero return", () => {
  const start = { ...profile, portfolio: 2000 };
  const plan = simulate(start, [], 31, 60, flat);
  const cash = simulate(start, [], 31, 60, cashOnly);
  assert.equal(plan.points.length, 13);
  assert.equal(plan.points[0].net, 10000);
  assert.equal(plan.points[1].contribution, 840);
  assert.equal(plan.points[12].net, 24400);
  assert.equal(plan.points[12].net, cash.points[12].net);
  assert.equal(plan.points[12].portfolio, 2000 + 12 * 840);
});

test("a gap year has zero income and the old monthly budget returns after the gap", () => {
  const gap = { id: 1, type: "gap", age: 30, duration: 2, expenses: 1000, cost: 500 };
  const { points } = simulate(profile, [gap], 31, 60, cashOnly);
  assert.equal(points[1].liquid, 6500);
  assert.equal(points[2].liquid, 5500);
  assert.equal(points[3].liquid, 6700);
  assert.equal(points[1].income, 0);
  assert.equal(points[1].expenses, 1000);
  assert.equal(points[1].oneOff, 500);
});

test("study changes income on completion and retirement then replaces the budget", () => {
  const study = { id: 1, type: "study", age: 30, duration: 6, income: 1000,
    expenses: 1200, cost: 1000, payChange: 500 };
  const retirement = { id: 2, type: "retire", age: 31, income: 1600, expenses: 2000 };
  const { points } = simulate(profile, [study, retirement], 32, 60, cashOnly);
  assert.equal(points[6].liquid, 5800);
  assert.equal(points[7].liquid - points[6].liquid, 1700);
  assert.equal(points[13].liquid - points[12].liquid, -400);
});

test("house equity and principal payments are transfers while purchase fees are an expense", () => {
  const start = { ...profile, cash: 80000, income: 0, expenses: 0 };
  const { points, eventResults } = simulate(start, [home], 31, 60, cashOnly);
  assert.equal(eventResults[1].executed, true);
  assert.equal(points[12].property, 200000);
  assert.ok(Math.abs(points[12].mortgage - 152000) < 0.0001);
  assert.ok(Math.abs(points[12].net - 78000) < 0.0001);
});

test("an unaffordable house is skipped and creates no phantom assets or debt", () => {
  const start = { ...profile, income: 0, expenses: 0 };
  const { points, eventResults } = simulate(start, [home], 31, 60, flat);
  assert.deepEqual(eventResults[1], { missing: 34000, executed: false });
  assert.equal(points[12].property, 0);
  assert.equal(points[12].mortgage, 0);
  assert.equal(points[12].net, 8000);
});

test("the plan sets money aside for upcoming expenses and detects unfunded payments", () => {
  const withExpense = simulate(profile, [{ id: 1, type: "expense", age: 31, cost: 40000 }], 32, 60, flat);
  assert.equal(withExpense.points[1].contribution, 0);
  assert.ok(withExpense.points[1].reserve > 25000);
  assert.equal(withExpense.firstShortfall, 13);
  assert.equal(withExpense.points[13].liquid, -16400);
});

test("salary growth and inflation compound separately and today's purchasing power is accounted for", () => {
  const assumptions = { ...flat.assumptions, salaryGrowth: 0.02, inflation: 0.03 };
  const { points } = simulate(profile, [], 32, 60, { ...cashOnly, assumptions });
  assert.equal(points[1].income, 3000);
  assert.equal(points[13].income, 3060);
  assert.equal(points[13].expenses, 1854);
  assert.equal(points[13].salaryGrowth, 0.02);
  assert.equal(points[24].realNet, points[24].net / 1.03 ** 2);
});

test("children add recurring inflation-adjusted costs from the event date through retirement", () => {
  const assumptions = { ...flat.assumptions, inflation: 0.02 };
  const children = { id: 1, type: "children", age: 31, count: 2, monthlyCost: 600 };
  const retirement = { id: 2, type: "retire", age: 32, income: 2500, expenses: 2000 };
  const { points } = simulate(profile, [children, retirement], 33, 60, { ...cashOnly, assumptions });
  assert.ok(points[12].expenses < 1840);
  assert.equal(points[13].expenses, 3060);
  assert.equal(points[25].expenses, 3200 * 1.02 ** 2);
  assert.equal(points[25].salaryGrowth, null);
  assert.equal(points[13].oneOff, 0);
});

test("property prices and purchase payments use the same inflation factor", () => {
  const start = { ...profile, cash: 80000, income: 0, expenses: 0 };
  const assumptions = { ...flat.assumptions, inflation: 0.02 };
  const { points } = simulate(start, [{ ...home, age: 31 }], 32, 60, { ...cashOnly, assumptions });
  assert.equal(points[13].property, 204000);
  assert.equal(points[13].oneOff, 42840);
  assert.ok(Math.abs(points[13].net - 77960) < 0.0001);
});

test("the reproducible equity path has losses and compounds to its selected geometric average", () => {
  const start = { ...profile, cash: 0, portfolio: 10000, income: 0, expenses: 0 };
  const assumptions = { ...DEFAULT_ASSUMPTIONS, equityReturn: 0.04 };
  const { points } = simulate(start, [], 42, 100, { assumptions, investMonthly: false });
  assert.ok(points[24].net < points[12].net);
  assert.ok(Math.abs(points.at(-1).net - 10000 * 1.04 ** 12) < 0.0001);
  assert.deepEqual(points, simulate(start, [], 42, 100, { assumptions, investMonthly: false }).points);
});

test("overlapping phases and duplicate home purchases are rejected", () => {
  const gap = { id: 1, type: "gap", age: 30, duration: 24 };
  assert.notEqual(validateEvent({ id: 2, type: "study", age: 31, duration: 12 }, [gap], 30), "");
  assert.notEqual(validateEvent({ id: 2, type: "retire", age: 31 }, [gap], 30), "");
  assert.notEqual(validateEvent({ ...home, id: 2, age: 35 }, [home], 30), "");
  assert.equal(validateEvent({ id: 2, type: "study", age: 32, duration: 12 }, [gap], 30), "");
});

test("moving a life event and changing risk both alter the projected wealth", () => {
  const original = compare(DEMO_PROFILE, DEMO_EVENTS, 52, 60);
  const moved = compare(DEMO_PROFILE, [DEMO_EVENTS[0], { ...DEMO_EVENTS[1], age: 39 }], 52, 60);
  const lowerRisk = compare(DEMO_PROFILE, DEMO_EVENTS, 52, 10);
  const end = (scenario) => scenario.points.at(-1).net;
  assert.notEqual(end(original.main), end(moved.main));
  assert.notEqual(end(original.main), end(lowerRisk.main));
  assert.ok(end(original.main) > end(original.noSavings));
  assert.ok(end(original.main) > end(original.weak));
  assert.ok(end(original.main) < end(original.strong));
});
