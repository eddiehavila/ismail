# Playing live

The live engine plays a queue of clips in real time while you edit it: a jam with the user, a set, a stream,
music that answers something happening now. A finished song is still made offline (render, master); a live set
is performed, and `live_record` keeps a take.

You are slow. A turn takes 5 to 30 seconds, which is 4 to 20 bars. So you never play notes as they happen: you
queue clips that loop until replaced, pre-program arcs, and schedule sweeps. Everything faster than your turn
lives inside the clips and the ramps.

The engine is fast; you are the latency. A clip lands at the next quantize point and renders 3 to 80x realtime,
so the delay between a decision and the sound is mostly the tokens you write and the thinking before them. A
fader move, a filter sweep, one layer in or out, a fill or a new pattern for one part costs seconds; a whole new
section costs a minute or more. Compose whole sections only for real changes, and steer with small edits.

## The loop, live

0. **Set Sheet** (in your reply, before any tool call): the Session Sheet plus an **arc**: which clip plays on
   which bars, what changes at each boundary, and how long the queue runs before it needs you (the runway).
1. **Rig**: `live_start(project, bpm)` (tempo is fixed per run), `live_bus` for a shared reverb, then one
   `live_track` per part with its instrument, `fx` chain and `sends`. A track plays one clip at a time: to layer
   two patterns on one sound, use two tracks.
2. **Queue the arc in one `live_queue` batch.** Chain with `at='after:#k'` (item k of the same batch) and loop
   counts; phrase starts with `next_4` / `next_8`. End on clips that loop `forever` or on a final chord. The
   reply's landing bars are the truth: when a clip is "moved" later, its first notes needed the render time.
3. **Sweeps and builds**: `live_fx(target, index, params, ramp_beats, at='bar:N')`, with N taken from the queue
   reply. `index` may be the effect's type (`'filter'`, `'delay:2'` for the second delay), which survives edits
   to the chain. Ramps on one param form a schedule: a later ramp does not erase an earlier one. A snap then a
   sweep = two moves, the second a beat later (`bar:N.25`). A whole cycle of moves goes in one call:
   `live_fx(moves=[...])` (the DJ kit builds them). `at` takes the same words everywhere (`now` = `asap`).
4. **Listen every turn**: `live_status` (levels per track and bus, runway, late events, underruns, safety gain
   reduction) and `live_listen(bars=4, view=...)` (on the live output `bars` is a count of the last bars; a
   `[a, b]` range only works with `recording=`). Write the Listening Report lines as for a render.
5. **Change on phrase boundaries** (`next_4`, `next_8`), not mid-phrase, unless the cut is the point.
6. **Record** with `live_record`: the take starts on a downbeat and has a `.json` sidecar;
   `live_listen(recording='rec_....wav', bars=[a, b])` analyses it in the set's bar numbers, after the set too.
7. **Ask the user** what they heard, as always, and log it in `notes/feedback.md`.

Write a short set as a script, `songs/<slug>/set.py`, like a `build.py`: rerunnable, and the notes and arc are
readable later. A long set with feedback between parts runs from a control module instead (see Running a set). `examples/disco_set.py` (in this skill) is a worked example (intro, groove, breakdown with a filter snap and
sweep, drop, ending; 17 clips in one batch).

## Sounds first

A live set is only as good as its sounds, and the rules of the main skill hold here too: no genre parts on bare
sprite patches. For a style with a reference, match the sounds offline first (`references/recreate.md`: drums,
bass and lead one at a time, the user's ear on each A/B) and take the matched instruments into the set; a set of
console sounds is not rescued by arrangement. Set faders from the reference's stem balance (`levels_from_ref` offline,
then carry the faders into the set), and swing from `analyze_swing`, not by feel.

