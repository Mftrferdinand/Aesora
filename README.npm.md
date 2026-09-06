# zeline (npm)

npm installer wrapper for the [Zeline](https://github.com/Mftrferdinand/Zeline) agentic AI framework by ZeroLinear.

This package is a **thin distribution shim**. It does not reimplement Zeline in JavaScript. At install time it:

1. Detects Python **3.10+** on your `PATH` (override with `ZELINE_PYTHON`).
2. Downloads the versioned Python wheel + `SHA256SUMS` from the matching GitHub release.
3. Verifies the wheel checksum (same trust path as `install.sh`).
4. Installs the wheel into a private runtime at `~/.local/share/zeline/lib` via `pip --target`.

The `zeline` command then launches `python -m zeline.cli` against that runtime.

If the installer did not run during `npm install` (npm ≥ 10 blocks lifecycle scripts unless opted in), the first `zeline` invocation self-installs the runtime automatically — no extra command needed.

## Install

```sh
npm install -g zeline
zeline --version
```

If your npm blocks install scripts and you prefer to run the installer explicitly during install rather than on first launch:

```sh
npm install -g zeline --allow-scripts=zeline
```

## Requirements

- Node.js ≥ 18 (for the installer only — Zeline itself runs on Python)
- Python **3.10 or newer** on your `PATH` (or set `ZELINE_PYTHON`)

## Environment variables

| Variable | Purpose |
| --- | --- |
| `ZELINE_PYTHON` | Python interpreter to use (e.g. `/usr/bin/python3.11`) |
| `ZELINE_INSTALL_ROOT` | Private runtime directory (default `~/.local/share/zeline`) |

## Updating

```sh
npm install -g zeline   # re-runs the installer and replaces the runtime
```

Or use the in-app updater against the same release channel:

```sh
zeline update
```

## Why not a pure npm package?

Zeline is a Python framework (`pyproject.toml`, entry point `zeline = "zeline.cli:main"`). This wrapper exists so users who prefer `npm install -g` get the same verified wheel that `install.sh` installs — without a rewrite, and without bundling the Python source into the npm tarball.
