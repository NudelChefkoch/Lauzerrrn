(function (root) {
  "use strict";

  const MAX_AGE = 100;
  const RESERVE_MONTHS = 3;
  const LOOKAHEAD_MONTHS = 36;
  const SAVINGS_SHARE = 0.7;
  const DEFAULT_ASSUMPTIONS = { salaryGrowth: 0.02, inflation: 0.015, equityReturn: 0.06 };
  const annualSwings = [0.11, -0.17, 0.14, -0.04, 0.08, 0.12, -0.28, 0.17, 0.07, -0.07, 0.09, -0.22];
  const monthlySwings = [-0.018, 0.012, 0.004, -0.005, 0.012, 0.006];
  const mean = (values) => values.reduce((total, value) => total + value, 0) / values.length;
  const annualMean = mean(annualSwings);
  const monthlyMean = mean(monthlySwings);

  const DEMO_PROFILE = {
    name: "Alexia", age: 27, education: "Bachelor",
    cash: 34000, portfolio: 18000, income: 6300, expenses: 4200,
  };

  const DEMO_EVENTS = [
    { id: 1, type: "gap", age: 31, duration: 6, expenses: 3500, cost: 4500 },
    { id: 2, type: "home", age: 36, price: 580000, down: 115000, cost: 9000,
      rate: 1.8, term: 30, housingChange: -1000 },
  ];
  const isEducation = (event) => event.type === "study" || event.type === "apprentice";
  const isTemporary = (event) => isEducation(event) || event.type === "gap";

  function returnCases(equityReturn) {
    return {
      central: { equity: equityReturn, bonds: 0.02, variableEquity: true },
      weak: { equity: equityReturn - 0.09, bonds: 0.005, variableEquity: true },
      strong: { equity: equityReturn + 0.03, bonds: 0.035, variableEquity: true },
    };
  }

  function monthlyEquityGrowth(rates, month) {
    const average = Math.log1p(rates.equity) / 12;
    if (!rates.variableEquity) return Math.exp(average);
    const year = Math.floor(month / 12) % annualSwings.length;
    return Math.exp(average + (annualSwings[year] - annualMean) / 12 +
      monthlySwings[month % monthlySwings.length] - monthlyMean);
  }

  function validateEvent(event, events, profileAge) {
    if (!Number.isInteger(event.age) || event.age < profileAge || event.age >= MAX_AGE) {
      return "Das Ereignis muss zwischen deinem heutigen Alter und 99 Jahren beginnen.";
    }

    const others = events.filter((item) => item.id !== event.id);
    if ((event.type === "retire" || event.type === "home") &&
        others.some((item) => item.type === event.type)) {
      return "Dieses Ereignis kann einmal im Zeitstrahl vorkommen.";
    }
    if (event.type === "home" && event.down > event.price) {
      return "Das Eigenkapital darf den Kaufpreis nicht überschreiten.";
    }

    const endMonth = (item) => item.age * 12 + item.duration;
    if (isTemporary(event) && others.some((item) => isTemporary(item) &&
        event.age * 12 < endMonth(item) && item.age * 12 < endMonth(event))) {
      return "Studium, Berufslehre und Auszeit dürfen sich zeitlich nicht überschneiden.";
    }
    if (isTemporary(event) && others.some((item) => item.type === "retire" &&
        item.age * 12 < endMonth(event))) {
      return "Ausbildung und Auszeit müssen vor dem Rentenbeginn enden.";
    }
    if (event.type === "retire" && others.some((item) => isTemporary(item) &&
        event.age * 12 < endMonth(item))) {
      return "Lege die Rente nach dem Ende von Ausbildung und Auszeit fest.";
    }
    return "";
  }

  function monthlyBudget(profile, events, months, assumptions) {
    const priceFactor = (month) => (1 + assumptions.inflation) ** (month / 12);
    const salaryFactor = (month) => (1 + assumptions.salaryGrowth) ** (month / 12);
    const scheduled = events.map((event) => ({
      ...event, start: (event.age - profile.age) * 12,
    }));
    const education = scheduled.filter(isEducation);
    const temporary = scheduled.filter(isTemporary);
    const retirement = scheduled.find((event) => event.type === "retire");
    const children = scheduled.filter((event) => event.type === "children");
    const household = scheduled.filter((event) => event.type === "marriage" || event.type === "move");
    const homeEvent = scheduled.find((event) => event.type === "home");
    const purchasePrices = homeEvent && priceFactor(homeEvent.start);
    const home = homeEvent && {
      ...homeEvent,
      price: homeEvent.price * purchasePrices,
      down: homeEvent.down * purchasePrices,
      cost: homeEvent.cost * purchasePrices,
    };

    const starts = Array.from({ length: months }, () => []);
    for (const event of scheduled) {
      if (event.start >= 0 && event.start < months) starts[event.start].push(event);
    }

    return starts.map((starting, month) => {
      const currentPhase = temporary.find((event) => event.start <= month &&
        month < event.start + event.duration);
      const retired = retirement && retirement.start <= month;
      const inflationFactor = priceFactor(month);
      const payChange = education.reduce((total, event) => {
        const finished = event.start + event.duration;
        return finished <= month
          ? total + event.payChange * priceFactor(finished) * salaryFactor(month - finished)
          : total;
      }, 0);
      let income = Math.max(0, profile.income * salaryFactor(month) + payChange);
      let livingCosts = profile.expenses;
      if (retired) {
        income = retirement.income * inflationFactor;
        livingCosts = retirement.expenses;
      } else if (currentPhase) {
        income = currentPhase.type === "gap" ? 0 : currentPhase.income * inflationFactor;
        livingCosts = currentPhase.expenses;
      } else {
        const leaveIncomeShare = children.reduce((share, event) =>
          event.start <= month && month < event.start + (event.leaveMonths ?? 0)
            ? Math.min(share, (event.leaveIncome ?? 0) / 100) : share, 1);
        income *= leaveIncomeShare;
      }
      const childCosts = children.reduce((total, event) => {
        const elapsed = month - event.start;
        return total + (elapsed >= 0 && (!event.costYears || elapsed < event.costYears * 12)
          ? event.count * event.monthlyCost : 0);
      }, 0);
      const householdChange = household.reduce((total, event) =>
        total + (event.start <= month ? event.monthlyChange : 0), 0);
      livingCosts = Math.max(0, livingCosts + householdChange);
      const mandatory = starting.filter((event) =>
        isTemporary(event) || ["expense", "marriage", "move"].includes(event.type));
      const cashCosts = mandatory.reduce((total, event) => total + event.cost, 0) * inflationFactor;
      const purchase = home?.start === month ? home : null;
      let housing = null;
      if (home && home.start <= month) {
        const principal = home.price - home.down;
        const instalment = principal / (home.term * 12);
        const remaining = Math.max(0, principal - (month - home.start) * instalment);
        housing = {
          change: Math.max(-livingCosts, home.housingChange) * inflationFactor,
          interest: remaining * home.rate / 1200,
          repayment: Math.min(remaining, instalment),
        };
      }
      return {
        income, expenses: (livingCosts + childCosts) * inflationFactor, cashCosts, purchase, housing,
        salaryGrowth: retired || currentPhase ? null : assumptions.salaryGrowth,
      };
    });
  }

  function recurringExpenses(entry, homeFailed) {
    const housing = homeFailed ? null : entry.housing;
    return entry.expenses + (housing ? housing.change + housing.interest + housing.repayment : 0);
  }

  function reserveTarget(budget, month, homeFailed, horizon) {
    let cumulative = 0;
    let needed = RESERVE_MONTHS * recurringExpenses(budget[month], homeFailed);
    for (let future = month + 1; future <= horizon; future += 1) {
      const entry = budget[future];
      const purchase = entry.purchase && !homeFailed ? entry.purchase.down + entry.purchase.cost : 0;
      const recurring = recurringExpenses(entry, homeFailed);
      cumulative += entry.income - recurring - entry.cashCosts - purchase;
      needed = Math.max(needed, RESERVE_MONTHS * recurring - cumulative);
    }
    return needed;
  }

  function simulate(profile, events, endAge, risk, {
    assumptions = DEFAULT_ASSUMPTIONS,
    rates = returnCases(assumptions.equityReturn).central,
    investMonthly = true,
  } = {}) {
    const months = (endAge - profile.age) * 12;
    const equityWeight = risk / 100;
    const bondGrowth = (1 + rates.bonds) ** (1 / 12);
    const budget = monthlyBudget(profile, events, Math.min(
      months + LOOKAHEAD_MONTHS, (MAX_AGE - profile.age) * 12,
    ), assumptions);
    let liquid = profile.cash;
    let equity = profile.portfolio * equityWeight;
    let bonds = profile.portfolio - equity;
    let property = 0;
    let mortgage = 0;
    let homeFailed = false;
    let totalContributions = 0;
    const eventResults = {};
    const snapshot = (month, extra) => {
      const net = liquid + equity + bonds + property - mortgage;
      return {
        liquid, portfolio: equity + bonds, property, mortgage, net,
        realNet: net / (1 + assumptions.inflation) ** (month / 12), ...extra,
      };
    };
    const points = [snapshot(0, { contribution: 0, reserve: profile.expenses * RESERVE_MONTHS })];

    function sellForCash(amount) {
      const portfolio = equity + bonds;
      if (amount <= 0 || portfolio <= 0) return;
      const fraction = Math.min(1, amount / portfolio);
      const proceeds = portfolio * fraction;
      equity *= 1 - fraction;
      bonds *= 1 - fraction;
      liquid += proceeds;
    }

    function invest(amount) {
      liquid -= amount;
      equity += amount * equityWeight;
      bonds += amount * (1 - equityWeight);
    }

    for (let month = 0; month < months; month += 1) {
      const entry = budget[month];
      equity *= monthlyEquityGrowth(rates, month);
      bonds *= bondGrowth;
      let oneOff = entry.cashCosts;
      liquid += entry.income - entry.expenses - oneOff;
      if (entry.purchase) {
        const purchase = entry.purchase;
        const required = purchase.down + purchase.cost;
        const missing = Math.max(0, required - liquid - equity - bonds);
        homeFailed = missing > 0.005;
        eventResults[purchase.id] = { missing, executed: !homeFailed };
        if (!homeFailed) {
          sellForCash(required - liquid);
          liquid -= required;
          oneOff += required;
          property = purchase.price;
          mortgage = purchase.price - purchase.down;
        }
      }
      const expenses = recurringExpenses(entry, homeFailed);
      liquid -= expenses - entry.expenses;
      if (entry.housing && !homeFailed) {
        mortgage = Math.max(0, mortgage - entry.housing.repayment);
      }
      sellForCash(-liquid);
      const reserve = reserveTarget(budget, month, homeFailed,
        Math.min(month + LOOKAHEAD_MONTHS, budget.length - 1));
      const surplus = entry.income - expenses;
      const contribution = investMonthly
        ? Math.max(0, Math.floor(Math.min(surplus * SAVINGS_SHARE, liquid - reserve))) : 0;
      invest(contribution);
      totalContributions += contribution;
      points.push(snapshot(month + 1, {
        contribution, reserve, expenses, oneOff, income: entry.income, salaryGrowth: entry.salaryGrowth,
      }));
    }

    const firstShortfall = points.findIndex((point) => point.liquid < -0.005);
    return { points, firstShortfall, eventResults, totalContributions };
  }

  function compare(profile, events, endAge, risk, assumptions = DEFAULT_ASSUMPTIONS) {
    const rates = returnCases(assumptions.equityReturn);
    return {
      main: simulate(profile, events, endAge, risk, { assumptions, rates: rates.central }),
      noSavings: simulate(profile, events, endAge, risk,
        { assumptions, rates: rates.central, investMonthly: false }),
      noEvents: simulate(profile, [], endAge, risk, { assumptions, rates: rates.central }),
      weak: simulate(profile, events, endAge, risk, { assumptions, rates: rates.weak }),
      strong: simulate(profile, events, endAge, risk, { assumptions, rates: rates.strong }),
    };
  }

  root.FinancialTwin = {
    MAX_AGE, DEFAULT_ASSUMPTIONS, returnCases,
    DEMO_PROFILE, DEMO_EVENTS, validateEvent, compare, simulate,
  };
  if (typeof module === "object" && module.exports) module.exports = root.FinancialTwin;
})(globalThis);
