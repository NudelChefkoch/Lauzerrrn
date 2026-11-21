"use strict";

const http = require("node:http");
const { readFile } = require("node:fs/promises");
const { join } = require("node:path");
const { execFile } = require("node:child_process");
const agent = require("./agent.cjs");
const dialog = require("./dialog.cjs");

const host = "127.0.0.1";
const port = 8765;
const entry = ["index.html", "text/html"];
const assets = new Map([
  ["/", entry],
  ["/index.html", entry],
  ["/styles.css", ["styles.css", "text/css"]],
  ["/game.css", ["game.css", "text/css"]],
  ...["model", "chart", "timeline", "app", "story", "scenes", "coach", "game"].map((name) =>
    ["/" + name + ".js", [name + ".js", "text/javascript"]]),
]);

const server = http.createServer(async (request, response) => {
  const path = (request.url || "").split("?")[0];
  if (path === "/api/twin/status" && request.method === "GET") {
    json(response, 200, await agent.status());
    return;
  }
  if (["/api/twin", "/api/twin/dialog"].includes(path) && request.method === "POST") {
    if (request.headers.origin && request.headers.origin !== "http://" + host + ":" + server.address().port) {
      json(response, 403, { error: "Öffne diese Seite über den lokalen Starter." });
      return;
    }
    const controller = new AbortController();
    response.once("close", () => {
      if (!response.writableEnded) controller.abort();
    });
    try {
      const chunks = [];
      let length = 0;
      for await (const chunk of request) {
        length += chunk.length;
        if (length > 65536) {
          json(response, 413, { error: "Anfrage zu gross." });
          return;
        }
        chunks.push(chunk);
      }
      const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const result = path === "/api/twin/dialog" ? await dialog.reply(payload, { signal: controller.signal }) :
        await agent.answer(payload);
      if (response.destroyed) return;
      const { status, ...body } = result;
      json(response, status, body);
    } catch {
      if (!response.destroyed) json(response, 400, { error: "Ungültige Anfrage." });
    }
    return;
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" }).end();
    return;
  }
  const asset = assets.get(path);
  if (!asset) {
    response.writeHead(404).end();
    return;
  }
  const [file, contentType] = asset;
  try {
    const content = await readFile(join(__dirname, file));
    response.writeHead(200, {
      "Content-Type": contentType + "; charset=utf-8",
      "Content-Length": content.length,
      "Cache-Control": "no-store",
    });
    response.end(request.method === "HEAD" ? undefined : content);
  } catch (error) {
    console.error("Datei konnte nicht gelesen werden:", file, error.message);
    response.writeHead(500).end();
  }
});

function json(response, status, content) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(JSON.stringify(content));
}

let requestedPort = port;
server.on("error", (error) => {
  if (error.code === "EADDRINUSE" && requestedPort === port) {
    requestedPort = 0;
    server.listen(requestedPort, host);
    return;
  }
  console.error("Der lokale Server konnte nicht starten:", error.message);
  process.exitCode = 1;
});

server.on("listening", () => {
  const url = "http://" + host + ":" + server.address().port + "/";
  console.log("Financial Twin " + url);
  console.log("Das Fenster beim Verwenden geoeffnet lassen. Beenden mit Strg+C.");
  if (process.platform === "win32" && process.argv.includes("--open")) {
    execFile("powershell.exe", ["-NoProfile", "-Command", "Start-Process '" + url + "'"],
      { windowsHide: true }, (error) => {
        if (error) console.log("Bitte die obige Adresse in der Browser-Adresszeile oeffnen.");
      });
  }
});

server.listen(requestedPort, host);
