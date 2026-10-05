# Changelog

## Unreleased

### Provenance: the string profiles credit their real sources (M73)

- `voices/strings/{violin,contrabass}.mimic.json` were measured from VSCO 2 Community Edition (Versilian Studios,
  CC0) and `cello.mimic.json` from "real cello notes" by flcellogrl (Freesound pack 12408, CC BY 4.0), both via
  tonejs-instruments; their `source` fields said Philharmonia Orchestra, which tonejs-instruments' own source list
  does not support. instruments.md says the same, and that the cello needs credit.

### Live tests: notes go straight to the stage dev, and updates come back (S31)

- stage.md and stage-dev.md: during a live test the studio agent in the room sends the person's stage notes directly
  to the stage dev (and writes them in the handoff); when a change touches the page's code, the stage dev tells that
  agent the update is ready, and the person takes it with the update gesture. The scene's content is the studio
  agent's to change; how the stage works is the stage dev's.

### Roles: studio agents, the maintainer, the stage dev (S24); the intake lists open pull requests (M77)

- `python -m ismail.handoffs` lists the open pull requests after the handoffs (title, branch, author, checks,
  whether it merges cleanly), marked new or updated since the last `--mark`, so a pull request is never seen only
  because its author sent word. It uses the GitHub command line when it is there and says so when it is not;
  `--no-prs` skips it.
- The skill names two kinds of agent: studio agents work within ismail (a song, a sound, a live or DJ set, a film,
  a scene on the stage), dev roles work on it. A studio agent that finds something general asks the person whether
  to contribute it and suggests starting a dev session; it never turns into a dev mid-conversation.
- New references for the dev roles, from the sessions that held them: `maintainer.md` and `stage-dev.md` (VR is
  one way into the stage, so its developer is the stage dev). development.md gains the area dev role, the start-up
  routine (progress file, machine, intake, report; every 4 hours by default, the person sets it), and why proactive
  and reactive work cost differently.
- stage.md gains the headset lessons it lacked: queue spoken lines and keep captions up until spoken, one sound one
  meaning, nothing that hitches while the person is in, a purpose for every run, panels that stay put, everything
  touchable by hand, who answers when two sessions listen, listeners reconnect after a restart; the reload advice is
  corrected (the plain scene address).
- development.md: a public voice, instrument or profile stays compatible with the songs that use it (new behavior
  as a new param whose default is the old sound); when it cannot, the new one ships beside its ancestor under a
  findable name, with `derived_from` in its data and credit both ways.
