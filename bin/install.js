#!/usr/bin/env node
// Zeline npm installer wrapper.
//
// This is a thin distribution shim. It does NOT reimplement Zeline in
// JavaScript — it downloads the versioned Python wheel from the matching
// GitHub release, verifies it against SHA256SUMS (same trust path as
// install.sh), and installs it into a private runtime directory via the
// user's Python 3.10+ interpreter. The `zeline` bin shim then launches
// `python -m zeline.cli` against that runtime.
//
// The logic mirrors install.sh so both installers stay in lockstep.

"use strict";

const { createHash } = require("crypto");
const { execFileSync } = require("child_process");
const fs = require("fs");
const https = require("https");
const path = require("path");
const os = require("os");

// --- Pinned release metadata (mirrors install.sh VERSION/REF) --------------
const VERSION = "0.3.0";
const REF = "v0.3.0";
const REPO = "Mftrferdinand/Zeline";
const RELEASE_BASE = `https://github.com/${REPO}/releases/download/${REF}`;
const WHEEL_NAME = `zeline-${VERSION}-py3-none-any.whl`;
const SHA256_NAME = "SHA256SUMS";

// Private runtime layout. install.sh defaults INSTALL_ROOT to
// $HOME/.local/share/zeline; we use the same convention so the two
// installers do not fight over two separate runtimes on the same machine.
const INSTALL_ROOT =
  process.env.ZELINE_INSTALL_ROOT ||
  path.join(os.homedir(), ".local", "share", "zeline");
const WHEEL_DIR = path.join(INSTALL_ROOT, "lib");
// Where the bin shim records the resolved python + module path.
const STAMP = path.join(INSTALL_ROOT, "npm-install.json");

// Windows detection. install.sh dispatches to install.ps1 on Windows;
// here we just need to know whether we are shelling out to pip or to a
// .ps1-style flow.
const IS_WINDOWS = process.platform === "win32";

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function step(label, msg) {
  process.stdout.write(`[zeline] ${msg}\n`);
}

function fail(msg) {
  process.stderr.write(`[zeline][x] ${msg}\n`);
  process.exit(1);
}

function warn(msg) {
  process.stderr.write(`[zeline][!] ${msg}\n`);
}

// HTTPS GET that follows GitHub release redirects to the CDN. Returns a Buffer.
function fetchBuffer(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(
      url,
      {
        headers: { "User-Agent": "zeline-npm-installer" },
        timeout: 60000,
      },
      (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          // Follow the redirect to the CDN.
          res.resume();
          fetchBuffer(res.headers.location).then(resolve, reject);
          return;
        }
        if (res.statusCode !== 200) {
          res.resume();
          reject(new Error(`HTTP ${res.statusCode} for ${url}`));
          return;
        }
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve(Buffer.concat(chunks)));
      }
    );
    req.on("timeout", () => {
      req.destroy(new Error(`timeout fetching ${url}`));
    });
    req.on("error", reject);
  });
}

function sha256Hex(buf) {
  return createHash("sha256").update(buf).digest("hex");
}

