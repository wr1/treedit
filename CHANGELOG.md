# Changelog

## 0.1.0 - 2026-10-06

First release.

- `treedit open`: edit a directory tree in a native (Tauri) window or the browser, with annotations, feedback
  for the agent (on paths, lines or several paths), live refresh, drafts, change bars, git history and an
  agent terminal pane.
- `treedit print`: the annotated tree, coloured by word count (token estimates in skill trees).
- `treedit annotation`, `treedit fb`, `treedit edits`, `treedit context`: the agent's side, from the CLI.
- `treedit skill install`: the agent skill for Claude Code and Hermes.
- A treedit logo: in the page header, as favicon, as the app window icon, and in window switchers
  (`make desktop` installs the icon and a hidden `treedit-app.desktop`; `make tool` runs it).
- `treedit open A B` (and `print`): several folders in one tree, each with its own notes, feedback,
  gitignore, drafts and history; feedback ids read `name:N`, and `$TREEDIT_ROOTS` lists the folders.
  Feedback on the top level or across folders, and the top-level annotation, go to the folders'
  common parent's `.treenotes.json` (ids `*:N`).
- The editor merges your unsaved edits three-way with changes on disk, so text is never doubled.