**Only proven sounds go on air.** That means library voices with their fitted rigs, measured mimic profiles, and the
instruments of finished songs. A voice written while preparing the set and never fitted to a recording or ear-tested
does not play live. In a 40-minute blues set, a 12-string and a harmonica built from textbook numbers, with their
references downloaded and separated but never used, drew "sounds like a kids piano... we have no guitar style,
nothing". When the set needs an instrument the project does not have (an acoustic guitar, a harmonica), say so
before the set and offer the choice: measure it first from the references (mimic, an ear test), or play the
nearest proven instrument and name it.

**First sound within minutes.** Open with a short arc built from proven parts, then build the later sections while it
plays and the audience reacts. The same blues set spent 40 minutes preparing seven eras before the user heard a
note, and one sentence of feedback condemned all of it.

**Never downgrade in silence.** When a constraint forces a worse sound (a fitted guitar rig too slow to render live,
a voice that fails its warm-up), say so before it plays and offer the options: fewer tracks on that rig, a simpler
chain, a pre-rendered clip. The blues set swapped the fitted guitar for an untested one without a word, and the
user caught it by ear.

**A song plays live through `live_load`, never rebuilt by hand.** A hand port drops the song's automation (a growl's
filter sat open at 20 kHz), its buses, its master chain and its held notes, and then it "sounds nothing like the
original". Load the song, or a `bars` window of it, on a deck. When `live_load` refuses (a bus effect with no live
version) or cannot keep up, that is an engine gap: measure it (studio render against a silent deck, per track and
band) and write it in the song's `HANDOFF.md`.

**Other songs stay untouched.** Loading a song on a deck reads it. Anything that writes (a test render, a parity
check) runs on a copy in your own song folder: a render in the original's `proj/` overwrites its `latest.wav`.

## Running a set: the DJ loop

A long set (a DJ set, a party, a 30-minute jam) is a loop between you and the audience, and the user's messages
are the audience. Later the audience may be a text stream from other devices (motion on the dance floor from a
camera, facial expression categories); treat it the same way.

- **Read the room.** When the audience is into it, lean in: keep the feel and add an element or two, build, take
  it down, drop. When it goes flat or repetitive, move on: a switch-up, a breakdown, a new song.
- **Think in energy, not song form.** Bring elements in over time (a percussion layer, 808 slides, string stabs,
  a riser), strip them for a breakdown (drums and bass out, filter the keys down, a snare roll into the last
  bar), then drop with more than before (double-time hats, the hook instrument). Every 16 to 32 bars something
  should change.
- **Small edits by default.** Steer with one-element changes between bigger moves: `live_track(volume_db=)`,
  `live_fx` sweeps, `{track, stop: true}`, a one-bar roll or fill clip (`loop: 0`), one part's new pattern.
- **Queue a runway before every question.** Whatever is queued loops while the user answers, and answers can
  take minutes (a static loop ran 9 minutes once). Before asking, queue changes that keep moving for longer than
  you expect to wait, and near the end of a timed set queue a fallback ending, so the set lands on time without
  you. New clips replace queued ones on their tracks, so the runway costs nothing when you override it.
- **Keep a control module, not one script**, laid out as in "A set's folder" below, and build it on the DJ kit
  (`ismail.live.djkit`): its `Set` logs every call with the clip ids per section, and its note and move builders
  replace the helpers every section used to rewrite.
- **Check after every addition**: the new track's level (a track reading -120 dBFS while "playing" is silent,
  see below), the master `limiter` (layers add up: pull faders when it reads more than ~3 dB), late events.

Changing style at a fixed tempo: the tempo is fixed per run, so change the feel by **metric modulation**. At a
house tempo T, 1.5T is a triplet grid: trap at 141.9 over G-funk at 94.6, with 6 trap bars = 4 house bars and
every trap beat = 2/3 of a house beat (write in trap beats, multiply by 2/3). A breakdown whose hats move to
triplets first announces the new grid; then drop. 2T and T/2 (half-time) work the same way.

