---
name: treedit
description: Use when working in a project the user reviews with treedit (a .treenotes.json exists or $TREEDIT_ROOT is set) - read the user's annotations (`treedit annotation ls`) and open feedback (`treedit fb ls`) on files, lines and the tree structure, act on it, commit the user's edits and your own work separately with git, and on an "agent roll" pick up the user's manual edits and do light housekeeping (frontmatter, names, spelling/grammar, doubled text) (`treedit edits` shows the user's saved and unsaved edits), answer each item with `treedit fb reply ID "what changed (hash)" --done`; `treedit context` shows what the user has selected. Never write annotations.
---

treedit — Review a directory tree with an agent: annotate files and folders, leave feedback (also on lines), see it coloured by word count; agents read both and answer feedback from the CLI.

This is a CLI toolbox. Discover its commands and
full schema on demand:
  treedit -h   # command tree
  treedit -j   # machine-readable JSON schema

Reviewing with the user (they see the tree, your replies and every file change live in the treedit window):
1. `treedit fb ls` - open feedback: id, path(s), line span with the quoted code, and the request.
   Run it in the tree root, or add `-C "$TREEDIT_ROOT"`. Several folders open in one window:
   `$TREEDIT_ROOTS` lists them (separated by `:`); each keeps its own annotations and feedback, so run
   `fb ls`, `edits` and `annotation ls` in each (`-C <folder>`). In the window and in `treedit context`
   their paths start with the folder's name, and feedback ids read `name:N` (`N` for the CLI).
   Feedback on the top level or on paths in several folders, and the annotation on the top level,
   live in the folders' common parent (where the pane starts): plain `treedit fb ls` there, with
   paths relative to it (ids `*:N` in the window).
2. `treedit context` - what the user has selected in the window right now (paths, lines).
3. Git keeps every diff attributable - the user's or yours - whether the user saved it or not:
   a. Before you start, and again before each commit: `git status` and `treedit edits`.
      `treedit edits` lists the user's own edits: files they saved in the editor, and unsaved drafts
      (as diffs) still open in the window.
   b. The user's saved edits that are not committed yet: commit them first, on their own, as theirs:
      `git add <their paths>` then `git commit -m "user: <what they changed>"`. Never mix them into
      your commits and never revert them.
   c. Unsaved drafts are input, not untouchable work in progress: they may be finished points the
      user never saved. When you edit a file that has a draft, read its diff (`treedit edits`) and
      merge every new point from it into your edit - keep the user's wording where you can, and
      carry over no doubled blocks. Write the result to disk yourself; don't leave a draft out
      because it is unsaved. Say in your commit and reply that the draft is included
      (`agent: <what changed>, with the user's unsaved draft (treedit #ID)`), so the user can load
      the disk version in the window and let the draft go.
   d. Your own work: one commit per feedback item, staging only the files you changed
      (`git add <path>...`, never `git add -A`):
      `git commit -m "agent: <what changed> (treedit #ID)"`.
   e. Commit in the repository that holds the file (a nested `notes/` repo is its own repository).
      Never push, amend, rebase or reset. Not a git repository? Ask the user before `git init`.
   f. After anything that merges (`git merge`, `pull`, `stash pop`, `cherry-pick`, resolving a
      conflict), read each merged file back in full, not just the diff. Merges sometimes keep both
      sides of a block that differ only slightly, leaving near-duplicate text: a paragraph, function,
      list item or heading twice with a small change. Keep the right version (usually the newer or
      fuller one), remove the other, and say in your reply what you dropped.
4. Then answer: `treedit fb reply ID "<what changed> (abc1234)" --done` with your commit's short hash.
   Not doing it, or unsure? Reply without --done and say why, or ask.
5. Annotations are the user's standing comments on files and folders (`treedit annotation ls`,
   also the `# ...` comments in `treedit print`). Read them as context and instructions. Never add,
   edit or move them: they are the user's channel to you, not a place to describe the tree.
   Answer through `treedit fb reply` instead.
Annotations and feedback live in .treenotes.json; use the CLI rather than editing that file.

Agent roll - when the user asks you to "roll" (pick up their manual edits and act on them):
1. `git status` and `treedit edits`; commit the user's saved edits as theirs first (3b).
2. Housekeeping on the files they touched, then a separate commit `agent: housekeeping (<files>)`,
   so their own diff and your tidy-up stay apart. Files with unsaved drafts: merge the draft in
   first (3c), then tidy the result.
   - Frontmatter: add or repair it where the file type expects it (a SKILL.md needs `name` and
     `description`); follow the convention of neighbouring files and invent no fields.
   - Names: when a new file or folder has a placeholder or unclear name, propose a better one in
     your reply; rename (`git mv`) only once the user agrees.
   - Language: fix spelling, grammar and punctuation in their prose with a light touch - keep their
     voice, terms and meaning. Never change code, verbatim quotes, citations or code blocks.
   - Doubled text: remove accidental duplicates - a word typed twice ("the the"), a sentence or
     paragraph pasted twice, a repeated heading, list item or frontmatter key. When two near-copies
     differ, keep the fuller one and say in your summary what you dropped.
3. Then work through `treedit fb ls` as above, and end with a short summary of what you did.

Loop roll - the same roll repeated every few minutes (in Claude Code: `/loop 3m ...`), while the user
keeps editing. Each tick picks up what changed since the last one; a quiet tick (no new edits, no open
feedback) makes no commits and answers in one line. The user ends the loop when they are done.
