(function (root) {
  "use strict";

  const width = 800;
  const height = 480;
  const ground = 380;
  const skins = ["#f4c5ad", "#d99469", "#a76646", "#704632"];
  const outfits = ["#b22e42", "#367664", "#304e92", "#c2873f"];
  const palettes = {
    city: ["#efe1d3", "#f5e9dd", "#b0aab0", "#5c5065", "#cdc0ac"],
    work: ["#d4e3e7", "#eef3ec", "#8ca8ac", "#345263", "#b8c8c0"],
    study: ["#ece0c8", "#fbecda", "#c4a392", "#804d4f", "#dbc4a6"],
    apprentice: ["#d4dfd5", "#eae8d8", "#8aab99", "#365855", "#c2c8b3"],
    gap: ["#b7d9de", "#e6eedb", "#67928c", "#315f63", "#d5c39a"],
    marriage: ["#eed7e1", "#fff0e6", "#bc8f9f", "#71415e", "#d9bfb3"],
    children: ["#eedbc2", "#fbebd5", "#caa181", "#7a4e3e", "#dfc6aa"],
    home: ["#dce3cb", "#f8edd5", "#9ca786", "#586750", "#c1c5a5"],
    move: ["#dbd9e9", "#f3e8ed", "#a09bb7", "#51527a", "#c5baca"],
    retire: ["#e8dfcb", "#f8eed6", "#b5a57f", "#605b44", "#d5c6a2"],
    review: ["#d7dfdc", "#efe9d9", "#91a49b", "#456361", "#c4c9b4"],
  };

  function createScene(canvas) {
    const ctx = canvas.getContext("2d");
    const reduced = root.matchMedia("(prefers-reduced-motion: reduce)");
    let frame;
    let content;
    let finish;
    let step = 1;

    function box(color, x, y, w, h, radius = 0) {
      ctx.fillStyle = color;
      if (radius) {
        ctx.beginPath();
        ctx.roundRect(x, y, w, h, radius);
        ctx.fill();
      } else ctx.fillRect(x, y, w, h);
    }

    function circle(color, x, y, radius, ry = radius) {
      ctx.beginPath();
      ctx.ellipse(x, y, radius, ry, 0, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    }

    function shape(color, ...points) {
      ctx.beginPath();
      for (let index = 0; index < points.length; index += 2) ctx.lineTo(points[index], points[index + 1]);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
    }

    function line(color, weight, ...points) {
      ctx.beginPath();
      for (let index = 0; index < points.length; index += 2) ctx.lineTo(points[index], points[index + 1]);
      ctx.strokeStyle = color;
      ctx.lineWidth = weight;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.stroke();
    }

    function building(kind, colors) {
      const [, pale, medium, dark] = colors;
      if (kind === "study") {
        shape(dark, 476, 209, 630, 128, 781, 209);
        shape(pale, 516, 196, 630, 145, 743, 196);
        circle(medium, 630, 178, 12);
        box(pale, 495, 211, 266, 158);
        box(dark, 602, 255, 56, 114, 24);
        for (const x of [509, 557, 684, 731]) {
          box(medium, x, 225, 13, 130, 3);
          box(dark, x - 5, 224, 23, 7, 2);
        }
        for (let index = 0; index < 4; index += 1) box(medium, 489 - index * 7, 352 + 7 * index, 277 + index * 14, 7);
      } else if (kind === "apprentice") {
        box(medium, 444, 189, 306, 187, 8);
        shape(dark, 430, 193, 514, 133, 514, 169, 611, 133, 611, 169, 717, 133, 758, 193);
        box(pale, 473, 219, 129, 156, 5);
        box(dark, 625, 219, 94, 70, 4);
        for (let index = 0; index < 7; index += 1) line(medium, 2, 480, 230 + 19 * index, 596, 230 + 19 * index);
        line(pale, 3, 672, 224, 672, 284);
      } else if (kind === "home" || kind === "children" || kind === "move") {
        const left = kind === "move" ? 482 : 479;
        box(pale, left, 230, 226, 143, 6);
        shape(dark, left - 24, 233, left + 108, 126, left + 246, 233);
        box(medium, left + 155, 160, 25, 66, 3);
        box(medium, left + 25, 260, 75, 58, 4);
        line(pale, 4, left + 62, 265, left + 62, 313);
        line(pale, 4, left + 28, 288, left + 95, 288);
        box(dark, left + 133, 261, 53, 112, 6);
        circle(pale, left + 172, 318, 3);
        box(medium, left + 125, 371, 73, 7, 3);
        if (kind === "children") {
          circle(pale, left + 79, 277, 7);
          line(dark, 2, left + 78, 283, left + 84, 296);
        }
      } else {
        for (const [x, y, w] of [[437, 220, 83], [532, 164, 102], [647, 206, 92], [751, 242, 45]]) {
          box(medium, x, y, w, ground - y, 4);
          for (let row = y + 19; row < ground - 17; row += 23) {
            for (let col = x + 12; col + 12 < x + w; col += 23) box(pale, col, row, 12, 9, 2);
          }
        }
      }
    }

    function landscape(kind, colors) {
      const [, pale, medium, dark, lawn] = colors;
      if (kind === "gap") {
        circle("#f5d590", 608, 132, 51);
        shape(medium, 0, 322, 133, 212, 199, 274, 330, 138, 434, 278, 542, 196, 799, 337, 799, 420, 0, 420);
        shape(pale, 277, 193, 330, 138, 369, 190, 337, 182, 320, 204, 309, 184);
        shape(dark, 0, 349, 154, 287, 239, 335, 390, 277, 551, 356, 673, 297, 800, 366, 800, 413, 0, 413);
        box("#a0bbb4", 0, 360, 800, 40);
        for (const [x, y, w] of [[42, 369, 49], [190, 378, 100], [553, 372, 65], [659, 388, 95]]) {
          line("#caddd0", 2, x, y, x + w, y);
        }
      } else if (kind === "marriage") {
        box(pale, 473, 354, 237, 24, 5);
        ctx.beginPath();
        ctx.moveTo(505, 360); ctx.lineTo(505, 246);
        ctx.bezierCurveTo(505, 143, 676, 143, 676, 246);
        ctx.lineTo(676, 360);
        ctx.lineWidth = 10; ctx.strokeStyle = dark; ctx.stroke();
        for (let index = 0; index < 19; index += 1) {
          const angle = Math.PI + Math.PI * index / 18;
          circle(index % 3 ? pale : medium, 590 + 86 * Math.cos(angle),
            228 + 66 * Math.sin(angle), 8 + index % 5);
        }
        for (const x of [414, 747]) {
          line(dark, 5, x, 365, x, 306);
          for (let i = -2; i <= 2; i += 1) circle(medium, x + i * 8, 305 + i * i * 2, 9);
        }
      } else {
        circle(pale, 643, 116, 49);
        shape(medium, 0, 324, 142, 273, 271, 302, 408, 257, 551, 309, 702, 261, 800, 298, 800, 423, 0, 423);
        shape(lawn, 0, 354, 183, 321, 342, 365, 496, 323, 653, 350, 800, 322, 800, 430, 0, 430);
        box(dark, 527, 317, 157, 15, 4);
        box(medium, 527, 338, 157, 12, 4);
        line(dark, 7, 540, 350, 540, 377);
        line(dark, 7, 673, 350, 673, 377);
      }
    }

    function accessory(kind, after, skin, dark) {
      if (!after && kind !== "gap") return;
      if (kind === "study") {
        shape("#302840", -37, -184, 0, -201, 38, -184, 0, -170);
        line("#efb967", 2, 26, -188, 40, -180, 40, -165);
        box("#fbefd6", 30, -44, 28, 9, 3);
        line("#ad384c", 3, 43, -45, 43, -34);
      }
      if (kind === "apprentice") {
        box("#f1bc61", -29, -180, 58, 11, 4);
        circle("#f1bc61", 0, -180, 24, 13);
        line("#6e745f", 5, 33, -45, 56, -61);
      }
      if (kind === "gap") {
        box("#d79a52", -41, -111, 31, 68, 9);
        line("#654d3c", 4, -22, -110, -20, -66, -8, -55);
      }
      if (kind === "marriage") {
        for (const [x, y] of [[31, -67], [43, -65], [38, -77], [49, -73]]) circle("#f3c2cb", x, y, 7);
        line("#577a56", 4, 30, -46, 42, -70);
      }
      if (kind === "children") {
        line(dark, 5, 28, -57, 51, -54, 68, -30);
        shape("#c08568", 58, -45, 113, -45, 99, -18, 71, -18);
        circle(skin, 92, -44, 9);
        circle(dark, 72, -10, 8);
        circle(dark, 98, -10, 8);
      }
      if (kind === "move" || (kind === "home" && content.funded)) {
        box("#d6a46d", 18, -64, 42, 38, 4);
        line("#f3d5a1", 4, 38, -62, 38, -28);
      }
      if (kind === "home" && !content.funded) {
        box("#f2f0df", 22, -66, 34, 29, 3);
        line("#6a8072", 2, 28, -55, 38, -62, 48, -54, 48, -46, 29, -46, 29, -55);
      }
    }

    function avatar(x, y, age, kind, after, bouncing, appearance = content.avatar, size = 1) {
      const { skin: tone, hair: style, outfit } = appearance;
      const skin = skins[tone] ?? skins[1];
      const clothing = outfits[outfit] ?? outfits[0];
      const gray = age >= 60;
      const hair = gray ? "#c6c1bd" : age >= 44 ? "#6e5857" : age >= 34 ? "#56404b" : "#42313d";
      ctx.save();
      ctx.translate(x, y - bouncing);
      const scale = size * (age >= 62 ? 0.95 : 1);
      ctx.scale(scale, scale);
      circle("rgba(53,44,55,.16)", 0, 2, 48, 11);
      line("#4c4859", 13, -14, -57, -17, -13);
      line("#514b5b", 13, 13, -57, 15, -12);
      box("#34313e", -28, -13, 23, 11, 5);
      box("#34313e", 9, -13, 24, 11, 5);
      if (style === 2) box(hair, -31, -165, 63, 61, 24);
      box(clothing, -30, -114, 60, 65, 16);
      line(clothing, 13, -24, -103, -34, -60);
      line(clothing, 13, 24, -104, 35, -66);
      circle(skin, -35, -56, 7);
      circle(skin, 35, -60, 7);
      box(skin, -8, -124, 16, 18, 5);
      circle(hair, 0, -155, 33, 37);
      circle(skin, 0, -148, 28, 33);
      circle(skin, -27, -147, 5);
      circle(skin, 27, -147, 5);
      shape(hair, -28, -153, -30, -173, -15, -186, 13, -187, 30, -172, 27, -154, 17, -174, -6, -162);
      if (style === 1) {
        for (let i = -2; i <= 2; i += 1) circle(hair, i * 11, -180 + i * i * 2, 11);
      }
      if (age >= 34 && !gray) line("#ada1a0", 2, 14, -179, 20, -175, 25, -167);
      circle("#3d3040", -10, -149, 2.4);
      circle("#3d3040", 10, -149, 2.4);
      line("#734653", 2, -6, -136, 0, -134, 6, -136);
      if (age >= 48) {
        line("#553d49", 1.4, -18, -153, -5, -153, -6, -146, -17, -146, -18, -153, -5, -153, 5, -153,
          18, -153, 17, -146, 6, -146, 5, -153);
      }
      if (gray) {
        line("#95655c", 1, -8, -160, 8, -160);
        line("#95655c", 1, -19, -142, -16, -140);
        line("#95655c", 1, 19, -142, 16, -140);
      }
      accessory(kind, after, skin, "#504251");
      ctx.restore();
    }

    function companions(age, kind, after, x) {
      if (kind === "marriage" && after) {
        avatar(x + 83, 407, age, "city", true, 0, { skin: 2, hair: 0, outfit: 2 }, 0.94);
      }
      let index = 0;
      for (const child of content.children ?? []) {
        const childAge = age - child.age;
        if (childAge < 1 || index >= 3) continue;
        for (let sibling = 0; sibling < child.count && index < 3; sibling += 1) {
          const size = Math.min(0.91, 0.42 + childAge * 0.035);
          avatar(x - 61 - index * 38, 419 + index * 5, childAge, "city", true, 0,
            { skin: content.avatar.skin, hair: (content.avatar.hair + sibling + 1) % 3, outfit: (index + 1) % 4 }, size);
          index += 1;
        }
      }
    }

    function paint() {
      if (!content || !ctx || !canvas.clientWidth) return;
      const ratio = root.devicePixelRatio || 1;
      canvas.width = Math.round(canvas.clientWidth * ratio);
      canvas.height = Math.round(canvas.clientHeight * ratio);
      ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0);
      const kind = content.kind;
      const colors = palettes[kind] ?? palettes.city;
      const [sky, light, medium, dark, lawn] = colors;
      const gradient = ctx.createLinearGradient(0, 0, 0, height);
      gradient.addColorStop(0, sky); gradient.addColorStop(1, light);
      box(gradient, 0, 0, width, height);
      for (const [x, y, size] of [[117, 69, 56], [304, 109, 51], [487, 66, 34]]) {
        circle("rgba(255,255,255,.35)", x, y, size, 10);
        circle("rgba(255,255,255,.28)", x + size * 0.33, y - 10, size * 0.46, 16);
      }
      box(lawn, 0, ground, width, height - ground);
      if (["gap", "marriage", "retire", "review"].includes(kind)) landscape(kind, colors);
      else building(kind, colors);
      shape("rgba(255,248,226,.53)", 0, 422, 208, 403, 576, 387, 690, 400, 800, 431, 800, 480, 0, 480);
      for (const [x, y, h] of [[75, 416, 37], [135, 370, 20], [353, 394, 22], [767, 430, 36]]) {
        line(dark, 3, x, y, x - 4, y - h);
        circle(medium, x - 10, y - h + 7, 12, 5);
        circle(medium, x + 6, y - h + 12, 11, 5);
      }
      const active = step < 1;
      const after = !content.transition || step >= 0.54;
      const x = content.transition ? (after ? 600 - (step - 0.54) * 590 : 184 + step * 805) : 265;
      const age = after ? content.age : content.fromAge;
      const opacity = 1 - Math.max(0, 1 - Math.abs(step - 0.53) / 0.13) * 0.95;
      ctx.globalAlpha = active ? opacity : 1;
      if (after) companions(age, kind, after, x);
      avatar(x, 409, age, kind, after,
        active ? Math.abs(Math.sin(step * 43)) * 5 : 0);
      ctx.globalAlpha = 1;
    }

    function skip() {
      root.cancelAnimationFrame(frame);
      step = 1;
      paint();
      const callback = finish;
      finish = null;
      callback?.();
    }

    new ResizeObserver(paint).observe(canvas);
    return {
      show(next) {
        root.cancelAnimationFrame(frame);
        finish = null;
        content = next;
        step = 1;
        paint();
      },
      play(next, done) {
        root.cancelAnimationFrame(frame);
        content = { ...next, transition: true };
        finish = done;
        if (reduced.matches) { skip(); return; }
        const started = root.performance.now();
        const animate = (time) => {
          step = Math.min(1, (time - started) / 2350);
          paint();
          if (step === 1) skip();
          else frame = root.requestAnimationFrame(animate);
        };
        frame = root.requestAnimationFrame(animate);
      },
      skip,
    };
  }

  root.createLifeScene = createScene;
})(globalThis);
