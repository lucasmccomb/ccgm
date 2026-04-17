#!/usr/bin/env node
// inventory.mjs - Language-aware structural map of a repository.
//
// Reads a repo root (default: cwd) and prints a JSON object to stdout
// describing languages, frameworks, entry points, scripts, existing docs,
// infrastructure, and monorepo structure.
//
// The /onboarding command consumes this JSON. It is intentionally cheap:
// directory walks are bounded by depth, every glob is scoped, binary and
// lock files are skipped. The script never reads file contents beyond the
// set of manifests and config files it explicitly opens.
//
// Usage:
//   node inventory.mjs                    # inventory cwd
//   node inventory.mjs /path/to/repo      # inventory another path
//   node inventory.mjs --pretty           # pretty-print JSON
//
// Exit codes:
//   0 - ok (JSON printed)
//   1 - fatal error (root path missing, etc.)

import { readFileSync, existsSync, statSync, readdirSync } from "node:fs";
import { join, basename, relative, resolve } from "node:path";

// ---------- Config ----------

const MAX_DEPTH = 4;
const IGNORED_DIRS = new Set([
  "node_modules",
  ".git",
  ".next",
  ".nuxt",
  ".svelte-kit",
  ".turbo",
  ".cache",
  ".vercel",
  ".wrangler",
  "dist",
  "build",
  "out",
  "coverage",
  ".venv",
  "venv",
  "__pycache__",
  ".pytest_cache",
  "target",
  "vendor",
  "tmp",
]);

// ---------- CLI ----------

const args = process.argv.slice(2);
const pretty = args.includes("--pretty");
const positional = args.filter((a) => !a.startsWith("--"));
const rootArg = positional[0] || process.cwd();
const ROOT = resolve(rootArg);

if (!existsSync(ROOT) || !statSync(ROOT).isDirectory()) {
  process.stderr.write(`inventory: not a directory: ${ROOT}\n`);
  process.exit(1);
}

// ---------- Helpers ----------