Phrase boundaries: `next_16` and friends count from bar 1 of the run, not from where a playing part's phrase
began. When a new part must line up with a 16-bar phrase that started on bar 37, use `bar:<37 + 16k>`.

### Reading the audience

Learned from a one-hour set steered by one listener; the same reading applies to any audience feed.

- **They judge change over time, not static balance.** "It didn't really change much" was about contrast, not the
  mix. A drop lands when the bar before it is emptied: the one that worked measured -27 dB with no sub in the bar
  before, then -19 dB with the sub 30 dB up, plus a silence gap. Meter the bar before a drop against the drop and
  aim for 6 to 8 dB of difference and a clear swing in the sub band.
- **Dynamics come from effects, not EQ and not more layers:** delay throws, reverb washes, filter sweeps, stutter
  gates, bitcrush, sidechain pumping, and silence. Faders and EQ are housekeeping; effects are the performance.
- **Invented melodies fail; derived ones win.** A generic pentatonic acid line was "all over the place". A call
  taken from the reference's vocal, callbacks to earlier sections' bell, cello and violin lines, and the opening
  progression reused all worked. New melodic material comes from the reference or from earlier in the set.
- **Measured beats guessed, and the listener hears it.** A guessed gnawa groove (four strokes on clean triplets)
  was "cool"; the measured one (three strokes at 0, 0.32 and 0.74 of a beat, its timbres fitted from the stems)
  was "I love it... closer". Measuring mid-set is fine at idle priority.
- **Feedback is short and directional** ("busy", "more bass", "move on", "sounds like shit"). Answer with one or
  two named moves, not a menu. "Move on" means a new section, not a tweak. Something bad comes out at once (the
  acid line was gone within seconds), then the bigger fix follows.
- **Ask about the culture, not the knobs:** "does it read as gnawa?" got a useful answer where a technical
  question would not.
- **Endings are emotional arcs** ("full circle", "crescendo", then peace). Plan the last 15 minutes early as an
  arc, but keep the ending swappable: do not queue it until it is close.

### Your latency is the risk

A section written from scratch took 5 to 10 minutes; a request for a new ending arrived after the queued section
it replaced had already started.

- When a message arrives, read `live_status` (heard bar, runway) before writing anything, and cancel what no
  longer fits: `Set.cancel('<section>')` takes back the clips logged for it.
- Build each move from the kit so the visible work is short calls, not long file writes.
- Judge a sparse part by `live_status`'s "max 10 s" level, not the snapshot: a vocal call read -70 dB when the
  snapshot fell in its rest.

### Dynamics with the kit

```python
from ismail.live.djkit import Set, steps, per_bar, notes, metric, sweep, throw, gap, pump, with_gain
S = Set('songs/<slug>')
S.start(84)                                       # set loudness + the pre-flight lines
S.track('kick', instrument={'type': 'kick'}, fx=with_gain([{'type': 'filter', 'cutoff': 18000}]))
r = metric(126, 84)                               # house beats on the 84 grid
S.q([{'track': 'kick', 'notes': notes(per_bar(24, lambda b: [] if 16 <= b < 20 else steps('X...X...X...X...')), r),
      'bars': 16, 'loop': 'forever', 'at': 'next_8'}], section='s04_house')
o = S.next_boundary(start=41, every=16)           # the next cycle bar that can still land in time
S.moves([sweep('kick', 'filter', 'cutoff', 400, 30, o + 8), gap(['kick', 'bass', 'stab'], o + 16),
         sweep('kick', 'filter', 'cutoff', 18000, 0, o + 16), throw('stab', at=o + 15.5), pump('pad', o + 16)])
```

`steps` turns step strings into notes (X x o g, swing, lag), `per_bar` builds a cycle bar by bar inside one clip,
`notes(..., ratio)` places a feel on another metric grid, and the move builders (`sweep`, `throw`, `gap`, `pump`)
return `live_fx` moves addressed by effect type. `with_gain` puts a gain first in a chain, which gaps and fades
use.

