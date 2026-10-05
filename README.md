# treedit

[![ci](https://github.com/wr1/treedit/actions/workflows/ci.yml/badge.svg)](https://github.com/wr1/treedit/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/wr1/treedit/graph/badge.svg)](https://codecov.io/gh/wr1/treedit)
[![PyPI](https://img.shields.io/pypi/v/treedit.svg)](https://pypi.org/project/treedit/)
[![Python](https://img.shields.io/pypi/pyversions/treedit.svg)](https://pypi.org/project/treedit/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Review a directory tree with an agent collaborator: annotate files and folders, leave feedback on
files, lines or the structure, and let the agent answer it from the CLI.
A [treeparse](https://github.com/wr1/treeparse) toolbox with a native (Tauri) window.

## Install

```sh
uv tool install treedit      # or: pipx install treedit (Python 3.12+, Linux/macOS)
make tool                    # from a checkout: the CLI plus the native window (needs Rust; make app-deps)
```

Without the `treedit-app` window, `treedit open` uses your web browser.

## Use

```sh
make open ROOT=PATH          # build the app window if needed and open PATH (make web: browser)
treedit open PATH            # app window if built, else the browser (--browser, --headless)
treedit print PATH           # print the annotated tree, coloured by word count
treedit annotation ls        # your comments on files/folders (also: get, set, mv)
treedit fb ls                # open feedback for the agent (also: add, reply, done, reopen, rm)
treedit -j                   # full schema for agents (--stub: one-line purpose)
python -m treedit print PATH # without installing the script
```

- Edit text files (Ctrl/Cmd+S saves, atomic, conflict-checked against disk).
- Ctrl+/ toggles line comments, Ctrl+Shift+/ or Shift+Alt+A a block comment, with the file type's
  syntax (`#`, `//`, `/* */`, `<!-- -->`, `--`, `%`, …); in the main and the stacked editors.
- Undo / redo (Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y, the ↶ ↷ buttons): one history per file that survives
  switching files and views; word-sized steps; a disk reload (an agent edit) is one step, so you can undo it.
- Find: Ctrl+F (pre-filled from a one-line selection); Enter / Shift+Enter or F3 / Shift+F3 cycle, "n of m",
  Aa for case; matches tick the overview strip; Esc leaves the match selected. Main and stacked editors.
- Line wrapping (on by default; **Wrap** in the status bar or Alt+Z), in the main and the stacked editors.
- Tab / Shift+Tab indent / outdent the selected lines (Shift+Tab alone: the current line); 4 spaces in
  Python, 2 elsewhere, tabs in tab-indented files.
- Enter keeps the line's indentation (one level more after a Python `:` or an opening `{` `[` `(` in code).
- In the app window, Ctrl+W or Ctrl+Q closes it (asking first if anything is unsaved);
  inside the terminal pane Ctrl+W stays the shell's delete-word.
- **History**: the git log of the selected file or folder (or the whole repository), uncommitted changes
  on top, `agent:` / `user:` commits badged; click a commit for its diff. Nested repos answer for their files.
- Files created in treedit are staged in git (`git add`, in the repository that holds them, so a nested
  `notes/` repo too; ignored paths are not forced in).
- Respects `.gitignore` (git decides, so nested ignores and global excludes count), except `notes/`,
  which stays visible (a nested notes repo's own `.gitignore` still applies). `--show PATH…` changes the
  kept paths, `--no-gitignore` turns it off.
- **Annotations**: standing comments on files and folders for the agent (it reads them, never writes
  them), set with `treedit annotation set PATH TEXT` and shown in the tree; stored in `PATH/.treenotes.json`.
- **Feedback for the agent** on a file or folder, on selected lines (“+ Feedback on L10–14”;
  the comment follows its quoted lines when the file changes), or on several selected paths
  at once (structure feedback such as “merge these”). Items are open or done; the agent answers
  with `treedit fb reply ID TEXT --done` and the reply appears live. Open items show as ● in the
  tree, in the **Feedback** overview, and as `! #N` lines in `treedit print`.
- Live refresh when agents or other editors change the tree.
- Unsaved edits are never dropped: every 1.5 s they are kept as a unified diff against the version
  they started from, in `~/.local/state/treedit/` (outside the project). Reopen treedit and they come
  back, re-applied onto a newer file if the agent changed it meanwhile; edits whose file vanished, or
  that no longer apply, are listed under "Unsaved edits that need you" (restore, show, discard).
- Live merging: when the agent changes a file you have unsaved edits in (open, stacked or in the
  background), your edits are re-applied onto its new version; only overlapping lines raise the
  conflict banner. `treedit edits` shows an agent your saved and unsaved edits, so the skill can have
  it commit yours (`user: …`) apart from its own (`agent: … (treedit #ID)`).
- Change bars: in the editor, a bar on the right marks lines changed recently (green = agent, blue =
  your saves), fading over 30 minutes; a strip at the far right shows where they are in the whole file
  (click a mark to go there). The stacked editors show the bars too.
- Tree markers: ✎ unsaved edits, ⚠ changed on disk while you were editing, ◆ changed by the agent
  (anything not written through the editor). Agent changes get a mild background that fades over
  30 minutes; a folder shows the freshest change inside it, fainter.
- **Agent pane** on the right: a real terminal (bundled xterm.js, stdlib PTY over a local, token-checked
  WebSocket) running a shell or an agent preset, started in the tree root with `$TREEDIT_ROOT`,
  `$TREEDIT_NOTES` and `$TREEDIT_URL` set:
  `treedit open . --agent claude` (or `'hermes --skills treedit'`; default `$TREEDIT_AGENT`, else a shell;
  `make open AGENT=claude`). The session survives reloads and keeps running when the pane is hidden.
  Buttons type into it: **→ Agent** on a feedback item, **Selection**, **Roll** (an agent roll: pick up
  your edits or new files, commit them as yours, tidy up frontmatter/names/spelling/doubled text, then the feedback), **Open feedback**; **Ptyxis** opens
  the same session setup in a separate window. Ctrl+Shift+C/V copy and paste.
- `treedit context` (inside the pane) prints what you have selected: paths, lines and their text.
- `treedit skill install` writes the agent skill to `~/.claude/skills/treedit/` and `~/.hermes/skills/treedit/`
  (`treedit skill show` prints it); it tells the agent to run `treedit fb ls`, act, and reply.
- Syntax highlighting (Python, JS/TS, C-family, Rust, Go, shell, TOML, YAML,
  JSON, Markdown, HTML/CSS, Typst, Julia); no external libraries.
- Ctrl/Cmd+click or Shift+click rows to stack several files read-only in the
  right pane; click a header to edit that one, Esc to clear.
- Names are coloured by document size in the tree: a file's word count ranked among all files (folders
  among folders), dim = small, normal = typical, amber then red = the largest (toggle with **heat**).
- Skill trees (any `SKILL.md` inside): counts become estimated tokens (~4 characters each). Files show
  their own; skill folders show `~min–max`: min = their `SKILL.md` alone, no leaf loaded (a folder without
  one: the `SKILL.md` of each skill inside), max = every file underneath loaded. `treedit print` too.
- A folder holding just one file, however deep, shows on one line (`icons/icon.png`, long paths
  shortened with `…/`); click a folder segment to annotate it (toggle with **compact**). `treedit print`
  colours the same way on a terminal (dark grey = no words); `--no-color` / `NO_COLOR` turn it off, `--color` forces it.

See `treedit -h` (or `treedit <cmd> -h`) for options.

## Development

```sh
make install                 # .venv with treedit (editable)
make test                    # pytest with coverage
make lint                    # ruff
make build                   # sdist + wheel in dist/
```

Releases: bump the version in `pyproject.toml` and `src/treedit/__init__.py`, update `CHANGELOG.md`, then
push a `vX.Y.Z` tag; the release workflow tests, publishes to PyPI and creates the GitHub release.

## License

MIT, see [LICENSE](LICENSE). Bundles [xterm.js](https://github.com/xtermjs/xterm.js) (MIT,
`src/treedit/vendor/LICENSE-xterm.txt`).