- blind-tests.md: the listening device is part of the exam (record it, one per round, a device sweep when it
  matters, calibrate the listener's floor with codec lenses, log the floor) (S30).
- Skill text describes actions in plain words with synonyms (send a message to a session, conversation or agent;
  a browser pane, preview or web view) instead of one harness's tool names.

### Faster mimic renders (M76); placement exams (S23)

- `mimic.render` computes each partial only while it sounds, so a long tail after the release costs next to
  nothing (a cello C2 with a 3 s tail: 2.5 s to 0.4 s, the same sound within -70 dB). Channels that would be equal
  (width 0, one player) are computed once.
- New mimic params: `mono=True` computes one channel for a caller that sums to mono; `floor=<dB>` skips partials
  that far under the strongest (off by default: 60 dulls the top of low notes by 3 to 5 dB).
- blind-tests.md: a placement exam needs a reference point and a clear task.

### The VR stage (M46)

- `ismail.stage`: the VR stage that grew in the Crossroads video (songs/crossroads/video/vr) is now part of the
  engine. A three.js WebXR page for a desktop browser or a headset (Quest 3), a server that serves a song's scenes
  (`python -m ismail.stage.server --scenes <song>/video/vr/scenes`), and the live link between the page and agents.
- 63 `stage_*` tools: `stage_start` / `stage_stop` / `stage_status`, `stage_events` (what the person did and said:
  voice notes, gestures, edits), `stage_world` (a scene's world.json), `stage_scene_export` (a scene rebuilt from
  its Blender build script in a heavy-job slot), `stage_note` (the "updates ready" card), `stage_cmd` for a command
  with no op yet, and 55 typed page commands (`stage_object_set`, `stage_say`, `stage_panel_show`,
  `stage_waypoint_set`, `stage_actor_play`, `stage_stream`, ...). Each one waits for the page's answer and raises
  with the next step when no page shows the scene or the page refuses.
- Scenes are data: everything the runtime used to hard-code for one song (who plays whom, facings, partners, the
  floor, keep-out boxes, the default scene, the build script) lives in `scenes/<name>/world.json` and
  `scenes/stage.json`. Session files (client log, speech cache, bundle, update notes) go to `<scenes>/_stage/`.
- One server per port: a busy port is refused (Windows let two servers bind one port and split the live link).
- Pins while following: `stage_follow_anchor(scene, person, joint="hips", to=<seat object | [x, y, z] | "here">)`
  (and "📌 Pin hips" on the Follow panel) keeps a seated person's hips on the seat, facing their own way: the user's
  head only bends the spine (direction, so sitting lower or taller does not sink or lift them), the hands drive the
  arms, the feet plant in front of the seat or on a rung under a high one, or on their own pins (`joint="feet"`).
  Walking clearly away from the seat lets go. The Follow panel shows the pins and that talking is not recorded
  without the phone gesture.
- Every Follow is recorded, in memory: the newest 180 s of the last Follow wait in the page, and after "■ Stop" a card
  offers "💾 Keep as take" (then the usual review: play on them, trim, redo) or "🗑 Discard"; `stage_take_keep_last`
  keeps it for the person afterwards. A liked 61 s follow of the bartender was lost because a plain Follow kept nothing.
- `stage_events(who=)` names an agent that follows a scene; a listener with no name reads "an unnamed agent" in the
  headset, not "unnamed".
- Pins take the pointer ray: a to-do pin's card (and its diamond) stops the ray, lights its border, and a pinch opens
  its note, so pins can be worked from a few steps away (the ray went through the card onto what was behind).
- The version card in front of the person shows on entering VR, when the server restarts, and when listening flips
  between somebody and nobody; no longer each time one listener of several comes or goes (an agent polling every
  half minute kept bringing it back).
- Body panels hold still to be read: a panel the person looks at (within 32 degrees) stays where it is, and for 1.5 s
  after; looking at it never counts as the body turning; it moves only when its place has drifted 25 cm for 0.6 s
  (a walk, a real body turn), then eases there. It used to dart away as they turned to read it.
- The thumbs prompt rides on the answering hand: while a spoken question waits (`stage_ask`, now with `sender=`),
  and while the right hand forms a thumb at a panel, a card over the right wrist says who asks, the question, and
  what up and down will answer, filling as the gesture is held.
- Every panel and caption says who it is from: `stage_say(sender=)`, `stage_panel_show(sender=)` (a command's `from`)
  draw a chip and border in that name's colour, fixed per name, and a sender's body panels keep to one side. The VR
  card that goes with a spoken line rides with the person now, titled by its sender instead of "Claude". The
  server's own lines are from "stage".
- Pin touches land: a to-do pin's card takes a fingertip as well as its diamond, a pin re-arms after 1.2 s even
  if the hand stayed close (it needed the tip to leave by 18 cm), the gaze window is 60 degrees, and a tip at a pin
  that does not open it says why (`pin_touch_missed`). A finger gun at a pin does not travel.
- A poke at UI wins over travel: while a hand's fingertip is within 10 cm of a panel, menu or button, or for 0.8 s
  after it pokes one, the finger gun shows no travel arc and its thumb click does nothing (`travel_held` says so).
  Poking menu buttons with the same finger gun that aims travel had teleported the person twice.
- Panels that ride with the person: `stage_panel_show(anchor="body", side="right"|"left", seconds=)` keeps a message just
  out of view beside where their body faces (a new body heading from the head and hands: a held head turn or the
  hands held out turn it, a glance does not), following them as they move; dragging it moves its place around them.
  World panels stay for notes about a place. Speech and new panels wait while the person is talking (a note
  recording, the phone gesture, 3 s after a note): a reply arriving mid-thought had lost them their sentence.
- Presence: the stage knows who is listening. A listener is anything following the live log (`stage_listen` across
  every scene through GET /live/inbox, or `stage_events` with since= on one); the headset shows "listening: <who>"
  or "nobody is listening" on entering VR and whenever it changes. A voice note a listener was handed but did not
  answer within 6 s is announced ("Handed to <who>"); one nobody was handed is answered out loud ("Nobody is listening right now. I
  saved your note.") and kept in `_stage/unread.jsonl`. Hooks (`~/.ismail/stage_hooks.json`; a song's
  `_stage/hooks.json` only when that file trusts its folder) run commands on entered_vr, left_vr, voice_note and voice_unheard. GET /live/presence, `_stage/presence.json`,
  `stage_presence`. The page also says when the server behind it restarted. (After six notes went unheard.)
- Desktop movement: the wheel steps forward where you look (along the floor in walk mode), the orbit pivot
  travelling with the camera, so zoom no longer shrinks the orbit until the wheel stalls; walk and key speed scale
  with the scene (3.5 m/s in the Crossroads club, was 1.2), Shift 3x.
- Scene lineage (M75): a scene's world.json may say `derives_from` (and `pass`, `pass_env`, `assets`).
  `stage_scene_export` builds a derived scene from its ancestor's full build, then its line's passes in the bridge
  (`VR_PASS`), the line's edits merged (the variant's win) and the Quest diet in the bridge (`VR_DIET`), so a remodel
  or another era never starts from a blockout. `stage_scene_new(name, source=)` makes one: the lineage in
  world.json, the page's pieces copied (trees, names, cues, waypoints), actor bodies from the source. Exports set
  `STAGE_SCENE` so renders go in `renders/<scene>/`. stage.md: "Deriving a scene".
- The stage server stays up (M74): a fixed pool of 32 workers instead of a thread per request (Python 3.11 kept every
  finished request thread, and the page polls 2.5 times a second: the old server died of a MemoryError after about
  40,500 threads), long-polls capped per client, `GET /health` (shown by `stage_status`). A full disk no longer
  stops the live link (state and events stay in memory) or the headset's boot (the last good bundle is served).
- The Blender bridge and the Quest diet (`ismail/stage/bridge`: merged groups, triangle and texture budgets,
  MakeHuman skin and mask-map fixes) ship with it. three.js r180 is vendored (MIT).

## 0.3.0

### Verify from the person's side; small fixes

- SKILL.md non-negotiable: every piece of work names what the person will see, hear or feel, is checked from their
  side, and is reported "verified" with the evidence (or "not verified yet" and what to look at), never a bare
  "done". Ops that change what the person perceives reply with what verifies it.
- `api.call(name, /, **kw)`: the op name is positional-only, so ops that take their own `name` argument
  (`mimic_measure`, `live_stream`) can be called through it.
- blind-tests.md: check the answer key for patterns before the page goes up.
- instruments.md: VSCO 2 CE file names are one octave low (the harp excepted).

### Install and distribution

- On PyPI: `pip install ismail`, or `uvx ismail mcp` to run the MCP server without installing. New console
  commands `ismail` (the CLI, same as `python -m ismail`) and `ismail-mcp`; `ismail mcp` starts the server.
- Claude Code plugin: `/plugin marketplace add newsbubbles/ismail`, then `/plugin install ismail@ismail` loads the
  server and the composing skill together (`.claude-plugin/`).
- Listed in the official MCP Registry as `io.github.newsbubbles/ismail` (`server.json`); a tag push publishes to
  PyPI and the registry (`.github/workflows/publish.yml`).
- `Dockerfile` (stdio server) and `glama.json` for directories that build and inspect servers; `CITATION.cff`.
- The README, the plugin and the client configs install from GitHub (`uvx --from git+https://github.com/newsbubbles/ismail ismail mcp`),
  which works whether or not a release is on PyPI. README: an "If you are an AI agent" section.

### Roadmap

- ROADMAP.md: where ismail is going (worlds, visiting each other's, hands and 4D editing, agents in the room,
  sound, pictures, the person, a hub for shared work) with a status on each; a "Where it is going" section in the
  README.
- SKILL.md: share what would help others (a fork and a pull request, after the inclusion review); development.md:
  sharing back from any user's project; user-experience.md: pictures have a vernacular too.

### Live output follows the device

- The live output follows the system default (`device='default'`): a Bluetooth speaker that connects mid-set takes
  over within a few seconds, and a device that stops taking audio falls back to the default. `live_device` moves a
  running set to another output by hand. The timeline, queue and audio mixed ahead carry on (about a second's gap);
  `live_start(follow_device=False)` keeps the old behaviour.
- The handoff scanner skips `history_src/` backups.

### Live: stream to a scene, controls

- `live_stream`: the master, a bus or a deck as raw PCM (int16 stereo, 44.1 kHz) over a GET on the engine's
  localhost port, each with its own safety limiter; a listener that falls behind loses its oldest audio and never
  slows the set. For a VR stage that plays each object's own bus at its place (relayed by the page's server).
- `live_map`, `live_control`, `live_controls`: a named control (a knob, slider or switch) mapped once to a track,
  bus or deck volume, a deck EQ or an effect param, with linear, log, switch or raw scaling; moves apply in the
  engine at once and are logged by bar, and read back as `[bar, value]` automation points.
- A streamed bus or deck that goes quiet sends silence instead of nothing, so every listener stays in step (the
  Crossroads stage had to fill the gaps itself), and `live_stream(project, name=...)` works (the op's `name` clashed
  with the dispatcher's).
### The stage in the skill

- `references/stage.md`: building a scene with a person inside it, from the Crossroads build: which surface for
  which decision, eye exams for pictures, bodies and contact, contact with a person in a headset (every interaction
  a sound, the person's names for things, a first-time tutorial one gesture at a time), shared-editing rules that
  never lose their work (no save before the scene has loaded), agents first.
- user-experience.md: when the person is inside the work. SKILL.md points to stage.md.

### Placement offsets

- Sounds land by their start; music lands on an anchor. A note can now be nudged off its beat in milliseconds:
  `'0 C4 1 100 @-40ms'` (negative = earlier), and a whole part with `track_set(offset_ms=-35)`. The note keeps its
  beat: `notes_read` shows the `@`, the roll stays on the grid, quantize and copy keep the nudge, and
  `notes_transform(offset_ms=)` sets it on many notes. Automation stays on the song's time; audio clips move with
  the track offset. A nudged note is the same as a note written at its nudged time, in the studio, in any window
  (bit-identical), on a deck (live parity) and in the video sync. A note nudged before 0 s starts at 0 s and the
  render reply says so. Live clips read `@` the same way. From tambopata, whose player was time-warped to land on
  the beat and sounded synthetic.

### The person: lexicon, objectives, user-experience reference

- The lexicon: `lexicon_note`, `lexicon_find`, `lexicon_view` keep a two-way map between the person's own words for
  what they hear and see ("boxy", "too clean") and ismail's terms (ops, parameters and their direction, effects,
  measurements), with the song, the moment, the craft the word belongs to (composer to colourist) and whether the
  change worked. Lookups go both ways; the view reads as a learning curve (the share of trade words by month, the
  crafts a vocabulary grows in). One local, append-only file shared by every session (`songs/_user/lexicon.jsonl`
  or `$ISMAIL_LEXICON`), never committed; a `who` per entry for other people's feedback. Words about the work only:
  never emotion, mood or health.
- Objectives: `project_new(objective=)` and `project_set(objective=, objective_by=)` record what a piece is for, in
  the person's words, with history; `project_info` shows it. `project_new(derived_from=)` carries the original's
  objectives and lineage into a version (intent provenance).
- Skill: `references/user-experience.md` (the lexicon, exams and pages, objectives, consent, what never to
  record), a SKILL.md non-negotiable, and a THE PERSON section in `guide`.

### Measure first, in the tools

- Every track says what its sound is modeled on: `project_info` lists each as measured (a mimic profile, a measured
  library voice, a sample imported or extracted from a recording, a fit), designed (on purpose) or unstated, and
  `render` names the unstated ones with the ops that measure. Fits record it themselves (`instrument_fit`
  apply_to_track, `track_fit` apply); the new `track_model` op records an example the tools could not see or marks
  a sound designed. Agents skipped measuring when the rule was only in the skill, most of all after a context
  summary; the tool replies keep it in view.
- Library voices state their provenance in INFO (`measured` or `designed`).
- `guide` opens with MEASURE FIRST.

### The machine: a line, and priority from the user

- `python -m ismail.machine run --wait 30m` (and `slot(..., wait=)`) stands in line for a heavy-job slot instead
  of being refused, and a job that does not wait yields to every waiter ahead of it. The board lists the line.
- `python -m ismail.machine priority <session> --for 3h --by "the user"` puts that session first in line until it
  expires (`--clear` ends it); it needs `--by`, since only the user gives it. Priority orders the line only: the
  heat limit, the busy CPU and the memory reserve hold for everyone (`--force` skips the heat limit and was the
  only way to go first; the voice session asked for this to finish its blind exams).

### What to reach for when

- SKILL.md: "What to reach for when", one table from the situation to the op, reference or rule (the start of a
  task and every compaction, measuring, real instruments, eye and blind exams, the person's words, sources and
  credits, versions, the shared machine, live sets, sharing back). The tools say back what is missing; the table
  says what to reach for.
- README, "If you are an AI agent": measure first, then ask the person's senses with exams (an eye exam for a
  direction, a blind exam to know when you are done, from one note up to the full mix).
- blind-tests.md: why exams (the person's senses as data, their words into the lexicon) and climbing from the
  smallest unit, since a test pitched too hard gives no direction.
### Credits name what the piece uses

- `credits` credits only the sources the piece uses: a row is used when a part's model names its file, its folder
  of takes or its id (a video id naming a stems folder), a mimic profile or a sample came from it, or its table's
  'in the song' column says so (prose like "**in the song**: the drum kit" or "not yet" reads as yes or no).
  `consulted=True` adds the rest under "Also consulted". A plain list that repeats a table's rows (a SOURCES.txt of
  video ids) is left out, and a table under its own heading keeps it.
- `track_model(on=[...])` takes several sources for one part (a forest bed from two recordings, a voice
  cross-synthesized from bird takes and a player's stem), and a folder of takes (`on='ref/birds/potoo'`).
### Live: the set says when it runs out

- `live_status` adds `RUNWAY ENDED N bars ago` when a set that has played has had nothing new queued for 8 bars
  (what loops on unchanged, or that it rings out), and `THIN for N s` when one track is left where the set has had
  several, or the mix sits 20 dB under its usual level, for 30 s. A set ran 10 minutes on one hat loop after its
  outro forgot to stop it, and `SILENT ON AIR` never fired.

### Sources and credits in the tools

- `project_info` lists a song's sources: the recordings, videos and scores in its `ref/` folders, which of them
  have a row in a SOURCES file, and rows without a licence or an author. `render` names files with no row. Stems,
  separations and analysis projects are skipped; a video's id in a SOURCES row covers its download and the wav
  made from it.
- `credits` (new op, 98 tools) writes `CREDITS.md` at the song root from the SOURCES tables (approval, local path,
  date and note columns left out), each part's model grouped by source, and the lineage. It says whether the piece
  plays recorded audio (imported samples, audio clips) or holds only measurements, and lists what it could not
  credit.
- `track_model(on='ref/birds/x.mp3')` takes a file in the song's `ref/` folder: any `on` starting with "ref" was
  read as the project reference and refused, and paths were looked for only under `proj/`.

### Skill: provenance, the deliverable, the machine-aware performer

- SKILL.md: provenance is kept from the first download to the public page. Every source a song uses, measuring-only
  ones included, gets a `ref/SOURCES.md` row (who made or played it, licence, what was measured); every track says
  what it is modeled on; performers and communities measured from recordings are credited; public pages take their
  credits from `SOURCES.md`. instruments.md and music-video.md log sources and assets the same way.
- SKILL.md: long work stays on its deliverable. `PROGRESS.md` at the song root, read at every start and after every
  compaction; reread the story before designing for it; a tool is a side track unless it unblocks the next step.
  music-video.md: the cast comes from the story, never from the track list, and effort follows the cast's order.
- live.md, "Watch the machine as well as the room": lessons of a 16-hour set (guards keyed on audio trouble,
  tracked watchdogs, shrinking the rig under load, one deck on a busy machine, the set on the person's clock, pause
  and resume as a move, borrowed voices checked before they go on air).

### Fixes from song handoffs

- Render memory: a track's whole output stays in memory only while an effect reads it (a sidechain or vocoder
  source), and stems are kept from their first to their last sound as float32, built full length when read. A
  40-bar song of 16 one-note tracks: peak 2856 -> 404 MiB, 1835 -> 73 MiB held after. A 146-bar song of ~70 tracks
  (tambopata) had needed ~20 GB and ran out of memory.
- `mimic_measure` measures a short note (a 0.3 s panpipe): its attack calibration read the note's level over a
  window that started after the note ended and produced a non-finite buffer.
- `analyze_timbre` (and every analysis reading a source in stereo) works on a mono file: both channels read the same.
- Live decks run the song's master chain (its limiter, compressor, any master effect), as its studio render does:
  `live_load` dropped it, so a deck played about 4 dB quieter and unlimited. `live_status` shows it on the deck line.
- A looping performer clip no longer hands its voice a negative song time: the context carried over the loop point
  sat at negative clip beats, and a voice that seeds on the song time (the birds call voice) failed on it.
- `live_transition` takes the old deck off air when it ends, so the next song loads onto it (it was refused, and a
  helper that crashed on the refusal left a set silent for 9 minutes). `live_status` says `SILENT ON AIR` when a set
  that has played sounds nothing for 10 s. `live_deck(cue=False)` describes the deck as it will be. `live_load`'s
  doc says a cued deck plays from `at`.
- `djkit.gap` brings each target back to a level (`level_db`, a number or per target) instead of 0 dB, and
  `Set.gap` uses the gains the set has given each track: a set running its tracks at +4 to +8 dB had every drop land
  under its build.
- The machine governor: `run --est` takes a unit (`10m`, `600s`, `1.5h`; a bare number is minutes and one above 240
  is refused, since `--est 600` meant as seconds showed a 10-minute render as 585 min). The board shows a `python -c`
  job by its first line and how far past its estimate a job runs.

### Roles and the migration process

- `development.md`: the roles as a multi-agent system (the user, song agents, the dev agent, subagents: what each
  owns and writes, and the contracts between them); the inclusion review before anything goes into the public repo
  (general beyond its song? measured from the user, who must say yes first? fitted to a commercial record or
  carrying a brand name, held for the user's decision? provenance recorded); preparing a voice or an engine for
  ismail in eleven steps (copy never move, strip the song out, render the same anywhere, live parity, INFO as manual
  and provenance, nothing existing changes by accident, tests, cost, docs, evidence in the PR); how to take an API
  change a song asks for (find the workaround and its cost, check it does not exist already, extend before adding,
  design the text first, close the loop, keep old names, prove it on the asking song); lessons from running the loop.

### The shared machine

- `ismail.machine`, the governor for one computer shared by many sessions (2026-10-02: six sessions stacked heavy
  jobs on a laptop GTX 1080 until it sat at 92 C pinned at 139 MHz and the user stopped everything). Op
  `machine_status` (and `python -m ismail.machine`): GPU heat, clock and throttle reasons (an idle card at 139 MHz is
  not trouble; a thermal bit or 85 C is), CPU, free commit, and every heavy job running in any session. Heavy jobs
  take slots on a board in `songs/_machine/`: one GPU job and two CPU jobs machine-wide, a live engine on air holds
  one. render, separate (GPU slot when it runs on CUDA), mimic_measure, instrument_fit, track_fit and live_parity
  take a slot and refuse with what is running, whose it is, when it should end, and what to do; a render whose
  memory estimate does not fit the free commit is refused instead of dying. Commands outside ismail run in a slot
  with `python -m ismail.machine run --gpu|--cpu -- <command>` at below-normal priority. Heavy jobs cap numeric
  threads at 2. The test suite takes a slot too.
- The governor also refuses a new CPU job while the CPU is 80% busy or more over 2 s, whoever is using it, and names
  the top processes: most load on this machine is not on the board (the desktop app, a node server). The board shows
  the top processes.
- Skill: "The machine is shared" is a non-negotiable (check before anything over a minute, one heavy job of your own,
  a hot GPU is not a free CPU, size jobs to the question, no sleep-poll loops, never leave heavy jobs running
  untold); development.md: touched tests locally, the full suite in CI; announcements never ask for work.

### Roles and collaboration

- Skill: "Your role, and where things live": making music is the default role and writes only inside
  `songs/<slug>/` (no edits to `ismail/`, `skills/`, tests or other songs, no git in the ismail repo); a missing
  capability is built in the song and listed in its `HANDOFF.md`; one folder layout for every song; song
  checkpoints with a git repository inside the song folder. The `guide` op opens with the same rule.
- New `references/development.md` for changing ismail itself (only when the user asks): a worktree per topic, the
  collaboration must-haves (what is not yours is not touched, nothing unmerged is deleted, no stash in a shared
  repo, proof and docs in every commit, the user merges), migrating from a song's `HANDOFF.md`, its format,
  and studio/live parity: every engine change says which side it touches, how live follows, and what proves it.
- `live.md`, from a 40-minute blues set: only proven sounds go on air (no voice written during set prep and never
  fitted or ear-tested), first sound within minutes, never downgrade a sound in silence, a song plays live through
  `live_load` and is never rebuilt by hand, and anything that writes runs on a copy, never in another song's folder.
- `blind-tests.md`: ear-test pages are always hosted on localhost and opened in the app's browser pane, take answers
  with a Submit button that writes them to a file, and are checked in the pane before the user sees them.
- Skill brought up to date with the live parity work: phrase voices no longer run an amp inside the voice (a
  guitar is `electric` with its rig on the track, live as in the studio); the performer signature takes `beat0`;
  how to write a performer's expression in the studio (`inst.lane.<name>` automation); the rig effects, presets,
  `electric`'s half-step-down tuning and `kit70`'s drum map; five rules for a voice that renders the same in a
  window, live and in the whole song (from `songs/tambopata`); `live_parity` for checking a song on a deck; what
  `live_status` and a deck's "not live" list now say; render speeds of the library performers. Fixed: the limiter
  ceiling (-1.0 dB for mp3 everywhere), the eye-exam page (Submit, not a copy button), wah as an effect sweep, not
  a lane, and where the engine looks for a song's voices. SKILL.md: call `guide` before writing a measuring
  script. The `guide` op's live text matches.
- The migration loop (`references/development.md`), the dev role's standing job: intake with
  `python -m ismail.handoffs` (every handoff section new or changed since the last mark, `--full`, `--mark`),
  triage into `songs/_migration/LEDGER.md`, the user decides, build on a branch, announce merges to every ismail
  session, the song closes the item. SKILL.md tells song agents their handoffs are read and how to close an item.
- The intake names sections by their heading path (one subheading under two elements stays two sections), skips
  caches and backups, and lists a reorganized handoff's old text only with `--all` (a section whose words were
  already in the file is "moved", not new).

### Guitar rig and performers

- Rig effects (`ismail/rig.py`): `fuzz` (Fuzz Face bias shift), `univibe` (four-stage LDR phaser with lamp lag),
  `amp` (Marshall-style tone stack after Yeh and Smith 2006, push-pull power stage with sag), `cab` (min-phase
  cabinet with a mic blend), `rotary` (Leslie with ramping rotors), `tape` (head bump, wow, flutter, hiss), `wah`
  (resonant band-pass). `fx_help(type=...)` documents each. Live runs them as block-by-block twins (below).
- Performer voices in the studio: a voice module with `perform()` and no `voice()` renders a whole part at once
  (strings that ring on, legato, slides, whammy), with expression lanes from automation `inst.lane.<name>`. Live
  already played them from clip `expr` lanes; one mechanism now: a deck turns a song's `inst.lane.*` automation
  into its clip's `expr`, and `live_load` marks a song's performer tracks (decks had played them note by note).
- Library voices `guitar/electric` (electric guitar or bass: waveguide strings, pickup comb and resonance, lanes
  for bend, vibrato, mute, slide, level) and `drums/kit70` (a 1970 kit as modal resonator banks), both performers,
  fitted in a late-60s guitar record study (20 of 22 single lead notes passed a blind exam). Presets
  `strat70_lead`, `strat70_rhythm`, `strat70_rotary`, `pbass70`, `kit70`; each voice's INFO `rigs` holds the fx
  chain its presets were fitted with, and `voice_help` prints them one line each.
- Skill: `references/blind-tests.md` (the eye exam and the blind exam: fair clips, reading the answers, the
  song-level checks single notes miss), and the guitar study's lessons in sound design (register first, harmonic
  profile, stem bias, rig order, fast rig fit), composition (phrase placement, band feel, bends to chord tones),
  recreate (straighten a drifting record, round-trip every sensor) and listening (spectrogram pairs; long-window
  numbers are blind to fakeness).

