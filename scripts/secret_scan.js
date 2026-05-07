const fs = require("fs");
const path = require("path");

const rootDir = path.resolve(__dirname, "..");
const rawArgs = process.argv.slice(2);
const mode = rawArgs.includes("--staged") ? "staged" : "repo";
const cliFiles = rawArgs.filter((arg) => !arg.startsWith("--"));

const allowList = new Set([
  ".env.example",
]);

const ignoredDirectories = new Set([
  ".git",
  ".claude",
  "node_modules",
]);

const blockedFiles = new Set([
  ".env",
]);

const repoWalkIgnoredFiles = new Set([
  ".env",
]);

const textExtensions = new Set([
  ".js",
  ".json",
  ".md",
  ".txt",
  ".tex",
  ".bib",
  ".py",
  ".sql",
  ".yml",
  ".yaml",
  ".toml",
  ".ini",
  ".cfg",
  ".ps1",
  ".sh",
  ".gitignore",
]);

const secretPatterns = [
  { name: "GitHub PAT", regex: /\bgh[pousr]_[A-Za-z0-9_]{20,}\b/g },
  { name: "Google API key", regex: /\bAIza[0-9A-Za-z\-_]{20,}\b/g },
  { name: "Tavily API key", regex: /\btvly-[A-Za-z0-9\-_]+\b/g },
  { name: "Browserbase live key", regex: /\bbb_live_[A-Za-z0-9\-_]+\b/g },
  { name: "Supabase publishable key", regex: /\bsb_publishable_[A-Za-z0-9_\-]+\b/g },
  { name: "JWT token", regex: /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g },
  { name: "Postgres URL", regex: /\bpostgres(?:ql)?:\/\/[^\s"'`]+/g },
  { name: "Telegram bot token", regex: /\b\d{8,10}:[A-Za-z0-9_-]{30,}\b/g },
];

const files = mode === "staged" ? cliFiles : walkRepo(rootDir);
const findings = [];

for (const relativePath of files) {
  if (!relativePath) continue;
  const normalizedPath = normalizeRelative(relativePath);
  if (allowList.has(normalizedPath)) continue;
  if (blockedFiles.has(normalizedPath)) {
    findings.push({
      file: normalizedPath,
      line: 1,
      type: "Blocked file",
      match: "Tracked secret file should not be committed",
    });
    continue;
  }
  if (!looksTextLike(normalizedPath)) continue;

  const absolutePath = path.join(rootDir, normalizedPath);
  if (!fs.existsSync(absolutePath)) continue;
  if (!fs.statSync(absolutePath).isFile()) continue;

  const content = fs.readFileSync(absolutePath, "utf8");
  if (content.includes("\u0000")) continue;

  for (const pattern of secretPatterns) {
    for (const match of content.matchAll(pattern.regex)) {
      const index = match.index ?? 0;
      findings.push({
        file: normalizedPath,
        line: countLines(content, index),
        type: pattern.name,
        match: redact(match[0]),
      });
    }
  }
}

if (findings.length) {
  console.error("Secret scan failed. Review these findings:");
  for (const finding of findings) {
    console.error(`- ${finding.file}:${finding.line} ${finding.type} -> ${finding.match}`);
  }
  process.exit(1);
}

const scopeLabel = mode === "staged" ? "staged file(s)" : "repo file(s)";
console.log(`Secret scan passed for ${files.length} ${scopeLabel}.`);

function walkRepo(directory, prefix = "") {
  const entries = fs.readdirSync(directory, { withFileTypes: true });
  const found = [];
  for (const entry of entries) {
    if (ignoredDirectories.has(entry.name)) continue;
    if (repoWalkIgnoredFiles.has(entry.name)) continue;
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      found.push(...walkRepo(absolutePath, relativePath));
    } else if (entry.isFile()) {
      found.push(relativePath);
    }
  }
  return found;
}

function normalizeRelative(value) {
  return value.replace(/\\/g, "/").replace(/^\.\//, "");
}

function looksTextLike(relativePath) {
  const base = path.basename(relativePath);
  if (textExtensions.has(base)) return true;
  return textExtensions.has(path.extname(relativePath).toLowerCase());
}

function countLines(content, index) {
  let lines = 1;
  for (let i = 0; i < index; i += 1) {
    if (content[i] === "\n") lines += 1;
  }
  return lines;
}

function redact(value) {
  if (value.length <= 12) return "[redacted]";
  return `${value.slice(0, 4)}...${value.slice(-4)}`;
}
