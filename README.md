# treedit

[![ci](https://github.com/wr1/treedit/actions/workflows/ci.yml/badge.svg)](https://github.com/wr1/treedit/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/wr1/treedit/graph/badge.svg)](https://codecov.io/gh/wr1/treedit)
[![PyPI](https://img.shields.io/pypi/v/treedit.svg)](https://pypi.org/project/treedit/)
[![Python](https://img.shields.io/pypi/pyversions/treedit.svg)](https://pypi.org/project/treedit/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

Editor and annotator aimed at agent assisted editing of skill trees.
Review a directory tree with an agent collaborator: annotate files and folders, leave feedback on
files, lines or the structure, and let the agent answer it from the CLI.
A [treeparse](https://github.com/wr1/treeparse) toolbox with a native (Tauri) window.

![Agents on the tree, a live merge into unsaved edits, several files open, change bars fading](docs/treedit.png)

## Install

```sh
uv tool install treedit      # or: pipx install treedit (Python 3.12+, Linux/macOS)
make tool                    # from a checkout: the CLI plus the native window (needs Rust; make app-deps)
```

Without the `treedit-app` window, `treedit open` uses your web browser.

## Discover

```sh
treedit -h                   # command tree
treedit -j                   # machine-readable JSON schema
treedit <cmd> -h             # one branch
```

## Development

```sh
make help
```

Releases: bump the version in `pyproject.toml` and `src/treedit/__init__.py`, update `CHANGELOG.md`, then
push a `vX.Y.Z` tag; the release workflow tests, publishes to PyPI and creates the GitHub release.

## License

MIT, see [LICENSE](LICENSE). Bundles [xterm.js](https://github.com/xtermjs/xterm.js) (MIT,
`src/treedit/vendor/LICENSE-xterm.txt`).
