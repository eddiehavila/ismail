---
name: ismail
description: Compose, arrange, sound-design, mix and recreate music with the ismail agent DAW (MCP tools mcp__ismail__*, or `python -m ismail -p <project> <op>`). Use whenever the user asks to make a song, beat, loop, track, jingle, soundtrack cue, remix or cover, to recreate or match a reference recording, to design a sound or instrument (including making acoustic instruments sound real), to master a song, to fix how a render sounds (muddy, harsh, cluttered, flat, off-tempo), to make a music video for a finished song (ismail.video), or to play, jam, DJ or perform music live in real time (live_* tools), and ismail is available. The skill makes you gather examples of the target sound, plan the piece as a Session Sheet before writing notes, model real instruments on measured examples, listen to every render through ismail's text analysis, and judge a reference match with its baseline-scored comparisons instead of by feel, then master it and ask the user what they hear. Not for music theory questions with no rendering, lyrics-only writing, or editing audio in other DAWs.
license: MIT
metadata:
  author: newsbubbles
  version: "0.1.0"
---

# Composing with ismail

ismail is a DAW you drive with text: notes, patches, effects and automation go in as data, and audio comes back as text (levels, drum lanes, piano rolls, chords, vowels, structure, comparisons). You cannot hear. Every musical judgment has to come from a tool reading. The failure modes this skill exists to prevent are the ones an agent falls into by default:

1. **Writing before planning.** Block chords on beat 1 of every bar, the same 8 bars pasted 12 times, every part in the same register.
2. **Not listening.** Rendering once and declaring it done, with a clipping master, a bass that masks the kick, or a part that is silent.
3. **Believing one number.** Matching notes while the result sounds nothing like the target; transcribing noise as notes; buying a better score with loudness.
4. **The console sound.** Every part a basic sprite patch (the `synth` type), so a cowboy song sounds like a 1990s game console playing one. Acoustic and electric instruments need a mimic profile or a measured voice, modeled on an example.

## The loop (every piece, every time)

0. **Examples.** Ask the user for a recording of what they want (a song, a sound, a link), even if they did not offer one. Recall what the genre is played on and find an example of each instrument that matters (`references/instruments.md`). A live set, a jam or a "quick" request starts here too: a quick framing shortens the Session Sheet, never this step or the non-negotiables (a live G-funk beat skipped them and the user called draft 1 "horrible").
1. **Session Sheet** (artifact, write it in your reply before any note): see the template below.
2. **Build** the skeleton: tracks with instruments from the Sheet, drums first, then bass, then harmony, then lead, then ear candy. Use `batch` for multi-op edits (atomic, one round trip).
3. **Render a window**, not the song: `render(bars=[a, b], stems=True)` on the section you just changed.
4. **Listen** with the checks in `references/listening.md` and write a **Listening Report** (artifact): one line per check, a number from a tool on each line.
5. **Fix** the worst line, re-render, re-check. Only then move to the next section.
6. **Full render + structure check**: `analyze_structure(source='render')` must show the form you planned in the Sheet.
7. **Master** (`references/mastering.md`): loudness for the genre or the reference, glue, mono low end, limiter ceiling -1 dB for mp3.
8. **Play it to the user and ask** (`render(mp3='also')`): name one or two things to listen for, report what you measured, and write their answer in the song's `notes/feedback.md`. Their ear overrules every score. Do this after each instrument chunk and each draft, not only at the end.

## Session Sheet (template)

```
Title / brief:     <one line: what it is, what it should feel like>
Tempo / meter:     <bpm> BPM, <n>/4, <length> bars (~<seconds> s)
Key / harmony:     <key>; loop = <chord per bar, e.g. Dm | Dm-G | Am | Am | F | F | Am | Am>
Form map:          intro 1-8 | A 9-24 | break 25-28 | B 29-44 | outro 45-52  (energy 2-5-3-8-1 out of 9)
Parts (role, register, rhythm, sound, modeled on):
  kick   C1  X...X...X....... (one bar)          kick synth, fitted or tuned to key root
  bass   C2-A2 offbeat 8ths, root motion          saw + sub, lp ~800 Hz, mono glide
  stabs  A#2-B4 syncopated 16ths, 12 hits/bar    detuned saw, lp 1-3 kHz, sidechained
  lead   C5+ motif every 2nd bar, 2-bar answer    square/saw, delay 3/16 pingpong
  pad    C3-C6 1 chord/bar, 3 beats + release    wide saws + air noise, reverb send
  (an acoustic part names its voice and its example, e.g.
  fiddle G3-E6 double stops on 2 and 4          voice bowed inst=violin; the fiddle in <reference> 0:12-0:20)
Variation plan:    what changes every 8 bars (a part in/out, filter opens, fill in bar 8)
Mix targets:       master <LUFS for the genre or reference>, peak -1 dBFS, limiter GR < 4 dB; kick and bass own the sub
```