// Parse a SHA256SUMS body (format: "<hex>  <filename>" per line) and return
// the hex digest for the requested filename.
function digestFor(sumsText, filename) {
  for (const line of sumsText.toString("utf8").split("\n")) {
    const m = line.trim().match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (m && m[2].trim() === filename) {
      return m[1].toLowerCase();
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Python detection — must be >= 3.10 (mirrors install.sh's PYTHON_BIN probe)
// ---------------------------------------------------------------------------

function detectPython() {
  // On Windows, prefer `py -3` first (the official launcher from python.org)
  // and reject the Microsoft Store `python.exe` stub, which lives under
  // WindowsApps and opens the Store instead of running Python. The stub
  // reports no usable version, so we also validate by running the probe.
  // Mirrors install.ps1:Resolve-Python.
  const candidates =
    process.env.ZELINE_PYTHON
      ? [process.env.ZELINE_PYTHON]
      : IS_WINDOWS
        ? ["py -3", "python", "python3"]
        : ["python3", "python"];

  for (const candidate of candidates) {
    const parts = candidate.split(" ");
    try {
      // Probe version + resolved executable. execFileSync throws on non-zero
      // exit or missing binary. We print three lines: version_ok (1/0),
      // version string, and sys.executable — same shape as install.ps1.
      const probe = "import sys; print(1 if sys.version_info >= (3,10) else 0); print('%d.%d.%d' % sys.version_info[:3]); print(sys.executable)";
      const out = execFileSync(parts[0], parts.slice(1).concat(["-c", probe]), {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 15000,
      });
      const lines = out.trim().split(/\r?\n/);
      if (lines.length < 3 || lines[0].trim() !== "1") continue;
      const version = lines[1].trim();
      const exePath = lines[2].trim();

      // Reject the Microsoft Store alias stub on Windows. The stub's
      // resolved executable lives under WindowsApps.
      if (IS_WINDOWS && /WindowsApps/i.test(exePath)) {
        warn(`Skipping ${candidate} — it is the Microsoft Store alias stub (${exePath}).`);
        continue;
      }

      const m = version.match(/^(\d+)\.(\d+)\.(\d+)/);
      if (!m) continue;
      const major = parseInt(m[1], 10);
      const minor = parseInt(m[2], 10);
      if (major > 3 || (major === 3 && minor >= 10)) {
        return { bin: candidate, version, executable: exePath };
      }
      warn(`Found ${candidate} ${version} but Zeline requires Python 3.10+.`);
    } catch (_e) {
      // Not installed or not on PATH; try the next candidate.
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Main installer
// ---------------------------------------------------------------------------

async function main() {
  process.stdout.write("\n  Zeline npm installer · v" + VERSION + "\n\n");

  // 1) Python prerequisite.
  const py = detectPython();
  if (!py) {
    fail(
      "Python 3.10+ not found. Install Python 3.10 or newer, or set ZELINE_PYTHON to the interpreter path, then re-run:\n" +
      "    npm install -g zeline\n" +
      "On Windows, install from https://www.python.org/ and ensure it is on PATH."
    );
  }
  step("1/4", `Python detected: ${py.bin} (${py.version})`);

  // 2) Fetch SHA256SUMS + wheel from the matching GitHub release.
  step("2/4", `Downloading ${WHEEL_NAME} from ${REF}…`);
  let sumsBuf, wheelBuf;
  try {
    [sumsBuf, wheelBuf] = await Promise.all([
      fetchBuffer(`${RELEASE_BASE}/${SHA256_NAME}`),
      fetchBuffer(`${RELEASE_BASE}/${WHEEL_NAME}`),
    ]);
  } catch (err) {
    fail(`Could not download release assets: ${err.message}`);
  }

  // 3) Verify the wheel checksum against SHA256SUMS — same trust path as install.sh.
  const expected = digestFor(sumsBuf, WHEEL_NAME);
  if (!expected) {
    fail(`${SHA256_NAME} has no entry for ${WHEEL_NAME}.`);
  }
  const actual = sha256Hex(wheelBuf);
  if (actual !== expected) {
    fail(
      `Checksum mismatch for ${WHEEL_NAME}.\n  expected: ${expected}\n  actual:   ${actual}\n` +
      "The downloaded wheel is corrupted or the release was tampered with. Refusing to install."
    );
  }
  step("3/4", `SHA-256 verified: ${actual.slice(0, 12)}…`);

  // 4) Install the wheel into a private runtime via pip --target.
  //    --target keeps the runtime isolated from the system site-packages,
  //    mirroring install.sh's private INSTALL_ROOT/venv approach without
  //    requiring venv creation (which can be flaky in stripped-down Termux
  //    or container environments).
  fs.mkdirSync(WHEEL_DIR, { recursive: true });
  const tmpWheel = path.join(WHEEL_DIR, WHEEL_NAME);
  fs.writeFileSync(tmpWheel, wheelBuf);

  const pyParts = py.bin.split(" ");
  const pipArgs = pyParts.slice(1).concat([
    "-m",
    "pip",
    "install",
    "--no-input",
    "--no-cache-dir",
    "--no-deps",
    "--upgrade",
    "--target",
    WHEEL_DIR,
    tmpWheel,
  ]);
  try {
    execFileSync(pyParts[0], pipArgs, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 180000,
    });
  } catch (err) {
    fail(`pip install failed: ${err.message}`);
  } finally {
    // Remove the wheel artifact; the installed tree is what matters.
    try { fs.unlinkSync(tmpWheel); } catch (_e) {}
  }

  // Record the resolved interpreter + module path so the bin shim stays
  // stable even if the user later changes their default `python3`.
  fs.mkdirSync(INSTALL_ROOT, { recursive: true });
  fs.writeFileSync(
    STAMP,
    JSON.stringify(
      {
        version: VERSION,
        ref: REF,
        python: py.bin,
        python_version: py.version,
        wheel_dir: WHEEL_DIR,
        installed_at: new Date().toISOString(),
      },
      null,
      2
    )
  );

  step("4/4", `Installed to ${WHEEL_DIR}`);
  process.stdout.write("\n  Zeline is ready. Run: zeline --version\n\n");
}

main().catch((err) => fail(err && err.message ? err.message : String(err)));
