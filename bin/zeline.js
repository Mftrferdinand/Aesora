#!/usr/bin/env node
// Zeline bin shim. Reads the runtime stamp written by bin/install.js and
// launches `python -m zeline.cli` against the private runtime, so the
// installed wheel is used regardless of the user's current PATH.

"use strict";

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const INSTALL_ROOT =
  process.env.ZELINE_INSTALL_ROOT ||
  path.join(os.homedir(), ".local", "share", "zeline");
const STAMP = path.join(INSTALL_ROOT, "npm-install.json");
const INSTALLER = path.join(__dirname, "install.js");

function fail(msg) {
  process.stderr.write(`[zeline][x] ${msg}\n`);
  process.exit(1);
}

// Lazy self-install: npm's allow-scripts feature (npm >= 10) blocks the
// postinstall script by default, so the stamp may not exist on first run.
// Rather than error out, run the installer ourselves, then continue.
if (!fs.existsSync(STAMP)) {
  process.stderr.write("[zeline] First run — installing the Zeline runtime…\n");
  const result = spawnSync(process.execPath, [INSTALLER], { stdio: "inherit" });
  if (result.status !== 0) {
    fail("Runtime installation failed. See the messages above, then re-run: zeline --version");
  }
  if (!fs.existsSync(STAMP)) {
    fail("Installer completed but the runtime stamp was not written. Re-run: npm install -g zeline");
  }
}

let stamp;
try {
  stamp = JSON.parse(fs.readFileSync(STAMP, "utf8"));
} catch (err) {
  fail(`Could not read Zeline runtime stamp (${STAMP}): ${err.message}`);
}

const pyBin = process.env.ZELINE_PYTHON || stamp.python;
if (!pyBin) {
  fail("No Python interpreter recorded for this Zeline install. Re-run: npm install -g zeline");
}

const pyParts = pyBin.split(" ");
// PYTHONPATH points at the private wheel dir so `python -m zeline.cli`
// resolves the installed package without needing sitecustomize hacks.
const env = Object.assign({}, process.env, {
  PYTHONPATH: stamp.wheel_dir || process.env.PYTHONPATH || "",
});
// Avoid module shadowing when launched from inside a running Zeline session
// — same guard as zeline/updater.py:_run_installer.
delete env.PYTHONHOME;

const child = spawn(
  pyParts[0],
  pyParts.slice(1).concat(["-m", "zeline.cli"]).concat(process.argv.slice(2)),
  { env, stdio: "inherit" }
);

child.on("error", (err) => {
  fail(`Failed to launch Zeline (${pyBin}): ${err.message}`);
});
child.on("exit", (code, signal) => {
  process.exit(code == null ? (signal ? 1 : 0) : code);
});
