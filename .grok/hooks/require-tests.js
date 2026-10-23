#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

function allow() {
  process.exit(0);
}

function block(reason) {
  process.stdout.write(JSON.stringify({ decision: "block", reason }));
  process.exit(0);
}

let raw = "";
try {
  raw = fs.readFileSync(0, "utf8");
} catch (_e) {
  raw = "";
}

let event = {};
try {
  event = raw.trim() ? JSON.parse(raw) : {};
} catch (_e) {
  event = {};
}

if (event.reason && event.reason !== "end_turn") allow();
if (event.stopHookActive) allow();

const root = process.cwd();
const commandFile = path.join(root, ".grok", "check-command.txt");
if (!fs.existsSync(commandFile)) allow();

const line = fs.readFileSync(commandFile, "utf8").split(/\r?\n/).find((l) => l.trim());
if (!line || line.trim().startsWith("#")) allow();

const result = spawnSync(line.trim(), {
  cwd: root,
  shell: true,
  encoding: "utf8",
  timeout: 540000,
});

if (result.error) {
  block(`Команда проверки не запустилась: ${result.error.message}`);
}
if (result.status !== 0) {
  const tail = `${result.stdout || ""}\n${result.stderr || ""}`.trim().slice(-1200);
  block(`Команда проверки завершилась с кодом ${result.status}.\n${tail}`);
}
allow();
