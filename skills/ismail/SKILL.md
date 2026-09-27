---
name: ismail
description: Compose, arrange, sound-design, mix and recreate music with the ismail agent DAW (MCP tools mcp__ismail__*, or `python -m ismail -p <project> <op>`). Use whenever the user asks to make a song, beat, loop, track, jingle, soundtrack cue, remix or cover, to recreate or match a reference recording, to design a sound or instrument, to fix how a render sounds (muddy, harsh, cluttered, flat, off-tempo), or to make a music video for a finished song (ismail.video), and ismail is available. The skill makes you plan the piece as a Session Sheet before writing notes, listen to every render through ismail's text analysis, and judge a reference match with its baseline-scored comparisons instead of by feel. Not for music theory questions with no rendering, lyrics-only writing, or editing audio in other DAWs.
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

## The loop (every piece, every time)

1. **Session Sheet** (artifact, write it in your reply before any note): see the template below.
2. **Build** the skeleton: tracks with instruments from the Sheet, drums first, then bass, then harmony, then lead, then ear candy. Use `batch` for multi-op edits (atomic, one round trip).
3. **Render a window**, not the song: `render(bars=[a, b], stems=True)` on the section you just changed.
4. **Listen** with the checks in `references/listening.md` and write a **Listening Report** (artifact): one line per check, a number from a tool on each line.
5. **Fix** the worst line, re-render, re-check. Only then move to the next section.
6. **Full render + structure check** at the end: `analyze_structure(source='render')` must show the form you planned in the Sheet.

## Session Sheet (template)

```
Title / brief:     <one line: what it is, what it should feel like>
Tempo / meter:     <bpm> BPM, <n>/4, <length> bars (~<seconds> s)
Key / harmony:     <key>; loop = <chord per bar, e.g. Dm | Dm-G | Am | Am | F | F | Am | Am>
Form map:          intro 1-8 | A 9-24 | break 25-28 | B 29-44 | outro 45-52  (energy 2-5-3-8-1 out of 9)
Parts (role, register, rhythm, sound):
  kick   C1  X...X...X....... (one bar)          kick synth, fitted or tuned to key root
  bass   C2-A2 offbeat 8ths, root motion          saw + sub, lp ~800 Hz, mono glide
  stabs  A#2-B4 syncopated 16ths, 12 hits/bar    detuned saw, lp 1-3 kHz, sidechained
  lead   C5+ motif every 2nd bar, 2-bar answer    square/saw, delay 3/16 pingpong
  pad    C3-C6 1 chord/bar, 3 beats + release    wide saws + air noise, reverb send
Variation plan:    what changes every 8 bars (a part in/out, filter opens, fill in bar 8)
Mix targets:       master ~-10 LUFS, peak -0.3 dBFS, limiter GR < 6 dB; kick and bass own the sub
```

Registers must not collide: at most one part per octave band doing sustained work. Every part needs its own rhythm; if two parts share a rhythm they should share a sound (layer them) or one should move.

## Where things are

- `references/composition.md`: arranging and writing with ismail's notation: rhythm cells as step strings, harmony voicing, motif and answer, 8-bar variation, transitions, energy curves. Read when writing notes.
- `references/sound-design.md`: recipes per role with parameter ranges, gain staging, when and how to use `instrument_fit`, `track_fit`, `sound_extract`, formant and vocoder voices. Read when choosing or designing sounds.
- `references/listening.md`: which analysis tool answers which question, how to read the text views (digits, rolls, zoom codes), and the Listening Report checks. Read before the first listen.
- `references/recreate.md`: matching a reference recording: grid and alignment, separation, consensus transcription, comparisons, what the scores mean, and the traps that make a draft score better while sounding worse. Read whenever a reference track is involved.
- `references/music-video.md`: music videos with `ismail.video`: the per-song `video/` folder, the CLI, the shot kit (units, floors, posing, mirrors, GPU budget), the cut list and note-driven glitches, contact-sheet review and the creative rules. Read before planning any video.

## Non-negotiables

- Never report a render as good without numbers from at least `render` output (LUFS, peak, per-track peaks, SILENT flags) and one analysis view of the changed section.
- Every track peak below 0 dBFS; master limiter gain reduction under about 6 dB (more means the faders are wrong, not that the limiter is working).
- After writing notes for a part, read them back (`notes_read view='roll'` for a bar or two) before rendering. Most note bugs are visible there.
- When matching a reference: never transcribe with raw `notes_from_audio` over a whole loop section; use `notes_from_audio_loop` (consensus). Never raise a track's level to improve a perceptual score. Never call a match done while `cmp_summary` shows a WARNING line or the mix perceptual group is far under its ceiling.
- Reference audio is for analysis only. Do not place slices of the reference in the render; make the sounds.
