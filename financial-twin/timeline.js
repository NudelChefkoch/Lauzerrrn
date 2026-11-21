(function (root) {
  "use strict";

  function createTimeline({ add, edit, move, formatAge, money, percent }) {
    const $ = (id) => document.getElementById(id);
    const track = $("timeline-track");
    const scroll = $("timeline-scroll");
    const cursor = $("timeline-cursor");
    const marks = $("event-list");
    const outside = $("outside-events");
    let data;
    let selected = 0;
    let drag = null;
    let trackWidth = 0;
    let buttons = new Map();

    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    const years = () => data.endAge - data.startAge;
    const monthForAge = (age) => (age - data.startAge) * 12;
    const position = (month) => (month / (years() * 12) * 100) + "%";
    const boundedAge = (age) => clamp(age, data.startAge, data.endAge - 1);

    function inspect(month, announce = false) {
      selected = clamp(month, 0, years() * 12 - 1);
      const budget = data.points[selected + 1];
      const age = formatAge(selected, data.startAge);
      const growth = budget.salaryGrowth === null ? "–" : percent(budget.salaryGrowth);
      cursor.style.setProperty("--position", position(selected));
      cursor.hidden = false;
      $("timeline-age").textContent = age;
      $("timeline-income").textContent = money(budget.income);
      $("timeline-expenses").textContent = money(budget.expenses);
      $("timeline-growth").textContent = growth;
      $("timeline-one-off").textContent = money(budget.oneOff);
      $("timeline-one-off-row").hidden = budget.oneOff <= 0;
      if (announce) {
        $("timeline-announcement").textContent = age + ". Nettoeinkommen " + money(budget.income) +
          ", laufende Ausgaben " + money(budget.expenses) + " pro Monat. Gehaltswachstum " + growth + ".";
      }
    }

    function pointerMonth(event) {
      const rect = track.getBoundingClientRect();
      return clamp(Math.round((event.clientX - rect.left) / rect.width * years() * 12), 0, years() * 12 - 1);
    }

    function pin(event, year, isOnTrack) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "event-pin";
      button.dataset.eventId = event.id;
      if (event.warning) button.dataset.warning = "";
      button.append(event.label);
      button.append(year);
      buttons.set(event.id, button);

      function label(age) {
        year.textContent = age;
        const description = [event.label, "mit " + age + " Jahren", event.detail, event.warning]
          .filter(Boolean).join(" · ");
        button.title = description;
        button.setAttribute("aria-label", description);
      }
      label(event.age);
      let suppressClick = false;
      button.addEventListener("click", (click) => {
        click.stopPropagation();
        if (!suppressClick) edit(event.id);
      });
      if (!isOnTrack) return button;

      button.addEventListener("focus", () => inspect(monthForAge(event.age), true));
      button.addEventListener("keydown", (key) => {
        const step = { ArrowLeft: -1, ArrowRight: 1 }[key.key];
        if (!step) return;
        key.preventDefault();
        key.stopPropagation();
        const age = boundedAge(event.age + step);
        if (age !== event.age) move(event.id, age);
      });
      button.addEventListener("pointerdown", (pointer) => {
        if (pointer.button !== 0 || drag) return;
        drag = { id: pointer.pointerId, x: pointer.clientX, scroll: scroll.scrollLeft, age: event.age, moved: false };
        suppressClick = false;
        button.setPointerCapture(pointer.pointerId);
      });
      button.addEventListener("pointermove", (pointer) => {
        if (drag?.id !== pointer.pointerId) return;
        if (!drag.moved && Math.abs(pointer.clientX - drag.x) < 5) return;
        drag.moved = true;
        const bounds = scroll.getBoundingClientRect();
        if (pointer.clientX > bounds.right - 24) scroll.scrollLeft += 18;
        if (pointer.clientX < bounds.left + 24) scroll.scrollLeft -= 18;
        const delta = pointer.clientX - drag.x + scroll.scrollLeft - drag.scroll;
        drag.age = boundedAge(event.age + Math.round(delta / track.clientWidth * years()));
        button.parentElement.classList.add("is-dragging");
        button.parentElement.style.setProperty("--position", position(monthForAge(drag.age)));
        label(drag.age);
        inspect(monthForAge(drag.age));
      });

      function endDrag(pointer, commit) {
        if (drag?.id !== pointer.pointerId) return;
        const { moved, age } = drag;
        drag = null;
        if (!moved) return;
        suppressClick = true;
        setTimeout(() => { suppressClick = false; }, 0);
        button.parentElement.classList.remove("is-dragging");
        button.parentElement.style.setProperty("--position", position(monthForAge(event.age)));
        label(event.age);
        inspect(monthForAge(event.age));
        if (commit && age !== event.age) move(event.id, age);
      }
      button.addEventListener("pointerup", (pointer) => endDrag(pointer, true));
      button.addEventListener("lostpointercapture", (pointer) => endDrag(pointer, false));
      return button;
    }

    function layout() {
      trackWidth = track.clientWidth;
      const lanes = [];
      for (const marker of marks.children) {
        const x = Number(marker.dataset.fraction) * trackWidth;
        const openLane = lanes.findIndex((previous) => x - previous >= 132);
        const lane = openLane === -1 ? lanes.length : openLane;
        lanes[lane] = x;
        marker.style.setProperty("--lane", lane);
      }
      track.style.setProperty("--lanes", Math.max(lanes.length, 1));
    }

    track.addEventListener("pointermove", (event) => {
      if (data && !drag && event.pointerType !== "touch") inspect(pointerMonth(event));
    });
    track.addEventListener("click", (event) => {
      if (!data || drag || event.target.closest(".event-pin")) return;
      const month = pointerMonth(event);
      inspect(month);
      add(boundedAge(data.startAge + Math.round(month / 12)));
    });
    track.addEventListener("focus", () => { if (data) inspect(selected, true); });
    track.addEventListener("keydown", (event) => {
      if (!data || event.target !== track) return;
      const step = event.shiftKey ? 12 : 1;
      const month = { ArrowLeft: selected - step, ArrowRight: selected + step,
        Home: 0, End: years() * 12 - 1 }[event.key];
      if (month !== undefined) {
        event.preventDefault();
        inspect(month, true);
      }
      if (event.key === "Enter") {
        event.preventDefault();
        add(boundedAge(data.startAge + Math.round(selected / 12)));
      }
    });
    new ResizeObserver(() => { if (trackWidth !== track.clientWidth) layout(); }).observe(track);

    return {
      update(next) {
        if (data && data.startAge !== next.startAge) selected = 0;
        data = next;
        buttons = new Map();
        const current = [];
        const pastHorizon = [];
        for (const event of data.events) {
          const onTrack = event.age < data.endAge;
          const year = document.createElement("strong");
          const button = pin(event, year, onTrack);
          if (onTrack) {
            const marker = document.createElement("li");
            const month = monthForAge(event.age);
            marker.className = "timeline-marker";
            marker.dataset.fraction = month / (years() * 12);
            marker.style.setProperty("--position", position(month));
            marker.append(button);
            current.push(marker);
          } else {
            pastHorizon.push(button);
          }
        }
        marks.replaceChildren(...current);
        outside.replaceChildren(...pastHorizon);
        $("timeline-outside").hidden = pastHorizon.length === 0;
        const intervals = Math.min(4, years());
        const ticks = Array.from({ length: intervals + 1 }, (_, index) => {
          const year = Math.round(years() * index / intervals);
          const label = document.createElement("span");
          label.textContent = index === 0 ? "Heute · " + data.startAge : (data.startAge + year) + " J.";
          label.style.left = position(year * 12);
          return label;
        });
        $("timeline-ticks").replaceChildren(...ticks);
        layout();
        inspect(selected);
      },

      focusEvent(id) { buttons.get(id)?.focus(); },
    };
  }

  root.createTimeline = createTimeline;
})(globalThis);
