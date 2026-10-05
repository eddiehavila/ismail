# The phone page: a live set in the person's pocket

The person listens to a live set on their phone, away from the computer, with the screen off. They talk back the
way they do in VR, tap feedback without unlocking, and answer what you put on the page: questions, blind exams,
downloads, buttons. It runs over the tailnet; nothing is public.

## Start it

1. `phone_start()`. It relays the newest live engine's master as an mp3 stream and never starts a set or plays sound
   on this machine. The reply gives the address.
2. If the reply says the tailnet doesn't reach it yet, ask the person once, then run the line it gives
   (`tailscale serve --bg --https=8870 http://127.0.0.1:8870`). It stays, and it is tailnet only.
3. Tell them: "Open <address>, press Listen, put the phone away. Hold the big button to talk, or tap it once to talk
   hands-free and tap again to send." The first time they hold it, the phone asks for the microphone.
4. Read what they send (below) for as long as the set runs. If nobody reads, the page tells them nobody is
   listening.

## What they send, and where it lands

Every line is JSON in `~/.ismail/phone/inbox.jsonl`. It is also written to the routed inbox: the playing engine's
`<project>/notes/phone_inbox.jsonl`, or the file named with `phone_route`. Each line carries `heard`, the bar they
actually heard (`{bar, beat, of: 'bar 213 beat 3'}`), and `behind_s`. The phone runs a few seconds behind the room,
so act on `heard`, not on the engine's now.

| kind | what it means | what to do |
|---|---|---|
| `tap` `love` | they love what they heard | cut a highlight at `heard` (live.md: highlights on praise) |
| `tap` `change` | change it up now | the next change-up, now |
| `tap` `energy_up` / `energy_down` | more energy / calmer | steer the next phrase |
| `tap` `louder` / `quieter` | the set's level | move the master a few dB |
| `tap` `pause` / `resume` | pause or resume the set | gracefully: never a hard stop |
| `tap` `start_set` | they want a set and none plays | start one (ask nothing more) |
| `tap` `rewind` | they went 30 s back to hear something again | often a sign they liked it |
| `mood` | a standing hint: calm, steady, lift, peak | read it when you pick the next chapter |
| `voice`, then `voice_text` (same `id`) | a voice note, then its words | answer it |
| `answer` / `exam` / `button` | replies to your panel, question, exam or buttons | act on them |

Read it with `phone_listen(who='<your name>', since=...)` (a long-poll, which also shows them who is listening), or
watch the routed file with your harness's file watcher, so a line wakes you even between turns. Hooks in
`~/.ismail/phone/hooks.json` (`{"voice": ["cmd"], "tap": [...], "any": [...]}`) run on every line, with
`PHONE_EVENT`, `PHONE_TEXT`, `PHONE_LINE` and `PHONE_INBOX` in their environment, for an agent that isn't running.

Voice notes are transcribed by the speech server on this machine. While the CPU is over the governor's limit they
wait in a queue: taps still arrive at once, and the page tells them their note is waiting.

## What you can put on the page

- `phone_now(now=, next=, recording_why=)`: the title, next up, and why recording is on or off. The page always
  shows whether it is, read from the engine.
- `phone_say(text)`: a caption and a toast. Use `pin=True` for the "since you left" summary when they come back
  (three lines: what changed and why). `speak=True` says it into the stream with the music ducked under it, so
  they hear it in their pocket. Speak only to answer something they said, never unprompted. `buzz=True`
  vibrates.
- `phone_ask(text)`: yes or no. `phone_panel_show(title, text, image, buttons)`: anything else (the
  stage_panel_show shape). Either one with `wait=N` blocks for the answer.
- `phone_exam(title, clips, question, chips, choices, answers_path)`: a blind exam. Label the clips blind (A, B). The
  live stream pauses while a clip plays. Submit writes to `answers_path`, so no "done" is needed.
- `phone_offer(path, auto=True)`: a download (a render, a take, a PDF).
- `phone_buttons([...])`: your own buttons, as data, for this moment of the set ("darker", "drop it now"). Clear
  them when the moment passes.
- `phone_buzz()`, `phone_status()` (who listens, the bar they hear, how far behind the room), `phone_stop()`.

## Their phone

- **Pocket mode:** the screen can be off and the set plays on. The lock screen and earbuds control it: next = change
  it up, previous = love this, play/pause = their own playback.
- **Network:** 64 kbps is the default (about 30 MB an hour); they can switch to 128 on the page. It reconnects by
  itself when the network drops, and taps made offline are sent when it's back.
- **Rewind and Live:** "30s" replays the last 30 seconds; "Live" jumps back to now.
- **Install:** "Add to home screen" makes it an app icon with the same address.
