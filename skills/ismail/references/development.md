# Developing ismail itself

Read this only when the user has explicitly asked you to change ismail (the engine, its ops, the skill, the
tests, the README), or to migrate elements a song lists in its `HANDOFF.md`. Making music is the other role, and
it never changes these files (SKILL.md, "Your role").

The dev role is more than editing: it runs **the migration loop** (below), the standing job of turning what the
songs learn into the engine and the skill, and of keeping every session on the same page.

Several sessions work on one machine at once: some make songs, one or more develop the engine, and the user moves
between them. Every rule below exists because breaking it once cost someone work or an afternoon.

## Work on a worktree, never in the shared checkout

The main checkout is shared: other sessions run songs and live engines from it, and some leave uncommitted work in
it. Engine work happens on a branch in its own worktree:

```bash
git -C <ismail> status --short          # what is there before you; none of it is yours
git -C <ismail> worktree list           # who else is working, on what branch
git -C <ismail> worktree add ../ismail-<topic> -b <topic> main
```

One topic per worktree, one agent per worktree. Run the tests and write the code there. Song folders are not in a
worktree (`songs/` is git-ignored), so read a song's files by their path in the main checkout.

## Collaboration must-haves

1. **What is not yours is not touched.** Uncommitted changes you did not make are someone's work in progress: never
   commit, revert, stash or "clean up" them. If they block you, they belong on their own branch: with the user's
   OK, save the diff as a patch outside git, apply it on a new worktree branch, commit it there with a message that
   says where it came from, check the branch copy is identical, and only then restore the checkout.
2. **Nothing unmerged is deleted.** A worktree is removed and a branch deleted only when its work is in main
   (`git merge-base --is-ancestor <branch> main` succeeds) and pushed. Look at its untracked files first, and back
   up anything that is not regenerable. Deleting a folder, a branch or a stash needs the user's yes.
3. **No stash in a shared repository.** The stash stack is shared by every worktree; another session can pop yours.
   Park work in a commit on your branch.
4. **Every commit carries its own proof and its docs:** the full test suite passing in a clean worktree (apply
   exactly what is staged to a fresh checkout and run it there), a `CHANGELOG.md` entry under Unreleased, and the
   skill, README and op docstrings updated in the same commit as the behavior they describe.
5. **Stage your files and hunks only**, never `git add .` or `-a`.
6. **The user merges.** Push the branch and open a pull request; the user reviews and merges. Push to main only when
   the user says so. A worktree stays until its pull request is merged.
7. **Tell the user what changed for the other sessions**: a renamed op, a new rule in the skill, a moved file.
   Sessions already running read the old skill.

## Studio and live parity