Registers must not collide: at most one part per octave band doing sustained work. Every part needs its own rhythm; if two parts share a rhythm they should share a sound (layer them) or one should move.

## Where things are

- `references/composition.md`: arranging and writing with ismail's notation: rhythm cells as step strings, harmony voicing, motif and answer, 8-bar variation, transitions, energy curves. Read when writing notes.
- `references/instruments.md`: making acoustic and electric instruments sound real: getting an example first, choosing between library voice, mimic (measured from recordings), hand-written measured voice, sampler and sprite, what makes a measured voice convincing, matching an instrument chunk by chunk, asking the user, genre palettes. Read before choosing sounds for any non-electronic part.
- `references/mastering.md`: the master pass: loudness targets by genre or reference, the master chain, and checks. Read before calling a song finished.
- `references/sound-design.md`: recipes per role with parameter ranges, gain staging, when and how to use `instrument_fit`, `track_fit`, `sound_extract`, formant and vocoder voices. Read when choosing or designing sounds.
- `references/listening.md`: which analysis tool answers which question, how to read the text views (digits, rolls, zoom codes), and the Listening Report checks. Read before the first listen.
- `references/recreate.md`: matching a reference recording: grid and alignment, separation, consensus transcription, comparisons, what the scores mean, and the traps that make a draft score better while sounding worse. Read whenever a reference track is involved.
- `references/live.md`: playing live with the live engine: the Set Sheet and arc, queueing a whole arc in one batch, sweeps with ramps, listening and recording while it plays, decks (load a song, prepare it cued, transition), running a long set as a DJ loop (read the audience, small edits, a runway before every question, energy builds and drops, metric modulation for style changes), phrase voices for performers, runway before slow jobs, what is not live yet. Read before any `live_*` call.
- `references/music-video.md`: music videos with `ismail.video`: the per-song `video/` folder, the CLI, the shot kit (units, floors, posing, mirrors, GPU budget), the cut list and note-driven glitches, contact-sheet review and the creative rules. Read before planning any video.
- `references/LOCAL.md`, if it exists: an index of the user's private references kept on this machine only (never committed). Read it at the start of a task; it says which private file covers which kind of song.

## Non-negotiables

- Never report a render as good without numbers from at least `render` output (LUFS, peak, per-track peaks, SILENT flags) and one analysis view of the changed section.
- Every track peak below 0 dBFS; master limiter gain reduction under about 6 dB (more means the faders are wrong, not that the limiter is working).
- After writing notes for a part, read them back (`notes_read view='roll'` for a bar or two) before rendering. Most note bugs are visible there.
- When matching a reference: never transcribe with raw `notes_from_audio` over a whole loop section; use `notes_from_audio_loop` (consensus). Never raise a track's level to improve a perceptual score. Never call a match done while `cmp_summary` shows a WARNING line or the mix perceptual group is far under its ceiling.
- Reference audio is for analysis only. Do not place slices of the reference in the render; make the sounds.
- No acoustic or electric instrument as a bare sprite (`synth`) patch: use a library voice, measure it with `mimic_measure`, build a measured voice, or use a sampler, and name the example it is modeled on. Genres built on records (hip-hop, G-funk, boom bap) get measured drums and bass too: `analyze_kit` on the reference drums, then a voice built from its components, or `sound_extract` + `instrument_fit`. Generic kick and snare fits failed there; a measured kit passed.
- Numbers that can be measured are measured, never guessed: bar 1, tuning and swing (`analyze_grid`, `analyze_swing`), the pieces of a drum kit (`analyze_kit`), the fader balance against a reference (`levels_from_ref`). A guessed swing of 0.07 beat against a measured 0.03 was audible.
- Everything the user hears goes through a master stage, live sets included, and its loudness is read at the output (`render` prints QUIET under -20 LUFS). A live set at -21 LUFS read as "nothing" at low volume.
- Before a full draft goes to the user, `analyze_sections` with the Sheet's form map: the section before the climax peaks 3 dB or more under it (a build as loud as its climax only showed up there), and nothing that should be heard sits 35 dB under the loudest section.
- When recreating a song, match each important instrument on a short exposed chunk first (`references/instruments.md` section 4) before arranging the whole song around it.
- Every mp3 you hand the user comes with a question about what they hear, and their answer goes in `notes/feedback.md`.