## A set's folder

```
songs/<slug>/
  project.json          project_new; the engine runs in this folder
  SET.md                the Set Sheet and the running order, kept as the set goes: one row per section
                        (# | name | start bar | grid, e.g. 84 or 126 = 1.5x | key | tracks added / stopped | what
                        the user said that caused it)
  set/
    ctl.py              plumbing only, no notes: a djkit Set, the rig helpers
    s01_triphop.py      one module per section, numbered in play order, named by style: rig() makes its
    s02_minimal.py        tracks, clips(start) returns the queue batch, choreo(start) the moves, run(start)
    ...                   does all three; seeded, so it regenerates exactly
    setlog.md           written by the kit: every call, landing bars, clip ids per section
  voices/               code voices made for the set; each docstring cites the measurement it came from
  ref/
    SOURCES.md          per reference: title, URL, date, who supplied or approved it, "analysis only"
    <name>.wav          the reference
    <name>/             its analysis project (excerpt, stems)
  work/                 measurement scripts and their saved output (groove.txt, timbre.txt): voices and
                        sections cite these numbers
  notes/feedback.md     bar or time | the user's words verbatim | what changed | the measured result
  takes/                live_record wavs and sidecars, when recorded
```

- **A rebuilt part gets a new track name with the section number** (`gmb2` -> `gmb3`), and each section module
  lists the old tracks it stops. To reuse a name, `live_fx(track, clear=True)` first: scheduled moves outlive
  clip changes.
- Temp files go to your scratchpad, not `set/`. Measurements are saved as files, not only printed.

## Performers and phrase voices

A code voice renders one note at a time, so legato, slides and bends between notes need another shape.

**Performer voices.** A voice module with `perform(notes, total_n, sr, bpm, lanes, **params)` and no `voice()`
plays a whole part (a guitar with hammer-ons and slides, strings that ring on, a kit that resonates). `live_track`
detects it, and live renders it a bar at a time, each bar with the second of the part before it as context, cut and
crossfaded at the bar line, so legato, slides and ringing strings carry across bars; a looping clip takes its
context from the previous pass, and a deck's section from the 8 beats before its window. A voice that keys its
variation on the song beat (`electric`, `kit70`) plays live as in the studio render, sample for sample. Bends and
vibrato come from the clip's `expr` lanes, `{"bend": [[beat, semitones], ...], "vib": [[beat, cents], ...]}` with
beats from the clip start; the voice's INFO lists its lanes.

**Phrase voices** are the older trick for a performer that is not written that way: make **one note = one whole
phrase**. The voice takes a `phrases` param, `{"<velocity>": {"notes": [...], "bend":
[[beat, semitones], ...], "vib": [[beat, cents], ...]}}`, and the note's velocity picks the phrase; the note's
pitch can transpose it against a `root`. Inside, call the performer on the phrase's notes and lanes and run any
offline effect chain on the result. Phrases render once and are cached, so they can be slow (a physical guitar
with an amp rig renders at ~1 to 3x realtime).

The instrument, params included, is captured when the track is made. After you add a phrase to the dict,
re-send `live_track(name, instrument=...)`; a note whose phrase is missing plays silence.

## Decks: prepare the next part while this one plays

A deck is a group of tracks with a DJ strip: fader, 3-band isolator (250 Hz / 2.5 kHz, a band at -40 dB or
less is killed), a filter knob (-1 low-pass .. 0 off .. +1 high-pass) and transpose. A cued deck plays off the
air; only you hear it, through `live_listen(deck=...)`.