### Live, from a one-hour set

- DJ kit, `ismail.live.djkit`: step strings to notes, cycles built bar by bar inside one clip, notes on another
  metric grid, effect moves (sweep, throw, gap, pump) addressed by effect type, and a `Set` that logs every call
  with the clip ids per section so a queued section can be cancelled.
- `live_fx`: `index` may be the effect's type (`'filter'`, `'delay:2'`); `moves=[...]` schedules a whole
  choreography in one call; `clear=True` cancels a track's scheduled moves (each param holds). A sweep can target
  a chain scheduled with `live_track(fx=..., at=...)`; the swap drops only the old chain's sweeps and keeps volume
  moves (it used to drop everything, a loaded song's volume curve included).
- One `at` vocabulary: `now` and `asap` mean the same in every live op.
- Problems between calls (a note dropped as too loud, a warm-up error, a stalled device) are added to the next
  reply of any live op. `live_status` shows each level's loudest over the last 10 s and a STALLED line when the
  device stops asking for audio.
- `live_start` names other engines still running on the machine (a registry in `~/.ismail/live`); `live_stop`
  waits for the engine to exit and kills it with its workers when a dead device would hang it.
- Skill (`references/live.md`): reading the audience, your latency, the pre-flight, dynamics with the kit, a set's
  folder layout, playing for a screen recording.
- Fix: the live engine crashed at startup since the rig effects were registered (its effect warm-up tried to
  build a live block for studio-only types); it now skips them, and they bake in the workers as before.

### Live and studio parity

- Fix: a note still sounding when a window starts (a drone, a pad, a held string) now plays in a studio render of
  a bar range and on a deck loaded with `bars`; both dropped it, and the deck said "silent in range". A note that
  rings on at least a beat into the window comes in on its first beat.
- A deck loaded straight on air is held off air until a whole bar of it is rendered, then goes on air on that bar
  line; it used to go on air with nothing rendered and lose its first bars in silence. `live_status` shows the
  hold, and the next reply says when it slipped and when it went on air.
- Renders go to the workers earliest-needed first, from an engine-side list, and a render no queued clip wants any
  more is dropped before a worker spends time on it. A clip queued for later renders its first pass from the
  moment it is queued, so loading ahead buys render time.
- Notes that never sounded because their render came back too late are counted (`live_status`: "never sounded")
  and said per track in the next reply; the late counter used to read 0 while bars played silent.
- Warm-ups render a short tail: each one had rendered 8 s through the track's baked rig on every worker, ahead of
  every real render, and a 23-track deck spent half a minute warming up.
- Fix: a deck's cue flips (`live_deck(cue=...)`, a transition's on-air) now land on the bar line the listener
  hears; they came about 90 ms early.