function safeRead(path) {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

function safeJson(path) {
  const raw = safeRead(path);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function exists(rel) {
  return existsSync(join(ROOT, rel));
}

function firstExisting(paths) {
  for (const p of paths) if (exists(p)) return p;
  return null;
}

function listTopLevelDirs() {
  try {
    return readdirSync(ROOT, { withFileTypes: true })
      .filter((d) => d.isDirectory() && !IGNORED_DIRS.has(d.name) && !d.name.startsWith("."))
      .map((d) => d.name)
      .sort();
  } catch {
    return [];
  }
}

function walk(dir, depth, out, filter) {
  if (depth > MAX_DEPTH) return;
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries) {
    if (IGNORED_DIRS.has(e.name)) continue;
    const full = join(dir, e.name);
    if (e.isDirectory()) {
      walk(full, depth + 1, out, filter);
    } else if (e.isFile() && filter(e.name, full)) {
      out.push(relative(ROOT, full));
    }
  }
}

function globFiles(filter) {
  const out = [];
  walk(ROOT, 0, out, filter);
  return out.sort();
}

// ---------- Detection ----------

function detectLanguages() {
  const langs = new Set();
  if (exists("package.json")) langs.add("javascript");
  if (exists("tsconfig.json") || globFiles((n) => n.endsWith(".ts") || n.endsWith(".tsx")).length > 0) {
    langs.add("typescript");
  }
  if (exists("Cargo.toml")) langs.add("rust");
  if (exists("pyproject.toml") || exists("requirements.txt") || exists("setup.py")) langs.add("python");
  if (exists("go.mod")) langs.add("go");
  if (exists("Gemfile")) langs.add("ruby");
  if (exists("composer.json")) langs.add("php");
  if (exists("pom.xml") || exists("build.gradle") || exists("build.gradle.kts")) langs.add("java");
  if (exists("Package.swift")) langs.add("swift");
  if (globFiles((n) => n === "CMakeLists.txt" || n.endsWith(".cpp") || n.endsWith(".cc")).length > 0) {
    langs.add("cpp");
  }
  if (globFiles((n) => n.endsWith(".sh")).length > 0) langs.add("shell");
  return [...langs].sort();
}

function detectFrameworks(pkg) {
  const fw = new Set();
  const deps = { ...(pkg?.dependencies || {}), ...(pkg?.devDependencies || {}) };

  // Build tools
  if (deps["vite"]) fw.add("vite");
  if (deps["webpack"]) fw.add("webpack");
  if (deps["next"]) fw.add("next.js");
  if (deps["nuxt"] || deps["nuxt3"]) fw.add("nuxt");
  if (deps["@remix-run/react"] || deps["@remix-run/node"]) fw.add("remix");
  if (deps["@sveltejs/kit"]) fw.add("sveltekit");
  if (deps["astro"]) fw.add("astro");
  if (deps["@angular/core"]) fw.add("angular");

  // UI
  if (deps["react"]) fw.add("react");
  if (deps["react-dom"]) fw.add("react-dom");
  if (deps["vue"]) fw.add("vue");
  if (deps["svelte"]) fw.add("svelte");
  if (deps["solid-js"]) fw.add("solid");

  // Styling
  if (deps["tailwindcss"]) fw.add("tailwind");
  if (deps["styled-components"]) fw.add("styled-components");

  // Backend / runtimes
  if (deps["express"]) fw.add("express");
  if (deps["fastify"]) fw.add("fastify");
  if (deps["hono"]) fw.add("hono");
  if (deps["wrangler"] || exists("wrangler.toml") || exists("wrangler.jsonc")) fw.add("cloudflare-workers");
  if (deps["@cloudflare/workers-types"]) fw.add("cloudflare-workers");

  // Testing
  if (deps["vitest"]) fw.add("vitest");
  if (deps["jest"]) fw.add("jest");
  if (deps["@playwright/test"] || deps["playwright"]) fw.add("playwright");
  if (deps["cypress"]) fw.add("cypress");

  // Backend-as-a-service
  if (deps["@supabase/supabase-js"] || exists("supabase")) fw.add("supabase");
  if (deps["firebase"] || deps["firebase-admin"]) fw.add("firebase");

  // Chrome extension detection (root, plus common CRX manifest homes)
  const manifestCandidates = ["manifest.json", "public/manifest.json", "static/manifest.json", "src/manifest.json"];
  for (const mp of manifestCandidates) {
    if (!exists(mp)) continue;
    const m = safeJson(join(ROOT, mp));
    if (m && (m.manifest_version || m.background || m.content_scripts)) {
      fw.add("chrome-extension");
      break;
    }
  }

  // Python frameworks
  const reqs = safeRead("requirements.txt") || "";
  const pyproject = safeRead("pyproject.toml") || "";
  const pyBlob = reqs + "\n" + pyproject;
  if (/\bdjango\b/i.test(pyBlob)) fw.add("django");
  if (/\bflask\b/i.test(pyBlob)) fw.add("flask");
  if (/\bfastapi\b/i.test(pyBlob)) fw.add("fastapi");

  return [...fw].sort();
}

function detectPackageManager() {
  if (exists("pnpm-lock.yaml")) return "pnpm";
  if (exists("yarn.lock")) return "yarn";
  if (exists("bun.lockb") || exists("bun.lock")) return "bun";
  if (exists("package-lock.json")) return "npm";
  if (exists("poetry.lock")) return "poetry";
  if (exists("Pipfile.lock")) return "pipenv";
  if (exists("Cargo.lock")) return "cargo";
  if (exists("Gemfile.lock")) return "bundler";
  return null;
}

function detectMonorepo(pkg) {
  const out = { isMonorepo: false, tool: null, workspaces: [] };
  if (pkg?.workspaces) {
    out.isMonorepo = true;
    out.tool = exists("pnpm-workspace.yaml") ? "pnpm" : "npm/yarn";
    const ws = Array.isArray(pkg.workspaces) ? pkg.workspaces : pkg.workspaces.packages || [];
    out.workspaces = ws;
  } else if (exists("pnpm-workspace.yaml")) {
    out.isMonorepo = true;
    out.tool = "pnpm";
    const raw = safeRead("pnpm-workspace.yaml") || "";
    out.workspaces = raw
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.startsWith("- "))
      .map((l) => l.slice(2).replace(/^["']|["']$/g, ""));
  } else if (exists("turbo.json") || exists("nx.json") || exists("lerna.json")) {
    out.isMonorepo = true;
    out.tool = exists("turbo.json") ? "turborepo" : exists("nx.json") ? "nx" : "lerna";
  }
  return out;
}

function detectEntryPoints(pkg) {
  const entries = [];
  // Package-declared entries
  if (pkg?.main) entries.push({ kind: "node-main", path: pkg.main });
  if (pkg?.module) entries.push({ kind: "esm-main", path: pkg.module });
  if (pkg?.bin) {
    if (typeof pkg.bin === "string") entries.push({ kind: "bin", path: pkg.bin });
    else for (const [name, p] of Object.entries(pkg.bin)) entries.push({ kind: `bin:${name}`, path: p });
  }

  // Vite / Next / app shells
  const webEntries = [
    "index.html",
    "src/main.ts",
    "src/main.tsx",
    "src/main.js",
    "src/main.jsx",
    "src/index.ts",
    "src/index.tsx",
    "src/index.js",
    "src/index.jsx",
    "app/page.tsx",
    "app/page.js",
    "pages/index.tsx",
    "pages/index.js",
    "app/layout.tsx",
  ];
  for (const p of webEntries) {
    if (exists(p)) entries.push({ kind: "web", path: p });
  }

  // Chrome extension (root, plus common CRX manifest homes)
  const extManifestCandidates = ["manifest.json", "public/manifest.json", "static/manifest.json", "src/manifest.json"];
  for (const mp of extManifestCandidates) {
    if (!exists(mp)) continue;
    const m = safeJson(join(ROOT, mp));
    if (!m) continue;
    if (m.background?.service_worker) entries.push({ kind: "ext-background", path: m.background.service_worker });
    if (m.background?.scripts) for (const s of m.background.scripts) entries.push({ kind: "ext-background", path: s });
    if (m.content_scripts) {
      for (const cs of m.content_scripts) for (const s of cs.js || []) entries.push({ kind: "ext-content", path: s });
    }
    if (m.action?.default_popup) entries.push({ kind: "ext-popup", path: m.action.default_popup });
    if (m.options_page) entries.push({ kind: "ext-options", path: m.options_page });
    break;
  }

  // Python
  if (exists("manage.py")) entries.push({ kind: "python", path: "manage.py" });
  if (exists("main.py")) entries.push({ kind: "python", path: "main.py" });
  if (exists("app.py")) entries.push({ kind: "python", path: "app.py" });

  // Go
  if (exists("main.go")) entries.push({ kind: "go", path: "main.go" });
  if (exists("cmd")) entries.push({ kind: "go", path: "cmd/" });

  // Rust
  if (exists("src/main.rs")) entries.push({ kind: "rust-bin", path: "src/main.rs" });
  if (exists("src/lib.rs")) entries.push({ kind: "rust-lib", path: "src/lib.rs" });

  return entries;
}

function detectScripts(pkg) {
  const scripts = {};
  if (pkg?.scripts) Object.assign(scripts, pkg.scripts);
  // Makefile targets
  if (exists("Makefile")) {
    const raw = safeRead("Makefile") || "";
    const targets = [...raw.matchAll(/^([a-zA-Z][a-zA-Z0-9_-]*):/gm)].map((m) => m[1]);
    if (targets.length) scripts.__makefile__ = targets;
  }
  return scripts;
}

function detectDocs() {
  const candidates = [
    "README.md",
    "README.rst",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "ARCHITECTURE.md",
    "CLAUDE.md",
    "AGENTS.md",
    "ONBOARDING.md",
    "SETUP.md",
    "docs",
    ".github/CONTRIBUTING.md",
  ];
  const out = [];
  for (const p of candidates) if (exists(p)) out.push(p);
  // Subdocs
  if (exists("docs")) {
    const docFiles = globFiles((n, full) => {
      if (!full.includes(`${ROOT}/docs/`)) return false;
      return n.endsWith(".md") || n.endsWith(".mdx") || n.endsWith(".rst");
    }).slice(0, 20);
    out.push(...docFiles);
  }
  return out;
}

function detectInfrastructure() {
  const infra = [];
  const checks = [
    ["Dockerfile", "docker"],
    ["docker-compose.yml", "docker-compose"],
    ["docker-compose.yaml", "docker-compose"],
    [".dockerignore", "docker"],
    ["wrangler.toml", "cloudflare-workers"],
    ["wrangler.jsonc", "cloudflare-workers"],
    ["vercel.json", "vercel"],
    ["netlify.toml", "netlify"],
    [".github/workflows", "github-actions"],
    [".circleci/config.yml", "circleci"],
    ["fly.toml", "fly.io"],
    ["render.yaml", "render"],
    ["supabase", "supabase"],
    ["terraform", "terraform"],
    ["Procfile", "heroku"],
    [".husky", "husky"],
  ];
  for (const [p, label] of checks) if (exists(p)) infra.push(label);
  return [...new Set(infra)].sort();
}

function detectTestRunners(pkg) {
  const runners = [];
  const deps = { ...(pkg?.dependencies || {}), ...(pkg?.devDependencies || {}) };
  if (deps.vitest) runners.push("vitest");
  if (deps.jest) runners.push("jest");
  if (deps.mocha) runners.push("mocha");
  if (deps.ava) runners.push("ava");
  if (deps["@playwright/test"] || deps.playwright) runners.push("playwright");
  if (deps.cypress) runners.push("cypress");
  if (exists("pytest.ini") || /\bpytest\b/.test(safeRead("pyproject.toml") || "")) runners.push("pytest");
  if (exists(".rspec") || exists("spec")) runners.push("rspec");
  if (exists("go.mod")) runners.push("go test");
  if (exists("Cargo.toml")) runners.push("cargo test");
  return [...new Set(runners)];
}

// ---------- Build inventory ----------

const pkg = safeJson(join(ROOT, "package.json"));
const topLevelDirs = listTopLevelDirs();
const languages = detectLanguages();
const frameworks = detectFrameworks(pkg);
const packageManager = detectPackageManager();
const monorepo = detectMonorepo(pkg);
const entryPoints = detectEntryPoints(pkg);
const scripts = detectScripts(pkg);
const docs = detectDocs();
const infrastructure = detectInfrastructure();
const testRunners = detectTestRunners(pkg);

const manifestName = pkg?.name || basename(ROOT);

const envExample = firstExisting([".env.example", ".env.template", ".env.sample"]);
const nodeVersionFile = firstExisting([".nvmrc", ".node-version"]);
const pythonVersionFile = firstExisting([".python-version"]);

const inventory = {
  root: ROOT,
  name: manifestName,
  description: pkg?.description || null,
  languages,
  frameworks,
  packageManager,
  nodeVersion: nodeVersionFile ? (safeRead(join(ROOT, nodeVersionFile)) || "").trim() : null,
  pythonVersion: pythonVersionFile ? (safeRead(join(ROOT, pythonVersionFile)) || "").trim() : null,
  monorepo,
  entryPoints,
  scripts,
  docs,
  infrastructure,
  testRunners,
  envExample,
  topLevelDirs,
  notes: [],
};

// Sanity notes the writer may surface to the user.
if (!inventory.docs.includes("README.md") && !inventory.docs.includes("README.rst")) {
  inventory.notes.push("No README detected at repo root.");
}
if (languages.length === 0) {
  inventory.notes.push("No known language manifests detected; inventory may be shallow.");
}
if (monorepo.isMonorepo && monorepo.workspaces.length === 0) {
  inventory.notes.push("Monorepo tooling detected but no workspace globs resolved.");
}

process.stdout.write(pretty ? JSON.stringify(inventory, null, 2) : JSON.stringify(inventory));
process.stdout.write("\n");
