# Changelog

## Unreleased

- Sync with the remote: the header's Sync button (and `treedit sync`) commits your edits, pulls with
  rebase, pushes, and merges a conflicting `.treenotes.json` entry by entry, so annotations and
  feedback travel between a treedit here and an agent working in a clone. Notes on both sides
  survive; a new feedback id is renumbered, never dropped. A conflict in any other file is committed
  with its markers and pushed by default, so the remote agent resolves it (the Sync dot then shows
  "conflict pushed"); `treedit sync --no-push-conflict` aborts and lists the files instead.
  `treedit sync --no-commit` is the remote side's half: push what is committed, pull the rest. A dot
  on the Sync button (and `/api/sync` / `treedit sync`) detects unresolved conflict markers directly
  in tracked files (`conflicts: [...]`, `state: "conflict"`), so the warning stays active across
  later commits on other files until the markers are resolved.
- Markdown preview: Preview in the file bar opens beside the source instead of covering it, follows
  edits as you type, and scrolls to keep the block under the caret in view. It renders with marked,
  sanitized with DOMPurify. A ```mermaid block
  renders in the window; a ```d2 block renders through the installed d2 CLI and is shown as a
  sandboxed image. Links are followed by clicking: another Markdown file opens in the preview,
  `#section` scrolls to the heading, and web links open in a new tab. In the source editor,
  Ctrl/Cmd/Alt+click a link (the pointer changes over it). Relative images follow the file.
- The agent pane now folds to a thin strip on the right edge (the » chevron at its top left): one
  segment per session, green when it just wrote, amber when connected but idle, red when
  disconnected, grey when ended. Click the strip to unfold; sessions keep running while folded.
- Delete from the tree: the row's right-click menu, the Delete button, or Del on a focused row removes
  the selection. A file git tracks is removed with `git rm`, so it leaves the index too. It asks first
  only when the deletion cannot be undone: an untracked path, or one whose annotation would be dropped.
- Three more window themes: GitHub light, Gruvbox and Evening (a warm dark).
- Markdown lists: Tab/Shift+Tab move a bullet by one of the file's own nesting levels (2 spaces, 4
  spaces or tabs) instead of always 2; Shift+Tab at the left margin drops the bullet/number/task
  marker, so the item leaves the list.
- Right-click an SVG row and choose **Open in Inkscape** to edit it in Inkscape on the machine
  running the treedit server (only that one app is allowed; needs Inkscape installed).
- PDF previews rasterise pages server-side with Poppler (`pdfinfo`/`pdftoppm`) and show a page
  counter with ‹ › controls; WebKit/Tauri has no dependable inline PDF viewer. If Poppler is not
  installed the old browser-viewer fallback is used.
- The tree keeps its scroll position when a row is selected, a folder opens, or a live refresh
  rebuilds the rows; it no longer jumps back to the top.
- Keyboard navigation: Ctrl+Shift+Left/Right move focus between the tree, editor and agent panes
  (wrapping around). In the tree pane, Ctrl+Shift+Up/Down or plain Up/Down move the selection and
  Enter opens a file or folds a folder. Ctrl/Cmd+N opens New….
- Window: a New… action creates files or folders at any depth from one multiline box (one path per
  line; an extension picks a file, a trailing / a folder), with missing parents. It creates and logs
  them in one go and selects the first new node, without a dry-run or a post-create dialog.
- `treedit new PATH...`: create files and folders at any depth with every missing parent. The last name
  decides the kind: an extension (`.md`, `.xx`) makes a file, no extension a folder (`v1.0/` asks for a
  dotted folder with a trailing slash). Prints each entry created; existing paths error unless
  `--exist-ok`; `--dry-run` previews. The window's New… follows the same rule instead of offering
  separate New file and New folder actions.
- Every state-changing command prints a confirmation line; `--json` after a command gives machine output
  (`treedit -j` alone still prints the schema). New `annotation rm`.
- Strict validation: `annotation mv` with nothing on SRC, `fb add` on a missing path and out-of-range or
  malformed `--lines` exit non-zero.
- Append-only change log (`.treenotes.log.jsonl`, who/when/before/after) of annotations, feedback and
  `treedit new`; `treedit log`, `treedit undo [SEQ]` and `treedit fb restore ID`. Removed feedback ids are
  not reused. Undoing `new` removes only what it created, while files are still empty and folders empty.

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
