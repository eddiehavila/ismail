# Listening with ismail (you have no ears; these are your ears)

## Which tool answers which question

| question | tool | read it like |
|---|---|---|
| Did it render, is anything silent or clipping? | `render` output | per-track peak/rms, `SILENT`, `CLIPPING`, limiter gain reduction |
| Is the song shaped the way I planned? | `analyze_structure(source='render')` | one char per bar per row: 9 loudest, each step -4 dB, '.' silent; `root` row = bass note per bar; sections lettered by similar arrangement |
| Are the notes what I meant? | `notes_read(view='roll')`, then `analyze_pitches(source='track:x')` | the roll shows what you wrote; pitches shows what actually sounds |
| Is the drum pattern right? | `analyze_drums(source='track:drums')` | step strings per lane; X within 4 dB of the lane's loud hits |
| What pieces does a kit have? | `analyze_kit(source='ref:drums')` | one component per piece: energy share, pitch region, hits per 16th; `(fragment)` = lower k |
| How much swing? | `analyze_swing(source=)` | 16ths: the 'a' against the 'and', in beats and ms; straight = 0 |
| Does the dynamic shape work? | `analyze_sections(sections={...})` | rms, peak, loudest and quietest 400 ms per section; WARNING when a build is as loud as its climax |
| Does it pump / gate / groove? | `analyze_envelope(bars, band=)` | digits per 16th; a kick-ducked part shows dips on the beats |
| Is the low end clean? | `analyze_bars` sub and bass columns, `analyze_spectrum(span=)` | kick and bass should not both peak in the same 1/3-octave band |
| What is this sound? | `analyze_timbre`, `analyze_spectrum`, `sound_compare` | harmonic slope, brightness and rolloff, envelope times, width |
| What is the voice saying? | `analyze_formants` | F1/F2 per half beat, nearest vowel |
| Anything else | `spectrogram` (PNG) | last resort; it caught a missing low-pass that no text view showed |

Tracks are analysable as `track:<name>` only after `render(stems=True)`. A track stem is the track after its own effects and fader, scaled by the master chain's gain, so the stems sum to the mix. That means a sidechain duck shows up in `track:<name>`; if it barely dips, the duck depth is small, not the stem pre-fx.

Two readings that mislead:
- `analyze_drums` on a full mix (`render`, `ref`) is band activity: leads and pads show up as snare and hat hits. Read your drums as `track:<drum track>`.
- `analyze_melody` on a track with delay or vibrato splits held notes into runs of short notes. Check pitch with it and rhythm with `notes_read(view='roll')`, or read the melody before adding the delay.

## Listening Report (write one after every render you judge)

```
Render: bars <a-b>, <LUFS> LUFS, peak <dB>, limiter GR <dB>
Levels:    <loudest track> / <quietest audible track>; nothing SILENT that should play
Low end:   kick peak band <Hz> vs bass peak band <Hz>  (separate, or one ducks the other)
Clutter:   notes/bar in busiest part = <n>; parts active at once = <n>  (more than 4-5 sustained parts = mud)
Rhythm:    analyze_drums / analyze_envelope on bar <n> matches the Sheet: yes/no (quote the line)
Harmony:   analyze_pitches bar <n> = <notes> (the chord you meant? yes/no)
Space:     width (analyze_timbre stereo line) <value>; reverb/delay sends present on <tracks>
Form:      analyze_structure rows match the form map: yes/no (which section differs)
Dynamics:  analyze_sections: range <dB> quietest to loudest; the section before the climax <dB> under it (3+)
Worst:     <the single worst line above> -> next fix
```

## Common readings and fixes

- Master limiter GR > 6 dB: pull the loudest tracks down 3-6 dB; re-render.
- `analyze_structure` shows a flat map (all 8s and 9s): no energy curve; drop parts in the intro and break, automate a filter.
- Level digits with holes where the part should sustain: amp sustain too low or notes too short (`notes_transform legato=true`).
- Bright wash across 3-10 kHz in a synth group: filter envelope amount too high, drive too high, or noise layers; darker is usually closer to finished records than it feels.
- A part that `analyze_pitches` reports with many neighbours at similar level (A2 with G#2 and A#2): heavy detune or distortion smearing the pitch; reduce detune or drive if the note should read clearly.