- The guitar rig runs live: fuzz, univibe, amp, cab, rotary, tape and wah have block-by-block twins
  (`ismail/live/rig_blocks.py`) running the studio kernels, held to the studio by `tests/test_live_parity.py`.
  They were baked into every rendered note: a guitar rendered at 0.8x realtime and a deck of Crossroads never got
  on air (219 notes lost); now it plays from its first bar with nothing late and the mixer at about 31%. Per-note
  baking also stacked one amp's hiss per note (+7 to +9 dB on the noise floor; now equal to the studio's), and a
  song with `tape` on a bus can load on a deck. Rig params move with `live_fx` (wah `pos`, rotary `speed`).
- Studio rig changes so a live twin can be exact (all inaudible): amp and tape hiss draw one noise stream per
  channel (a different noise, same level); tape wow is a causal running delay (the output sits 14 samples later);
  auto-wah follows its recent peak instead of the whole part's 98th percentile (within 0.1 dB).
- Performer voices play live in bar chunks: each bar renders with the second of the part before it as context
  (held notes from their real start), cut and crossfaded at the bar line; a looping clip takes context from its
  previous pass, a deck's section from the 8 beats before its window (a held note is no longer struck again on the
  window's first beat). Crossroads on a deck against the studio: envelope correlation 0.999-1.000 and bands
  within 0.5 dB on bass, rhythm, lead and drums (0.96-0.99 before; the lead lost 21 dB at 125 Hz at the window
  edge). kit70 renders at 5x realtime instead of 0.5x (no 8 s tail per hit).
