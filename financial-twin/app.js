(function () {
  "use strict";

  const model = window.FinancialTwin;
  const $ = (id) => document.getElementById(id);
  const write = (id, value) => { $(id).textContent = value; };
  const amountFormat = new Intl.NumberFormat("de-CH", { maximumFractionDigits: 0 });
  const centsFormat = new Intl.NumberFormat("de-CH", { maximumFractionDigits: 2 });
  const percentFormat = new Intl.NumberFormat("de-CH", { style: "percent", maximumFractionDigits: 1 });
  const direction = (amount) => Math.abs(amount) < 0.5 ? 0 : Math.sign(amount);
  const money = (amount) => (direction(amount) < 0 ? "−" : "") + "CHF " + amountFormat.format(Math.abs(amount));
  const fundingGap = (amount) => amount < 1 ? "CHF " + centsFormat.format(amount) : money(amount);
  const signedMoney = (amount) => (direction(amount) > 0 ? "+" : "") + money(amount);
  const percent = (amount) => percentFormat.format(amount);

  const state = {
    profile: { ...model.DEMO_PROFILE },
    events: model.DEMO_EVENTS.map((event) => ({ ...event })),
    endAge: 52,
    risk: 60,
    assumptions: { ...model.DEFAULT_ASSUMPTIONS },
    compareBy: "savings",
    showRange: true,
    isDemo: true,
  };
  let result;
  let nextEventId = 3;
  let editingId = null;
  let selectedAddAge = null;

  const chart = window.createWealthChart($("chart-wrap"), $("wealth-chart"), $("chart-tooltip"),
    $("chart-readout"), money, formatAge);
  const timeline = window.createTimeline({
    add: (age) => openEvent(null, age), edit: openEvent, move: moveEvent, formatAge, money, percent,
  });
  const profileDialog = $("profile-dialog");
  const profileForm = $("profile-form");
  const eventDialog = $("event-dialog");
  const eventForm = $("event-form");

  const duration = { name: "duration", label: "Dauer (Monate)", min: 1, max: 120, step: 1 };
  const income = { name: "income", label: "Nettoeinkommen / Monat (CHF)" };
  const expenses = { name: "expenses", label: "Ausgaben / Monat (CHF)" };
  const events = {
    study: {
      label: "Studium",
      fields: [duration, income, expenses, { name: "cost", label: "Einmalige Studienkosten (CHF)" },
        { name: "payChange", label: "Nettoeinkommen danach ± pro Monat (CHF)", min: -100000000 }],
      defaults: (profile) => ({
        duration: { Berufslehre: 36, Schulabschluss: 36, Master: 12, Promotion: 12 }[profile.education] ?? 24,
        income: 1200, expenses: Math.round(profile.expenses * 0.75), cost: 5000, payChange: 700,
      }),
      details: (event) => event.duration + " Monate · " + money(event.income) + " Einkommen pro Monat",
      help: "Während des Studiums gelten die eingegebenen Monatswerte. Danach ändert sich das bisherige Nettoeinkommen um den angegebenen Betrag.",
    },
    gap: {
      label: "Gap Year / Auszeit", shortLabel: "Auszeit",
      fields: [duration, expenses, { name: "cost", label: "Einmalige Kosten (CHF)" }],
      defaults: (profile) => ({ duration: 12, expenses: profile.expenses, cost: 4500 }),
      details: (event) => event.duration + " Monate ohne Einkommen · " + money(event.cost) + " einmalig",
      help: "Während der Auszeit beträgt das Einkommen CHF 0. Danach gelten wieder die bisherigen Monatswerte.",
    },
    home: {
      label: "Hauskauf",
      fields: [
        { name: "price", label: "Kaufpreis (CHF)", min: 1 },
        { name: "down", label: "Eigenkapital (CHF)" },
        { name: "cost", label: "Nebenkosten des Kaufs (CHF)" },
        { name: "rate", label: "Hypothekarzins pro Jahr (%)", max: 25 },
        { name: "term", label: "Laufzeit der Tilgung (Jahre)", min: 1, max: 60, step: 1 },
        { name: "housingChange", label: "Wohnkostenänderung / Monat (CHF)", min: -100000000 },
      ],
      defaults: () => ({ price: 580000, down: 115000, cost: 9000, rate: 1.8, term: 30, housingChange: -1000 }),
      details: (event) => money(event.price) + " Kaufpreis · " + money(event.down + event.cost) + " bei Kauf",
      help: "Die Wohnkostenänderung ist Unterhalt und übrige Wohnkosten abzüglich wegfallender Miete. Zins und Tilgung kommen separat dazu. Beim Kauf kann das Modell Anlagen verkaufen.",
    },
    expense: {
      label: "Grössere Ausgabe", shortLabel: "Ausgabe",
      fields: [{ name: "cost", label: "Einmalige Ausgabe (CHF)", min: 0.01 }],
      defaults: () => ({ cost: 15000 }),
      details: (event) => money(event.cost) + " einmalig",
      help: "Das Modell zieht den Betrag im ersten Monat des Ereignisses vom verfügbaren Vermögen ab.",
    },
    children: {
      label: "Kind(er)",
      shortLabel: (event) => event.count === 1 ? "1 Kind" : event.count + " Kinder",
      fields: [
        { name: "count", label: "Anzahl Kinder", min: 1, max: 20, step: 1 },
        { name: "monthlyCost", label: "Kosten je Kind / Monat in heutigen CHF" },
      ],
      defaults: () => ({ count: 1, monthlyCost: 900 }),
      details: (event) => money(event.count * event.monthlyCost) + " zusätzlich pro Monat in heutigen CHF",
      help: "Die Ausgaben steigen ab dem gewählten Alter dauerhaft um die Kosten pro Kind. Der Betrag wird im Modell an die Inflation angepasst.",
    },
    retire: {
      label: "Rente",
      fields: [{ ...income, label: "Netto-Renteneinkommen / Monat (CHF)" }, expenses],
      defaults: (profile) => ({ income: Math.round(profile.income * 0.65), expenses: profile.expenses }),
      details: (event) => money(event.income) + " Rente pro Monat",
      help: "Ab diesem Alter gelten das eingegebene Renteneinkommen und die monatlichen Ausgaben dauerhaft.",
    },
  };

  function formatAge(month, startingAge = state.profile.age) {
    const age = startingAge + Math.floor(month / 12);
    const remainder = month % 12;
    if (remainder === 0) return "Mit " + age + " Jahren";
    return "Mit " + age + " Jahren und " + remainder + (remainder === 1 ? " Monat" : " Monaten");
  }

  function renderChart() {
    const investing = state.compareBy === "savings";
    const alternate = investing ? result.noSavings : result.noEvents;
    const label = investing ? "Ohne monatlichen Sparplan" : "Ohne Lebensereignisse";
    const difference = result.main.points.at(-1).net - alternate.points.at(-1).net;
    $("compare-investments").setAttribute("aria-pressed", investing);
    $("compare-events").setAttribute("aria-pressed", !investing);
    $("range-legend").hidden = !state.showRange;
    write("comparison-legend", label);
    const effect = investing ? "verändert der Sparplan" : "verändern die Ereignisse";
    const summary = direction(difference) === 0
      ? "Beide Varianten ergeben mit " + state.endAge + " Jahren dasselbe Nettovermögen."
      : "Mit " + state.endAge + " Jahren " + effect + " das Nettovermögen im Modell um " +
        signedMoney(difference) + ".";
    write("comparison-summary", summary);
    chart.update({
      main: result.main.points,
      comparison: alternate.points,
      weak: result.weak.points,
      strong: result.strong.points,
      startAge: state.profile.age,
      endAge: state.endAge,
      events: state.events,
      showRange: state.showRange,
      comparisonLabel: label,
    });
  }

  function renderAges() {
    const age = state.profile.age;
    const horizons = [...new Set([Math.min(age + 10, model.MAX_AGE), Math.min(age + 25, model.MAX_AGE),
      65, 85, model.MAX_AGE, state.endAge])]
      .filter((year) => year > age).sort((a, b) => a - b);
    $("projection-age").replaceChildren(...horizons.map((year) => {
      const option = document.createElement("option");
      option.value = year;
      option.textContent = "Bis Alter " + year;
      return option;
    }));
    $("projection-age").value = state.endAge;
  }

  function renderProfile() {
    const profile = state.profile;
    const initial = Array.from(profile.name)[0]?.toLocaleUpperCase("de-CH") || "P";
    write("demo-label", state.isDemo ? "Fiktives Demo-Profil" : "Eigenes Szenario");
    write("header-initial", initial);
    write("profile-initial", initial);
    write("profile-name", profile.name || "Dein Profil");
    write("profile-description", profile.age + " Jahre · " + profile.education);
    for (const field of ["cash", "portfolio", "income", "expenses"]) {
      write("profile-" + field, money(profile[field]));
    }
  }

  function renderPlan() {
    const risk = state.risk;
    const level = risk < 35 ? "Vorsichtig" : risk < 70 ? "Ausgewogen" : "Chancenorientiert";
    write("risk-level", level);
    $("risk-slider").setAttribute("aria-valuetext", level + ", " + risk + " Prozent Aktien");
    write("equity-share", percent(risk / 100));
    write("bond-share", percent((100 - risk) / 100));
    $("allocation-equity").style.width = risk + "%";

    const { contribution, reserve } = result.main.points[1];
    write("monthly-investment", money(contribution));
    write("liquidity-target", money(reserve));
    write("plan-summary", result.main.totalContributions > 0
      ? "Der Sparplan investiert bis Alter " + state.endAge + " insgesamt " +
        money(result.main.totalContributions) + ". Die Rate passt sich an Überschuss und geplante Ausgaben an."
      : "In diesem Zeitraum bleibt der monatliche Sparplan bei CHF 0. Die Rate hängt vom Überschuss und der verfügbaren Liquidität ab.");

    const interruptions = [];
    const month = result.main.firstShortfall;
    if (month !== -1) {
      interruptions.push(formatAge(month) + " fehlen erstmals " + fundingGap(-result.main.points[month].liquid) + ".");
    }
    const skipped = state.events.filter((event) => result.main.eventResults[event.id]?.executed === false);
    if (skipped.length > 0) interruptions.push(skipped.length === 1
      ? "Ein Ereignis kann nicht finanziert werden. Details stehen im Zeitstrahl."
      : skipped.length + " Ereignisse können nicht finanziert werden. Details stehen im Zeitstrahl.");
    write("liquidity-notice", interruptions.join(" "));
    $("liquidity-notice").hidden = interruptions.length === 0;
  }

  function renderEvents() {
    const markers = [...state.events].sort((a, b) => a.age - b.age || a.id - b.id).map((event) => {
      const definition = events[event.type];
      const outcome = result.main.eventResults[event.id];
      const label = typeof definition.shortLabel === "function" ? definition.shortLabel(event) :
        definition.shortLabel ?? definition.label;
      return {
        ...event, label, detail: definition.details(event),
        warning: outcome?.executed === false ? "Ausgesetzt · " + fundingGap(outcome.missing) + " fehlen" : "",
      };
    });
    timeline.update({
      startAge: state.profile.age, endAge: state.endAge, points: result.main.points, events: markers,
    });
  }

  function render() {
    result = model.compare(state.profile, state.events, state.endAge, state.risk, state.assumptions);
    const starting = result.main.points[0].net;
    const ending = result.main.points.at(-1);
    const difference = ending.net - result.noSavings.points.at(-1).net;
    write("current-net", money(starting));
    write("future-label", "Modelliertes Nettovermögen mit " + state.endAge + " Jahren");
    write("future-net", money(ending.net));
    write("future-purchasing-power", "Heutige Kaufkraft · " + money(ending.realNet));
    write("investment-effect", signedMoney(difference));
    $("investment-effect").classList.toggle("positive", direction(difference) > 0);
    $("investment-effect").classList.toggle("negative", direction(difference) < 0);
    renderAges();
    renderProfile();
    renderChart();
    renderPlan();
    renderEvents();
  }

  function error(id, message = "") {
    write(id, message);
    $(id).hidden = message === "";
  }

  function moveEvent(id, age) {
    const item = { ...state.events.find((event) => event.id === id), age };
    const message = model.validateEvent(item, state.events, state.profile.age);
    error("timeline-status", message);
    if (message) return;
    state.events = state.events.map((event) => event.id === id ? item : event);
    render();
    timeline.focusEvent(id);
  }

  function openProfile() {
    for (const [field, value] of Object.entries(state.profile)) {
      profileForm.elements.namedItem(field).value = value;
    }
    profileForm.elements.clearEvents.checked = false;
    $("clear-events-label").hidden = state.events.length === 0;
    error("profile-error");
    profileDialog.showModal();
    profileForm.elements.namedItem("name").focus();
  }

  profileForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(profileForm);
    const age = Number(form.get("age"));
    const currentEvents = form.has("clearEvents") ? [] : state.events;
    const earlier = currentEvents.find((item) => item.age < age);
    if (earlier) {
      error("profile-error", "„" + events[earlier.type].label + "“ liegt vor dem neuen Startalter. " +
        "Ändere das Ereignis im Zeitstrahl oder wähle „Zeitstrahl beim Speichern leeren“.");
      return;
    }
    state.profile = {
      name: form.get("name").trim(), education: form.get("education"), age,
      cash: Number(form.get("cash")), portfolio: Number(form.get("portfolio")),
      income: Number(form.get("income")), expenses: Number(form.get("expenses")),
    };
    state.events = currentEvents;
    if (state.endAge <= age) state.endAge = Math.min(age + 25, model.MAX_AGE);
    state.isDemo = false;
    profileDialog.close();
    render();
  });

  function renderEventFields(type, values) {
    const definition = events[type];
    const fields = definition.fields.map((field) => {
      const label = document.createElement("label");
      label.textContent = field.label;
      const input = document.createElement("input");
      input.name = field.name;
      input.type = "number";
      input.min = field.min ?? 0;
      input.max = field.max ?? 100000000;
      input.step = field.step ?? 0.01;
      input.required = true;
      input.value = values[field.name];
      label.append(input);
      return label;
    });
    $("event-fields").replaceChildren(...fields);
    write("event-help", definition.help);
  }

  function openEvent(id = null, age = null) {
    editingId = id;
    selectedAddAge = age;
    const event = state.events.find((item) => item.id === id);
    const type = event?.type ?? "study";
    write("event-dialog-title", event ? "Ereignis bearbeiten" : "Ereignis hinzufügen");
    eventForm.elements.type.value = type;
    eventForm.elements.age.min = state.profile.age;
    eventForm.elements.age.value = event?.age ?? age ?? Math.min(model.MAX_AGE - 1, state.profile.age + 2);
    renderEventFields(type, event ?? events[type].defaults(state.profile));
    $("delete-event").hidden = !event;
    error("event-error");
    eventDialog.showModal();
    eventForm.elements.type.focus();
  }

  eventForm.elements.type.addEventListener("change", () => {
    const type = eventForm.elements.type.value;
    renderEventFields(type, events[type].defaults(state.profile));
    if (editingId === null && selectedAddAge === null) {
      const suggestedAge = type === "retire" ? Math.max(65, state.profile.age) :
        state.profile.age + (type === "home" ? 8 : 2);
      eventForm.elements.age.value = Math.min(model.MAX_AGE - 1, suggestedAge);
    }
    error("event-error");
  });

  eventForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(eventForm);
    const type = form.get("type");
    const id = editingId ?? nextEventId;
    const age = Number(form.get("age"));
    const item = { id, type, age };
    for (const field of events[type].fields) item[field.name] = Number(form.get(field.name));
    const message = model.validateEvent(item, state.events, state.profile.age);
    if (message) {
      error("event-error", message);
      return;
    }
    state.events = [...state.events.filter((existing) => existing.id !== id), item];
    if (editingId === null) nextEventId += 1;
    if (age >= state.endAge) {
      state.endAge = Math.min(model.MAX_AGE, age + (type === "retire" ? 20 : 5));
    }
    eventDialog.close();
    error("timeline-status");
    render();
    timeline.focusEvent(id);
  });

  $("delete-event").addEventListener("click", () => {
    state.events = state.events.filter((event) => event.id !== editingId);
    eventDialog.close();
    error("timeline-status");
    render();
    $("add-event").focus();
  });
  $("edit-profile").addEventListener("click", openProfile);
  $("header-profile").addEventListener("click", openProfile);
  $("add-event").addEventListener("click", () => openEvent());
  $("open-assumptions").addEventListener("click", () => {
    renderReturnTable();
    $("assumptions-dialog").showModal();
  });
  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog").close());
  });
  $("projection-age").addEventListener("change", (event) => {
    state.endAge = Number(event.target.value);
    render();
  });
  $("risk-slider").addEventListener("input", (event) => {
    state.risk = Number(event.target.value);
    render();
  });
  $("compare-investments").addEventListener("click", () => {
    state.compareBy = "savings";
    renderChart();
  });
  $("compare-events").addEventListener("click", () => {
    state.compareBy = "events";
    renderChart();
  });
  $("show-range").addEventListener("change", (event) => {
    state.showRange = event.target.checked;
    renderChart();
  });

  for (const [id, key] of [
    ["salary-growth", "salaryGrowth"], ["inflation", "inflation"], ["equity-return", "equityReturn"],
  ]) {
    const input = $(id);
    input.value = Number((state.assumptions[key] * 100).toFixed(1));
    input.addEventListener("input", () => {
      if (!input.validity.valid) return;
      state.assumptions[key] = input.valueAsNumber / 100;
      render();
    });
    input.addEventListener("blur", () => {
      if (!input.validity.valid) input.value = Number((state.assumptions[key] * 100).toFixed(1));
    });
  }

  function renderReturnTable() {
    const rates = model.returnCases(state.assumptions.equityReturn);
    const table = $("return-table");
    table.replaceChildren();
    for (const [key, label] of [["equity", "Aktien"], ["bonds", "Anleihen"]]) {
      const row = table.insertRow();
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.textContent = label;
      row.append(heading);
      for (const scenario of ["weak", "central", "strong"]) {
        row.insertCell().textContent = percent(rates[scenario][key]);
      }
    }
  }

  function updateNavigation() {
    const hash = window.location.hash || "#uebersicht";
    for (const link of document.querySelectorAll(".header-inner nav a")) {
      if (link.hash === hash) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    }
  }
  window.addEventListener("hashchange", updateNavigation);
  updateNavigation();
  render();
})();