ismail has two players for one music: the studio renders a song offline (`ismail/render.py`, `fx.py`,
`instruments.py`, the voices), and the live engine plays it block by block (`ismail/live/`). The studio is the
source of truth; live must sound the same, and a user hears the difference at once ("it sounds nothing like the
original" was a growl whose velocity articulations came out wrong on a deck).

Every engine change answers three questions in its commit and pull request:

1. **Which side does it touch?** Studio only, live only, or both. A change to an effect, an instrument type, a voice,
   automation, buses or the render order is a studio change that live must follow.
2. **How does live follow?** Every built-in effect has a live twin (`ismail/live/fx_blocks.py`, the guitar rig in
   `rig_blocks.py`) running the studio kernel block by block; a change to the effect changes its twin. A new effect
   type without a twin is baked (the workers run the studio code on each event). Instruments and voices render in
   the workers through the studio code, per note, per mono phrase, or for a performer per bar with a second of
   context, so anything that depends on more than that needs checking: a mono synth's glide from the last phrase,
   a drone that began long before a deck's window, randomness keyed on anything but the song position (synths and
   drums seed on the note's place in its bar, performers on `beat0`), work that depends on the length of the
   buffer (code voices get each note whole).
3. **What proves it?** Effects: `tests/test_live_parity.py` holds every live processor to its studio twin over a
   whole window. Instruments and voices: `tests/test_live_song_parity.py` plays every instrument type and library
   voice on a deck against the studio (sample for sample, performers by ear); add a case for a new type or voice.
   Songs: `live_parity(song, bars=[a, b])` compares a real section per track, bus and the mix. Put its table for a
   song the change affects in the pull request.

A parity bug found while making music is a song agent's finding, not its fix: it goes in the song's `HANDOFF.md`
with the A/B numbers and the bars, and the engine agent fixes it on a branch with a test that fails before the fix.

## The migration loop

Songs keep finding what ismail lacks, build it in their own folder and write it in their `HANDOFF.md`. The dev
agent collects those findings, gets the user's decision, builds them into the engine and tells the other sessions.
Each step ends in something you can point at:

1. **Intake.** `python -m ismail.handoffs` lists every handoff section that is new or changed since the last mark,
   across `songs/**/HANDOFF*.md` and the folders in `songs/_migration/roots.txt` (`--full` prints the new text).
   Run it before any engine work, and every couple of hours while songs are active. Read new sections whole.
2. **Triage** into `songs/_migration/LEDGER.md`, one row per item: where from, kind (bug, migrate, feature, skill,
   research, preset), status. Merge duplicates across songs: two songs building the same thing is the strongest
   signal there is. Kinds that stay out of the engine say why: song-only, parked (with the reason), held (blocked on
   a decision, e.g. anything fitted to a commercial recording or named after a brand or a person). Then
   `python -m ismail.handoffs --mark`.
3. **Report and decide.** Tell the user what is new, the verdict you propose for each item and an order. The
   user approves, cuts or reorders; nothing is built before that.
4. **Build**, one topic per worktree branch, with a test that fails before the change, the docs and skill text
   in the same commit, and a pull request (the steps under "Migrating an element" below). The row says `in PR #n`.
5. **Announce after the user merges.** Send each ismail session in the ledger's roster one short message (the
   `SendMessage` tool): what changed, the ops, params and skill sections involved, what to do differently, and that
   the skill changed on disk (re-read the reference before relying on it). Tell, never instruct: what a session does
   with its own song is its business and the user's. Log the message in the ledger; the row says `announced`.
6. **Close.** The song agent marks the item migrated in its own `HANDOFF.md`; the next intake sees the change and
   the row says `closed`. The dev agent never writes in a song's folder (`songs/_migration/` is its own).

## Migrating an element

A song agent that needed something ismail lacks built it inside its song and listed it in
`songs/<slug>/HANDOFF.md`. Migrating it:

1. Read the whole handoff. It names the elements, the evidence that they work (blind exams, measurements), the
   files, a proposed API, tests and skill text.
2. Copy the files into the engine (never move or delete them from the song: the song must keep working as it is).
3. Make the tool surface first: op names, arguments, help text and errors that say what to do next. The agent
   that uses the op has only its docstring and its replies.
4. Tests: a round trip on known material (synthetic audio with known answers), plus one regression test per bug
   the handoff describes.
5. Skill text where an agent will look for it (a route-table row, a section in the matching reference).
6. Tell the user it is migrated and in which pull request; after the merge, announce it (the loop's step 5).

## A song's HANDOFF.md

Written by the song agent, in the song's root folder, so any agent can migrate without the conversation. The
intake splits it on headings and compares section by section, so give each finding its own heading and add to it
rather than rewriting old sections:

```
# HANDOFF: what can migrate out of <Song> (songs/<slug>)
## What it is            the capability, the mechanism, the parameters
## Evidence              blind exam scores, measured errors, what is NOT yet tested
## Files                 every file in the song folder that belongs to it
## Proposed integration  module names, ops (name, arguments, reply), tests, skill text
## Eligible for migration   | element | where | target | state |
## For the skill         lessons and rules the song learned, in the user's words where possible
```

## Suggestions

- Read the ops you touch through the agent's eyes: a reply that dumps a wall of text, an error that only says
  "failed", a parameter whose unit is not in its doc. Fix those before adding features.
- Write rules where every agent reads them (the skill, the `guide` op, docstrings), not in private memory.
- Keep the user's words: a lesson quoted from the user's feedback is more useful to the next agent than a summary.
