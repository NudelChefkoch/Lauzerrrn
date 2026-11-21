(function (root) {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const model = root.FinancialTwin;
  const story = root.TwinStory;
  const dashboard = root.TwinDashboard;
  const scene = root.createLifeScene($("life-scene"));
  const { money, formatAge } = dashboard;
  const chapters = story.CHAPTERS;
  const avatarForm = $("avatar-form");
  const panel = $("game-interaction");
  let avatar;
  let scenario;
  let baseline;
  let decisions = [];
  let index = 0;
  let review = false;
  let playing = false;
  let returnToReview = false;
  let previewing = false;
  let priority = "";
  let coachContext;
  let readDraft;
  const coach = root.TwinCoach.create({
    snapshot() {
      if (!scenario || !coachContext) return null;
      const draft = readDraft?.();
      return { scenario, priority, stage: coachContext.stage, age: draft?.age ?? coachContext.age, draft };
    },
    compare({ original, modified }) { openDashboard(modified, original); },
  });

  function visitCoach(key, stage, age) {
    coachContext = { stage, age: Math.max(scenario.profile.age, age) };
    coach.visit(key, stage, scenario.profile.name);
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function button(text, action, className = "button button-secondary") {
    const node = element("button", className, text);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  }

  function write(id, text) { $(id).textContent = text; }

  function heading(title, text) {
    $("game-title").replaceChildren(title, element("span", "headline-dot", "."));
    write("game-description", text);
  }

  function spanLabel(months) {
    const years = Math.floor(months / 12);
    const remainder = months % 12;
    const parts = [];
    if (years || !remainder) parts.push(years + (years === 1 ? " Jahr" : " Jahre"));
    if (remainder) parts.push(remainder + (remainder === 1 ? " Monat" : " Monate"));
    return parts.join(" und ");
  }

  function banner(kind, age, title, text) {
    write("scene-place", title);
    write("scene-age", spanLabel(Math.round(age * 12)));
    write("scene-title", kind);
    write("scene-text", text);
  }

  function showAvatar() {
    const values = new FormData(avatarForm);
    avatar = { skin: +values.get("skin"), hair: +values.get("hair"), outfit: +values.get("outfit") };
    const age = Math.max(18, Math.min(99, +values.get("age") || 20));
    const name = values.get("name").trim() || "Dein Zwilling";
    scene.show({ kind: "city", age, avatar });
    banner("Lerne deinen Zwilling kennen", age, "Heute", name + " steht am Anfang dieser Geschichte.");
  }

  function storyScene(kind, age, data = {}) {
    return { kind, age, avatar, children: scenario.events.filter((event) => event.type === "children"), ...data };
  }

  function start(profile) {
    scenario = {
      profile, events: [], risk: 60, assumptions: { ...model.DEFAULT_ASSUMPTIONS },
      endAge: Math.min(100, Math.max(75, profile.age + 25)),
    };
    decisions = [];
    coach.reset();
    coachContext = readDraft = null;
    baseline = null;
    index = 0;
    review = false;
    playing = false;
    returnToReview = false;
    priority = "";
    avatarForm.hidden = true;
    panel.hidden = false;
    $("chapter-nav").hidden = false;
    renderChapter();
  }

  function reset() {
    scenario = null;
    decisions = [];
    review = false;
    coach.reset();
    coachContext = readDraft = null;
    panel.hidden = true;
    avatarForm.hidden = false;
    $("chapter-nav").hidden = true;
    $("chapter-budget").hidden = true;
    heading("Spiel dein Leben", "Gestalte deinen digitalen Zwilling und probiere aus, wohin deine Entscheidungen führen.");
    showAvatar();
    avatarForm.elements.namedItem("name").focus();
  }

  function renderChapters() {
    const tabs = chapters.map((chapter, chapterIndex) => {
      const tab = button(chapter.title, () => {
        if (playing) return;
        returnToReview = review || returnToReview;
        review = false;
        index = chapterIndex;
        renderChapter();
      }, "");
      tab.disabled = playing || chapterIndex > decisions.length;
      if (!review && chapterIndex === index) tab.setAttribute("aria-current", "step");
      return tab;
    });
    if (decisions.length === chapters.length || review) {
      const tab = button("Rückblick", showReview, "");
      tab.disabled = playing;
      if (review) tab.setAttribute("aria-current", "step");
      tabs.push(tab);
    }
    $("chapter-nav").replaceChildren(...tabs);
  }

  function chapterAge() {
    return decisions[index]?.age ?? story.chapterAge(chapters[index], scenario.profile.age, decisions.slice(0, index));
  }

  function showStats(entries) {
    const blocks = entries.map(([label, value]) => {
      const block = element("div", "game-stat");
      block.append(element("span", "", label), element("strong", "", value));
      return block;
    });
    $("chapter-budget").replaceChildren(...blocks);
    $("chapter-budget").hidden = blocks.length === 0;
  }

  function sectionTitle(text) { return element("h2", "", text); }

  function actions(...buttons) {
    const row = element("div", "game-actions");
    row.append(...buttons);
    return row;
  }

  function numericField(field, value) {
    const label = element("label", "", field.label);
    const input = element("input");
    input.type = "number";
    input.name = field.name;
    input.min = field.min ?? 0;
    input.max = field.max ?? 100000000;
    input.step = field.step ?? 0.01;
    input.required = true;
    input.value = value;
    label.append(input);
    return label;
  }

  function renderChapter(choiceIndex = decisions[index]?.choiceIndex ?? null) {
    const chapter = chapters[index];
    const age = chapterAge();
    const selected = chapter.choices[choiceIndex];
    readDraft = null;
    renderChapters();
    heading(chapter.title, "Wähle, wie dieses Kapitel in deiner Geschichte weitergeht.");
    banner(chapter.prompt, age, chapter.title, "Dein Zwilling ist an diesem Punkt " + age + " Jahre alt.");
    scene.show(storyScene(chapter.scene, age, { funded: false }));
    showStats([]);
    const choices = element("div", "choice-list");
    chapter.choices.forEach((choice, position) => {
      const option = button("", () => renderChapter(position), "choice");
      option.append(element("strong", "", choice.label), element("span", "", choice.text));
      option.setAttribute("aria-pressed", position === choiceIndex);
      choices.append(option);
    });
    panel.replaceChildren(sectionTitle(chapter.prompt), choices);
    if (!selected) {
      visitCoach(index, chapter.title, age);
      return;
    }

    const form = element("form", "chapter-form");
    const grid = element("div", "form-grid");
    const definition = dashboard.eventTypes[selected.type];
    const lastAge = decisions[index - 1]?.age ?? scenario.profile.age;
    const nextAge = decisions[index + 1]?.age ?? model.MAX_AGE - 1;
    grid.append(numericField({ name: "age", label: "Alter bei Beginn", min: lastAge, max: nextAge, step: 1 }, age));
    let leaveToggle;
    if (definition) {
      const old = decisions[index]?.event;
      const values = { ...definition.defaults(scenario.profile), ...(old?.type === selected.type ? old : {}) };
      const leaveFields = new Set(["leaveMonths", "leaveIncome"]);
      for (const field of definition.fields) {
        if (selected.type !== "children" || !leaveFields.has(field.name)) {
          grid.append(numericField(field, values[field.name]));
        }
      }
      if (selected.type === "children") {
        const toggleLabel = element("label", "form-wide game-leave-switch", "Elternzeit einplanen");
        leaveToggle = element("input");
        leaveToggle.type = "checkbox";
        leaveToggle.checked = values.leaveMonths > 0;
        toggleLabel.prepend(leaveToggle);
        const extra = element("div", "form-grid form-wide");
        for (const field of definition.fields.filter((item) => leaveFields.has(item.name))) {
          const label = field.name === "leaveMonths" ? { ...field, min: 1, label: "Monate Elternzeit" } : field;
          extra.append(numericField(label, field.name === "leaveMonths" ? values.leaveMonths || 6 : values.leaveIncome));
        }
        function updateLeave() {
          extra.hidden = !leaveToggle.checked;
          for (const input of extra.querySelectorAll("input")) input.disabled = extra.hidden;
        }
        leaveToggle.addEventListener("change", updateLeave);
        updateLeave();
        grid.append(toggleLabel, extra);
      }
    }
    const error = element("p", "game-error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    const submit = element("button", "button button-primary", "Kapitel spielen");
    submit.type = "submit";
    form.append(grid);
    if (definition) form.append(element("p", "", definition.help));
    form.append(error, actions(submit));
    const id = index + 101;
    function eventInput(values) {
      if (!definition) return null;
      const item = { id, age: Number(values.get("age")), type: selected.type };
      for (const field of definition.fields) item[field.name] = Number(values.get(field.name));
      if (leaveToggle && !leaveToggle.checked) item.leaveIncome = 55;
      return item;
    }
    readDraft = () => [...form.querySelectorAll("input")].every((input) => input.disabled || input.validity.valid)
      ? eventInput(new FormData(form)) : null;
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const startAge = Number(data.get("age"));
      const eventData = eventInput(data);
      if (eventData) {
        const message = model.validateEvent(eventData, scenario.events, scenario.profile.age);
        if (message) {
          error.textContent = message;
          error.hidden = false;
          return;
        }
      }
      const previous = scenario.events.find((item) => item.id === id) ?? null;
      if (returnToReview && !baseline && JSON.stringify(previous) !== JSON.stringify(eventData)) {
        baseline = scenario;
      }
      const events = scenario.events.filter((item) => item.id !== id);
      if (eventData) events.push(eventData);
      scenario = { ...scenario, events, endAge: Math.min(100, Math.max(scenario.endAge, startAge + 8)) };
      decisions[index] = { age: startAge, event: eventData, choiceIndex };
      const next = () => {
        if (returnToReview || index === chapters.length - 1) showReview();
        else {
          index += 1;
          renderChapter();
        }
      };
      const ageAfter = Math.min(scenario.endAge, startAge + (eventData?.duration ??
        eventData?.leaveMonths ?? 0) / 12);
      playScene(selected.scene, startAge, ageAfter, selected.label, eventData, next);
    });
    panel.append(form);
    visitCoach(index, chapter.title, age);
  }

  function playScene(kind, fromAge, age, title, event, next) {
    readDraft = null;
    playing = true;
    root.scrollTo(0, 0);
    renderChapters();
    const run = model.simulate(scenario.profile, scenario.events, scenario.endAge, scenario.risk,
      { assumptions: scenario.assumptions });
    const budget = run.points[Math.min(run.points.length - 1, (fromAge - scenario.profile.age) * 12 + 1)];
    const purchase = run.eventResults[event?.id];
    const funded = purchase?.executed === true;
    const caption = event?.type === "home" && !funded
      ? "Für den Kauf fehlen im Modell " + money(purchase?.missing ?? 0) + "."
      : event ? dashboard.eventTypes[event.type].details(event) : "Dein Monatsbudget läuft ab diesem Zeitpunkt weiter.";
    banner(title, fromAge, "Dein Lebensweg", "Das Kapitel beginnt mit " + fromAge + " Jahren.");
    $("skip-animation").hidden = false;
    panel.replaceChildren(sectionTitle(title), element("p", "", "Schau, wie dieses Kapitel ausgeht."));
    showStats([]);
    scene.play(storyScene(kind, age, { fromAge, funded }), () => {
      $("skip-animation").hidden = true;
      playing = false;
      renderChapters();
      const elapsed = Math.round((age - fromAge) * 12);
      const jump = elapsed ? spanLabel(elapsed) + " später" : "Mit " + age + " Jahren";
      banner(title, age, jump, caption);
      showStats([
        ["Nettoeinkommen im Startmonat", money(budget.income)],
        ["Laufende Ausgaben im Startmonat", money(budget.expenses)],
        ["Einmalige Zahlungen im Startmonat", money(budget.oneOff)],
      ]);
      panel.replaceChildren(sectionTitle("Dieses Kapitel ist gespielt"), element("p", "", caption),
        actions(button("Weiter", next, "button button-primary")));
    });
  }

  function riskText(facts, plan) {
    const focus = facts.status === "risk" ? facts.weak : facts.base;
    const notes = [];
    if (focus.home?.executed === false) {
      notes.push("Für meinen Hauskauf mit " + focus.home.age + " fehlen " + money(focus.home.missing) + ".");
    }
    if (focus.shortfallMonth >= 0) {
      notes.push(formatAge(focus.shortfallMonth, plan.profile.age) + " fehlen mir erstmals " +
        money(focus.firstShortfall) + " für fällige Zahlungen.");
    }
    if (!notes.length) return "Mein Plan deckt die erfassten Ausgaben auch im getesteten schwachen Renditepfad.";
    return (facts.status === "risk" ? "Bei schwachen Renditen wird es eng. " : "") + notes.join(" ");
  }

  function alternativeOutcome(item, original) {
    const gain = item.assessment.base.minimum - original.base.minimum;
    const descriptions = [];
    if (item.assessment.base.home && !original.base.home?.executed && item.assessment.base.home.executed) {
      descriptions.push("Der Hauskauf ist im Basispfad finanzierbar.");
    }
    if (original.base.shortfallMonth >= 0 && item.assessment.base.shortfallMonth < 0) {
      descriptions.push("Die Finanzierungslücke im Basispfad entfällt.");
    }
    if (item.assessment.base.home?.executed === false) {
      descriptions.push("Für den Hauskauf fehlen im Basispfad noch " + money(item.assessment.base.home.missing) + ".");
    }
    if (item.assessment.base.shortfallMonth >= 0) {
      descriptions.push("Im Basispfad bleibt eine Lücke bei den fälligen Zahlungen.");
    }
    if (original.weak.home?.executed === false && item.assessment.weak.home?.executed === true) {
      descriptions.push("Der Hauskauf klappt auch im schwachen Renditepfad.");
    } else if (item.assessment.weak.home?.executed === false && item.assessment.base.home?.executed === true) {
      descriptions.push("Bei schwacher Rendite fehlen für den Hauskauf " + money(item.assessment.weak.home.missing) + ".");
    }
    if (original.weak.shortfallMonth >= 0 && item.assessment.weak.shortfallMonth < 0) {
      descriptions.push("Die Zahlungslücke bei schwacher Rendite entfällt.");
    } else if (item.assessment.weak.shortfallMonth >= 0 && item.assessment.base.shortfallMonth < 0) {
      descriptions.push("Bei schwacher Rendite bleibt eine Lücke bei den fälligen Zahlungen.");
    }
    if (Math.abs(gain) >= 1) descriptions.push("Tiefster Kontostand " + (gain > 0 ? "+" : "−") + money(Math.abs(gain)) + ".");
    return descriptions.join(" ") || "Der schwache Renditepfad hat weniger Finanzierungslücken.";
  }

  function planWith(item) {
    return { ...scenario, events: scenario.events.map((event) => event.id === item.event.id ? item.event : event) };
  }

  function playAlternative(item) {
    if (!baseline) baseline = scenario;
    scenario = planWith(item);
    const chapterIndex = item.event.id - 101;
    if (decisions[chapterIndex]) decisions[chapterIndex] = {
      ...decisions[chapterIndex], age: item.event.age, event: item.event,
    };
    playScene(item.event.type, item.event.age, item.event.age, item.title, item.event, showReview);
  }

  function showReview() {
    review = true;
    returnToReview = false;
    renderChapters();
    const facts = story.assess(scenario);
    const titles = { difficult: "Mein Plan hat eine Finanzierungslücke", risk: "Mein Plan ist anfällig",
      feasible: "Mein Plan trägt im Modell" };
    heading("Dein älteres Ich", "Schau zurück auf deine Entscheidungen und probiere eine andere Zukunft aus.");
    const age = scenario.endAge;
    readDraft = null;
    const name = scenario.profile.name || "Dein Zwilling";
    scene.show(storyScene("review", age));
    banner(name + " blickt zurück", age, "Dein Rückblick", riskText(facts, scenario));
    showStats([
      ["Tiefster Kontostand im Basispfad", money(facts.base.minimum)],
      ["Nettovermögen in heutiger Kaufkraft", money(facts.base.realNet)],
      ["Heutige Kaufkraft bei schwacher Rendite", money(facts.weak.realNet)],
    ]);

    const note = element("div", "review-note");
    note.dataset.status = facts.status;
    note.append(element("strong", "", titles[facts.status]), element("p", "", riskText(facts, scenario)));
    const form = element("form", "priority-form");
    const question = element("label", "", "Was möchtest du auf jeden Fall beibehalten?");
    question.htmlFor = "game-priority";
    const select = element("select");
    select.id = "game-priority";
    select.required = true;
    const choices = { family: ["children"], break: ["gap"], marriage: ["marriage"], home: ["home"],
      education: ["study", "apprentice"], retirement: ["retire"] };
    const selectHint = element("option", "", "Priorität wählen");
    selectHint.value = "";
    select.append(selectHint);
    for (const [key, label] of Object.entries(story.PRIORITIES)) {
      if (key !== "buffer" && !scenario.events.some((event) => choices[key].includes(event.type))) continue;
      const option = element("option", "", label);
      option.value = key;
      select.append(option);
    }
    select.value = priority || coach.priority();
    priority = select.value;
    const suggest = element("button", "button button-primary", "Alternativen berechnen");
    suggest.type = "submit";
    form.append(question, select, suggest);
    const list = element("div", "alternative-list");
    function suggestions() {
      const items = story.alternatives(scenario, priority, facts);
      if (!items.length) {
        list.replaceChildren(element("p", "", "Unter dieser Priorität verbessert keine der getesteten Einzeländerungen den Finanzplan. Du kannst ein Kapitel bearbeiten und weitere Kombinationen ausprobieren."));
        return;
      }
      list.replaceChildren(...items.map((item) => {
        const card = element("article", "alternative");
        card.append(element("strong", "", item.title), element("p", "", item.detail),
          element("p", "", alternativeOutcome(item, facts)),
          actions(button("Im Diagramm vergleichen", () => openDashboard(planWith(item), scenario), "text-button"),
            button("Alternative spielen", () => playAlternative(item), "text-button")));
        return card;
      }));
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      priority = select.value;
      suggestions();
    });
    const history = element("details", "review-history");
    const historyList = element("ul");
    for (const event of [...scenario.events].sort((a, b) => a.age - b.age)) {
      historyList.append(element("li", "", event.age + " Jahre · " + dashboard.eventTypes[event.type].label));
    }
    history.append(element("summary", "", "Deine Entscheidungen"), historyList);
    const chartActions = actions(button("Statistiken ansehen", () => openDashboard(), "button button-secondary"),
      button("Entscheidung erneut spielen", () => {
        const homeChapter = decisions.findIndex((item) => item.event?.type === "home");
        index = homeChapter >= 0 ? homeChapter : decisions.length - 1;
        returnToReview = true;
        review = false;
        renderChapter();
      }, "text-button"));
    panel.replaceChildren(sectionTitle("Was ist dir wichtig?"), note, chartActions, form, list, history,
      button("Mit deinem Zwilling sprechen", () => $("coach-jump").click(), "text-button"),
      button("Neues Leben spielen", reset, "text-button"));
    if (select.value) suggestions();
    visitCoach("review", "Rückblick", age);
  }

  function openDashboard(alternate = null, alternateBaseline = null) {
    if (playing) return;
    previewing = Boolean(alternate);
    $("game-view").hidden = true;
    $("dashboard-view").hidden = false;
    if (scenario) dashboard.load(alternate ?? scenario, alternateBaseline ?? baseline);
    else dashboard.load(dashboard.read());
    root.scrollTo(0, 0);
  }

  $("back-to-game").addEventListener("click", () => {
    const compared = previewing;
    previewing = false;
    if (scenario && !compared) {
      scenario = dashboard.read();
      for (let chapter = 0; chapter < decisions.length; chapter += 1) {
        const event = scenario.events.find((item) => item.id === chapter + 101);
        if (event) decisions[chapter] = { ...decisions[chapter], age: event.age, event };
        else decisions[chapter] = { ...decisions[chapter], event: null };
      }
    }
    $("dashboard-view").hidden = true;
    $("game-view").hidden = false;
    if (scenario && !compared) {
      if (review) showReview();
      else renderChapter();
    } else if (!scenario) showAvatar();
    root.scrollTo(0, 0);
  });

  $("open-dashboard").addEventListener("click", () => openDashboard());
  $("skip-animation").addEventListener("click", scene.skip);
  avatarForm.addEventListener("input", showAvatar);
  avatarForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(avatarForm);
    const profile = { name: data.get("name").trim(), education: data.get("education") };
    for (const key of ["age", "cash", "portfolio", "income", "expenses"]) profile[key] = Number(data.get(key));
    start(profile);
  });
  $("alexia-demo").addEventListener("click", () => start({ ...story.DEMO }));
  showAvatar();
})(globalThis);