1. `live_load(deck='B', song=<ismail project folder>, bars=[a, b])` puts a song (or a section) on deck B: its
   tracks, effects and buses come over as `B.<name>`, its notes play at the house tempo (re-rendered, not
   stretched), with its automation (effect sweeps, volume curves, instrument filter and pitch moves, the master
   fade) and its group buses. It is cued while another deck is on air. The reply lists what did not come over
   (placed audio clips, the master effect chain, effects whose source track was muted). A track with instrument
   automation renders its whole section as one event: load the deck several bars before it plays. A performer
   voice's studio lanes (`inst.lane.bend` ...) arrive as its clip's `expr`, so a guitar keeps its bends. A drone
   or pad already sounding at the window's first bar comes in on its first beat, as in a studio render of those
   bars.
   A deck loaded straight on air waits off air until a whole bar of it is rendered, then goes on air on that bar
   line: load too close and the audience hears it start bars late, and the next reply says so. A big song (20+
   tracks) wants 10 to 20 bars of lead; load it while the other deck plays, and keep it cued.
   Before a set, A/B each song on a deck against its render (a silent engine, `live_start(device='none')`, plus
   `live_record`): a drum bus that had lost its dry signal left only the bass audible, and only the user heard it.
2. Listen to deck B while deck A plays; fix it there (`live_deck` eq/transpose, `live_fx` on `B.<track>`).
   Key-match with `live_deck(transpose=...)` (drums stay).
3. `live_transition(to='B', style=..., bars=16, at='next_8')` queues the whole mix: `blend` (B up without bass,
   bass swap half-way, A out), `bass_swap`, `filter`, `cut`. It starts at the first boundary after B is
   playing, puts B on air, and stops A when it ends. The reply is the timeline; `live_status` shows each deck's
   fader and eq as they move.
4. Watch `live_status`'s mixer load: two full songs is about 50%; above ~70% risks dropouts.

Put the swap where the incoming deck's bass plays: a 16-bar section whose loop restarts on a sparse bar leaves a
hole at the bass swap. Pick `bars` so the section starts on its downbeat hit.

## Rules

- **Runway before a slow job.** Before anything that takes time (`mimic_measure` 25 to 60 s, `instrument_fit` and
  `track_fit` minutes, a long think), queue an arc longer than the job, with change in it (a clip with a fill
  in its last bar, an evolving chain, a ramp), not one bar repeated.
- **Variation inside the clip.** A 4-bar clip with a fill in bar 4 beats a 1-bar clip plus four tool calls.
- **Balance with faders.** Read the per-track levels in `live_status` and set `volume_db`. The safety chain is
  a floor, not a mixer: its limiter and rider should read 0 dB.
- **Live output is quiet by default** (trim -6 dB, sustained cap -16 dBFS rms, ceiling -1 dBFS; about -21 to
  -23 LUFS for a balanced mix). That is too quiet for a listener at a normal volume: one user heard "nothing".
  For a set, start the engine with `ISMAIL_LIVE_TRIM_DB=4` and `ISMAIL_LIVE_CAP_DB=-12` in the environment of
  the process that calls `live_start` (the engine inherits it): about -16 LUFS. Then keep the limiter near 0 dB
  with faders.
- **Sounds you are unsure of**: try them on a muted or quiet track (`volume_db=-40`, then fade with a ramp on a
  gain fx) rather than straight onto the main part.
- **Tempo change** = `live_stop`, then `live_start` with the new tempo (a gap). Inside a set, change the feel
  with metric modulation instead (above).
- **Gliding parts** (a portamento synth lead, a Moog bass) belong on the synth engine (`mono`, `glide`) with
  measured harmonics (an `additive` osc or a fitted filter): mimic renders each note alone and does not glide.
- **Pre-flight.** `live_start` names any other engine still running on the machine (a forgotten set held a
  Bluetooth speaker for hours and froze the next one): stop it unless it should play. After the first clip,
  check that the heard bar moves; a `STALLED` line in `live_status` (or in any reply) means the device stopped
  asking for audio: `live_stop`, then `live_start`, or another device. `live_stop` waits for the engine to exit
  and kills it with its workers when a dead device would hang it.
- **Heavy jobs before the set.** Stem separation during a set caused 1,654 underruns; measurement scripts at idle
  priority were fine.
