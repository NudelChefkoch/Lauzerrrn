(function (root) {
  "use strict";

  const PROMPTS = {
    Berufseinstieg: ["Reicht mein Budget während der Ausbildung?", "Wie gross ist mein Puffer?"],
    Auszeit: ["Reicht mein Geld für die Auszeit?", "Was wäre mit 3 Monaten Auszeit?"],
    Partnerschaft: ["Wie wirkt sich die Hochzeit auf mein Budget aus?", "Was bleibt mir als Puffer?"],
    Familie: ["Reicht mein Budget während der Elternzeit?", "Was wäre mit 6 Monaten Elternzeit?"],
    Wohnen: ["Kann ich den Hauskauf finanzieren?", "Welche Alternative hätte ich?"],
    Rente: ["Reicht mein Einkommen in der Rente?", "Was ändert der monatliche Sparplan?"],
    Rückblick: ["Wo wird mein Plan eng?", "Welche Alternative respektiert meine Priorität?"],
  };

  function create({ snapshot, compare }) {
    const $ = (id) => document.getElementById(id);
    const panel = $("coach-panel");
    const conversation = $("coach-conversation");
    const thread = $("coach-thread");
    const textarea = $("coach-message");
    const send = $("coach-send");
    const prompts = $("coach-prompts");
    const progress = $("coach-progress");
    let current;
    let pending;
    let history = [];
    let openings = new Set();
    let preference = "";

    function node(tag, className, text) {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text) element.textContent = text;
      return element;
    }

    function button(text, callback, className) {
      const element = node("button", className, text);
      element.type = "button";
      element.addEventListener("click", callback);
      return element;
    }

    function append(role, stage, text, question, insight) {
      const entry = node("li", "coach-turn coach-turn-" + role);
      entry.dataset.role = role;
      const bubble = node("div", "coach-bubble");
      bubble.append(node("span", "coach-stage", role === "user" ? "Du" : stage),
        node("p", "", text));
      if (question) bubble.append(node("p", "coach-question", question));
      if (insight) {
        const block = node("div", "coach-insight");
        block.append(node("strong", "", insight.title));
        for (const line of insight.lines) block.append(node("p", "", line));
        if (insight.compare) {
          block.append(button("Im Dashboard vergleichen", () => compare(insight.compare), "text-button"));
        }
        bubble.append(block);
      }
      entry.append(bubble);
      thread.append(entry);
      thread.scrollTop = thread.scrollHeight;
      return bubble;
    }

    function setExpanded(expanded) {
      conversation.hidden = !expanded;
      $("coach-toggle").setAttribute("aria-expanded", String(expanded));
      $("coach-toggle").textContent = expanded ? "Einklappen" : "Ausklappen";
    }

    function updateBusy() {
      const sending = pending && !pending.opening;
      send.disabled = Boolean(sending);
      for (const action of prompts.children) action.disabled = Boolean(sending);
      progress.hidden = !pending;
      if (pending) progress.textContent = "Dein Zwilling prüft deine Angaben …";
    }

    function cancelOpening() {
      if (!pending?.opening) return;
      pending.controller.abort();
      pending = null;
    }

    function openForStage() {
      if (!current || pending || openings.has(current.key)) return;
      openings.add(current.key);
      void request(true);
    }

    async function request(opening) {
      const context = snapshot();
      if (!current || !context || pending) return;
      const task = { controller: new AbortController(), opening, stage: current.stage };
      pending = task;
      updateBusy();
      try {
        const response = await fetch("/api/twin/dialog", {
          method: "POST", headers: { "Content-Type": "application/json" }, signal: task.controller.signal,
          body: JSON.stringify({ ...context, preference, opening,
            history: history.slice(-10) }),
        });
        const reply = await response.json();
        if (!response.ok) throw new Error(reply.error);
        if (task.controller.signal.aborted || pending !== task) return;
        if (!opening) preference = reply.priority || preference;
        $("coach-state").textContent = reply.source === "simulation" ?
          "Hinweis aus der Simulation" : "Lokales Modell · " + reply.source;
        append("assistant", task.stage, reply.tip, reply.question, reply.insight);
        history.push({ role: "assistant", stage: task.stage, content: reply.tip + " " + reply.question });
      } catch {
        if (task.controller.signal.aborted || pending !== task) return;
        $("coach-state").textContent = "Verbindung zum Chat unterbrochen";
        const notice = append("assistant", task.stage, "Die Nachricht konnte gerade nicht verarbeitet werden.");
        notice.append(button("Erneut versuchen", () => {
          if (pending) return;
          if (!opening && history.at(-1)?.role !== "user") return;
          notice.parentElement.remove();
          void request(opening);
        }, "text-button"));
      } finally {
        if (pending === task) {
          pending = null;
          updateBusy();
          openForStage();
        }
      }
    }

    function submit(text) {
      const content = text.trim();
      if (!content || !current || pending && !pending.opening) return;
      cancelOpening();
      openings.add(current.key);
      history.push({ role: "user", stage: current.stage, content });
      append("user", current.stage, content);
      textarea.value = "";
      void request(false);
    }

    $("coach-form").addEventListener("submit", (event) => {
      event.preventDefault();
      submit(textarea.value);
    });
    textarea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        submit(textarea.value);
      }
    });
    $("coach-toggle").addEventListener("click", () => setExpanded(conversation.hidden));
    $("coach-jump").addEventListener("click", () => {
      setExpanded(true);
      panel.scrollIntoView({ block: "start", behavior: "auto" });
      textarea.focus({ preventScroll: true });
    });

    return {
      visit(key, stage, name) {
        panel.hidden = false;
        $("coach-jump").hidden = false;
        $("coach-title").textContent = name ? "Chat mit " + name : "Zwilling-Chat";
        $("coach-initial").textContent = name ? Array.from(name)[0]?.toUpperCase() || "Z" : "Z";
        if (current?.key === key) return;
        cancelOpening();
        current = { key, stage };
        prompts.replaceChildren(...PROMPTS[stage].map((text) => button(text, () => submit(text))));
        updateBusy();
        openForStage();
      },
      priority() { return preference; },
      reset() {
        pending?.controller.abort();
        current = pending = null;
        history = [];
        openings = new Set();
        preference = "";
        thread.replaceChildren();
        prompts.replaceChildren();
        textarea.value = "";
        panel.hidden = true;
        $("coach-jump").hidden = true;
        $("coach-state").textContent = "Ich schaue mir deinen Lebensweg an.";
        setExpanded(true);
        updateBusy();
      },
    };
  }

  root.TwinCoach = { create };
})(globalThis);
