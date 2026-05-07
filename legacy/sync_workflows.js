/**
 * sync_workflows.js
 * Exports the live EL + EL Error Handler workflows from n8n to local JSON files.
 * Run once to sync repo with n8n state: node sync_workflows.js
 */
const fs = require("fs");
const path = require("path");

loadDotEnv();

const N8N_URL = requiredEnv("N8N_URL");
const API_KEY = requiredEnv("N8N_SECRET");
const HEADERS = {
  "X-N8N-API-KEY": API_KEY,
  Accept: "application/json",
};

const WORKFLOWS = [
  { id: "298f3JSOE72nhW59", file: "el_workflow.json", label: "EL (main pipeline)" },
  { id: "rE91gItDFzMp368P", file: "el_error_handler.json", label: "EL Error Handler" },
];

async function exportWorkflow({ id, file, label }) {
  const res = await fetch(`${N8N_URL}/api/v1/workflows/${id}`, { headers: HEADERS });
  if (!res.ok) throw new Error(`Failed to fetch ${label}: ${res.status}`);
  const wf = await res.json();
  const omit = [
    "updatedAt",
    "createdAt",
    "shared",
    "versionId",
    "activeVersionId",
    "versionCounter",
    "triggerCount",
    "tags",
    "parentFolder",
    "activeVersion",
  ];
  const clean = Object.fromEntries(Object.entries(wf).filter(([key]) => !omit.includes(key)));
  const outPath = path.join(__dirname, file);
  fs.writeFileSync(outPath, JSON.stringify(clean, null, 2), "utf8");
  console.log(`Synced ${label} -> ${file} (${clean.nodes.length} nodes)`);
}

function loadDotEnv() {
  const envPath = path.join(__dirname, ".env");
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const equalsIndex = trimmed.indexOf("=");
    if (equalsIndex <= 0) continue;
    const key = trimmed.slice(0, equalsIndex).trim();
    const rawValue = trimmed.slice(equalsIndex + 1).trim();
    const value = rawValue.replace(/^['"]|['"]$/g, "");
    if (!(key in process.env)) process.env[key] = value;
  }
}

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

(async () => {
  for (const workflow of WORKFLOWS) await exportWorkflow(workflow);
  console.log("\nDone. Commit el_workflow.json + el_error_handler.json.");
})().catch((error) => {
  console.error("Failed:", error.message);
  process.exit(1);
});
