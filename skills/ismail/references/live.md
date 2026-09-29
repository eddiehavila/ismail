# Playing live

The live engine plays a queue of clips in real time while you edit it: a jam with the user, a set, a stream,
music that answers something happening now. A finished song is still made offline (render, master); a live set
is performed, and `live_record` keeps a take.

You are slow. A turn takes 5 to 30 seconds, which is 4 to 20 bars. So you never play notes as they happen: you
queue clips that loop until replaced, pre-program arcs, and schedule sweeps. Everything faster than your turn
lives inside the clips and the ramps.

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
   reply. Ramps on one param form a schedule: a later ramp does not erase an earlier one. A snap then a sweep =
   two calls, the second a beat later (`bar:N.25`).
4. **Listen every turn**: `live_status` (levels per track and bus, runway, late events, underruns, safety gain
   reduction) and `live_listen(bars=4, view=...)`. Write the Listening Report lines as for a render.
5. **Change on phrase boundaries** (`next_4`, `next_8`), not mid-phrase, unless the cut is the point.
6. **Record** with `live_record`: the take starts on a downbeat and has a `.json` sidecar;
   `live_listen(recording='rec_....wav', bars=[a, b])` analyses it in the set's bar numbers, after the set too.
7. **Ask the user** what they heard, as always, and log it in `notes/feedback.md`.

Write the set as a script, `songs/<slug>/set.py`, like a `build.py`: rerunnable, and the notes and arc are
readable later. `examples/disco_set.py` (in this skill) is a worked example (intro, groove, breakdown with a filter snap and
sweep, drop, ending; 17 clips in one batch).

## Decks: prepare the next part while this one plays

A deck is a group of tracks with a DJ strip: fader, 3-band isolator (250 Hz / 2.5 kHz, a band at -40 dB or
less is killed), a filter knob (-1 low-pass .. 0 off .. +1 high-pass) and transpose. A cued deck plays off the
air; only you hear it, through `live_listen(deck=...)`.

1. `live_load(deck='B', song=<ismail project folder>, bars=[a, b])` puts a song (or a section) on deck B: its
   tracks, effects and buses come over as `B.<name>`, its notes play at the house tempo (re-rendered, not
   stretched). It is cued while another deck is on air. The reply lists what did not come over (automation,
   placed audio clips, effects whose source track was muted).
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
- **Live output is quiet by design** (trim -6 dB, sustained cap -16 dBFS rms, ceiling -1 dBFS; about -23
  LUFS for a balanced mix). Do not chase loudness live; master a take offline.
- **Sounds you are unsure of**: try them on a muted or quiet track (`volume_db=-40`, then fade with a ramp on a
  gain fx) rather than straight onto the main part.
- **Tempo change** = `live_stop`, then `live_start` with the new tempo.

## What is and is not live yet

Live: every instrument type including mimic profiles, every effect (the same processors as offline renders,
block for block), send buses, sidechain/duck/vocoder from live tracks, ramps on every automatable fx param.
Not yet: master-bus effects (the safety chain is the master), vocoder modulators from sound-bank sounds,
instrument-param automation (use fx params), tempo changes inside a run, a song's automation and placed audio
clips on a deck.

## Numbers worth knowing

- Output trails the mix by ~96 ms (a fixed 4096-sample alignment budget for effect lookahead, plus the safety
  limiter). Tracks stay aligned with each other; `live_listen` and recordings compensate.
- A chain may need at most 4096 samples of lookahead along track + bus (a hall is 1024, a limiter its
  lookahead, oversampled distortion 20). The error says which effect to drop.
- A replaced chain rings out (its reverb tail keeps sounding) for up to 12 s.
- `live_status` shows each track's render speed ("renders 3x realtime"). Drums and code voices run 20 to 50x,
  synths 4 to 7x, mimic 1 to 3x (low notes are the slowest: more harmonics). A clip's first pass waits for its
  renders, so the reply moves slow first launches a bar or two later; every later pass reuses them, and
  identical notes (a repeated chord) render once.
- `live_start` takes ~20 to 30 s: the render workers warm up every instrument kind and every mimic profile in
  the folder before it returns, so the first clips land on time.
- Mimic profiles come out quiet next to synths and code voices (about 9 dB): check their level in
  `live_status` and raise `volume_db` before judging the balance.
