"use strict";

const http = require("node:http");
const { readFile } = require("node:fs/promises");
const { join } = require("node:path");
const { execFile } = require("node:child_process");

const host = "127.0.0.1";
const port = 8765;
const entry = ["index.html", "text/html"];
const assets = new Map([
  ["/", entry],
  ["/index.html", entry],
  ["/styles.css", ["styles.css", "text/css"]],
  ...["model", "chart", "timeline", "app"].map((name) =>
    ["/" + name + ".js", [name + ".js", "text/javascript"]]),
]);

const server = http.createServer(async (request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" }).end();
    return;
  }
  const asset = assets.get((request.url || "").split("?")[0]);
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