- `electric` and `kit70` key their randomness per note on the song beat (`perform(..., beat0=)`), so any slice of
  a part, a studio bar range included, plays exactly as the whole part. One generator drawn note after note gave
  every slice a different performance (a kit's hi-hat changed timbre with the number of notes). Studio renders of
  songs using them get a new realization of the same humanization. `skills/.../sound-design.md` says how to write
  a performer this way.
- Deck notes keep 10 significant digits (6 rounded long sections' timing).
- A track whose amp or tape hisses keeps hissing through rests up to 8 s before it sleeps, as in the studio.
- A big `live_queue` no longer stalls the mixer: the batch's render estimates and event groups are planned before
  the engine lock is taken, the scheduler places at most 128 events per pass (earliest first), everything alive at
  engine start is frozen out of the garbage collector's full sweeps, and the GIL switch interval is 1 ms. An
  8000-note queue: the mixer's longest wait for the lock 256 ms -> under 25 ms, collector pauses 133 ms -> 20 ms,
  mixer peak about 1000% -> 130-180% of real time.
- The live mixer keeps every effect's state out of denormal floats (a fuzz left in silence decayed into them and
  took a guitar chain to 100% of real time), and a track whose amp only hisses goes dormant like a silent one.
- A standing parity check: op `live_parity(song, bars)` renders the bars in the studio and plays them on a silent
  engine of its own, then compares each track, bus and the mix (level, envelope, octave bands, residual), judged
  from the window's second bar. `tests/test_live_song_parity.py` holds every instrument type and library voice to
  it: voices that are not performers match the studio sample for sample, performers by ear.
- Synths and drums seed their random phase and noise on where a note sits in its bar, not where it sits in the
  render buffer: a studio render of a bar range now sounds as those bars do in the whole song, and live plays it
  sample for sample (it was a different take of the noise and phases each time). Studio renders of synth and drum
  parts get a new realization; nothing else changes.
- Code and mimic voices get each note whole even when a render window ends first: a voice whose noise draws or
  filters depend on the length it is given (the `sfx` voice) sounded different near a window's end and live.
- Fix: an engine rendering inline (`workers=0`) now finds a loaded song's sampler sounds; its samplers were silent.

## 0.2.0 (2026-09-30)

### Live

- **Live engine** (`ismail/live/`): a separate process per folder plays a queue of clips in real time while the
  agent edits it. Ops: `live_start`, `live_stop`, `live_status`, `live_track`, `live_bus`, `live_fx`,
  `live_queue`, `live_cancel`, `live_view`, `live_listen`, `live_record`.
- Clips loop until replaced; launches quantize to the beat, bar or phrase (`next_4`, `bar:N`, `after:<id>`,
  `after:#k` for a whole arc in one batch). The reply gives each clip's landing bar and the runway.
- Render ahead: worker processes render each note or phrase before the playhead (identical notes render once);
  a clip that cannot render in time lands later and the reply says so.
- Effects, send buses, sidechain, duck and vocoder from live tracks; `live_fx` ramps any automatable param.
- Safety chain on every output: trim, loudness rider, lookahead limiter, ceiling, set from the environment.
- `live_listen` analyses the last bars played, a deck, or a finished `live_record` take.
- Decks: `live_deck`, `live_load` (a whole ismail song on a cued deck), `live_transition` (blend, bass swap,
  filter, cut), a DJ strip per deck (LR4 isolator, filter knob, fader, transpose).
- Studio and live: studio code is the source of truth. Effects run live as block-by-block twins
  (`fx_blocks.py`, `dsp_blocks.py`) held to the studio versions by `tests/test_live_parity.py`; an effect with no
  twin is baked into each rendered note or phrase. Voices with `perform()` play whole phrases live, with `expr`
  lanes (bend, vibrato) on clips.
- mimic profiles and code voices play live.
- Install `.[live]` (sounddevice) to play to speakers; `device='none'` runs without audio out.
- A deck plays a song the way it renders: a bus that tracks play through keeps its reverb or delay as an insert
  (dry passes; live buses had been wet-only, which took the drums out of a song with a reverb on its drum bus),
  and the song's automation comes over (fx params and track and bus volume as ramps, instrument params rendered
  with the notes, the master fade), repeated every pass on a looping deck. A track with instrument automation
  renders its section as one event, sent to a worker one pass ahead.