- **Mixer budget.** About 18 tracks in a crescendo peaked at 71% of real time and dropped out. Share reverbs on
  buses (a reverb per track is expensive) and stop parts you no longer hear; removing tracks barely helps.
- **A new voice's first pass**: check its level at once (a first qraqeb sat 30 dB under the part it answered). A
  single event above +12 dBFS is dropped as a broken voice, and the next reply of any op says so ("NEW since
  your last call"). A code voice's randomness is seeded by pitch and velocity: vary them for stroke variety.
- **Chain swaps and sweeps.** `live_fx` at or after a scheduled `live_track(fx=...)` swap targets the new chain;
  the swap drops the sweeps written for the old one and keeps volume moves. A sidechain or duck source must be a
  live track before the chain that reads it.
- **Recording a long set** takes disk: 24-bit stereo is ~16 MB a minute (~480 MB for 30 minutes). Check free
  space first, or skip the take and use `live_listen` on the live output.

## Playing for a screen recording

When the session itself is the show (the viewer sees your turns and hears the set):

- Each turn, one short line: what is queued and which bar to listen for what ("bar 97: the kick drops out, the
  guembri goes into the delay; bar 105: the drop").
- One concrete question at a time, with the default you will take if there is no answer.
- Visible work stays short: kit calls, not long file writes.

## What is and is not live yet

Live: every instrument type including mimic profiles and performer voices, every effect, send buses,
sidechain/duck/vocoder from live tracks, ramps on every automatable fx param.

Effects run two ways. An effect with a live processor (every built-in type today, the guitar rig included) runs
block by block on the mixer and matches the studio version (held by tests): a wah's `pos`, a rotary's `speed`, a
univibe's `rate_hz` move with `live_fx` like any filter. An amp or tape with hiss on keeps hissing while its track
plays, as in the studio, and sleeps with the track when its notes stop. An effect that exists only in the studio
(a new type nobody has written a live twin for) is **baked**: the render workers run it on each note or phrase
before the mix. `live_status` marks it `(baked)`. A baked effect cannot be moved with `live_fx`, restarts its LFOs
and tails per note, and hears each note alone (a fuzz on a chord distorts each note, not the sum). Everything up to
the last studio-only effect in a chain is baked, so order is kept; a sidechain or duck cannot sit before one, and a
bus cannot bake at all (put the effect on the tracks).

Not yet: master-bus effects (the safety chain is the master), vocoder modulators from sound-bank sounds,
instrument-param automation on your own live tracks (a deck's song has it; otherwise use fx params, or expr
lanes on a performer), tempo changes inside a run, placed audio clips and the master effect chain on a deck.

## Numbers worth knowing

- Output trails the mix by ~96 ms (a fixed 4096-sample alignment budget for effect lookahead, plus the safety
  limiter). Tracks stay aligned with each other; `live_listen` and recordings compensate.
- A chain may need at most 4096 samples of lookahead along track + bus (a hall is 1024, a limiter its
  lookahead, oversampled distortion 20). The error says which effect to drop.
- A replaced chain rings out (its reverb tail keeps sounding) for up to 12 s.
- `live_status` shows each track's render speed ("renders 3x realtime"). Drums and code voices run 20 to 50x,
  synths 4 to 7x, mimic 1 to 3x (low notes are the slowest: more harmonics). A clip's first pass waits for its
  renders, so the reply moves slow first launches a bar or two later; every later pass reuses them, and
  identical notes (a repeated chord) render once. Phrase voices (a whole guitar phrase through an amp rig) run
  ~1 to 3x: queue them a phrase ahead.
- `live_start` takes ~20 to 30 s: the render workers warm up every instrument kind and every mimic profile in
  the folder before it returns, so the first clips land on time.
- Mimic profiles come out quiet next to synths and code voices (about 9 dB): check their level in
  `live_status` and raise `volume_db` before judging the balance.