### Measurement

- `analyze_grid`: the snare on 2 and 4 votes for bar 1; reports the record's tuning offset and swing.
- New ops: `ref_retune` (retuned analysis copies of an off-pitch reference), `analyze_swing`, `analyze_kit`
  (the pieces of a drum kit and each one's pattern, by NMF), `analyze_sections`, `levels_from_ref` (faders from
  the reference's stem balance).
- `analyze_sections` flags a build (2 dB or more under the climax on average, peaking within 3 dB of it), not a
  drop that goes on at the same level.

### Voices

- mimic: instruments measured from recordings (`mimic_measure`, the `mimic` instrument type), with leave-one-out
  checks; wandering vibrato, swells, measured room, attack maps, sympathetic strings.
- Voice library in family folders; measured string profiles ship built in.

### Skill

- Live reference (`references/live.md`): running a set as a DJ loop, small edits over whole sections, a runway
  before every question, metric modulation for style changes at a fixed tempo, performers and phrase voices.
- Recreation lessons: measure tuning, swing, kit pieces and fader balance; a record's drum kit as measured
  models; phrase length before tiling; one-part-at-a-time A/B.

## 0.1.0 (2026-09-26)

First public release: an agent-operated DAW with a CLI, an MCP server and a Python API. Notes, patches,
effects and automation in as text; levels, spectra, drum lanes, piano rolls, chords, structure and stored
reference comparisons out as text. Code voices, drum synths, samplers, stem separation, instrument and track
fitting, the optional music-video pipeline, and the agent skill.
