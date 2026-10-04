# The stage: building a scene with a person inside it

A scene for a video or an interactive world gets made by two kinds of work at once. The agent builds, measures and
renders; the person stands in the scene (a browser, or a headset) and places, judges and acts. This reference is
what one long build of a 1958 bar and a club, with a VR editor beside Blender, taught about doing that well. Read it
before building any scene, look or editor a person will work inside, and with `music-video.md` (shots and the cut)
and `user-experience.md` (their words, senses and consent).

The stage itself (a browser and WebXR editor with a Blender round trip, hands, voice and panels) is part of ismail:
`ismail.stage`, driven by the `stage_*` tools (below). Everything after that section holds for any editor where a
person and an agent change the same scene.

## Running the stage

- **Scenes live in the song:** `<song>/video/vr/scenes/<name>/` holds `scene.glb` and `manifest.json` (from the
  Blender bridge), `edits.json` (what the person moved), `world.json` (who plays whom, facings, partners, the floor,
  keep-out boxes, spawn, credits, and `build`: the room script that exports it), waypoints, cues, takes, voice
  notes and snapshots. `scenes/stage.json` may name the default scene. Takes, voice and snapshots are the person's:
  never share them by default.
- **Start:** `stage_start(scenes="<song>/video/vr/scenes")` replies with the address. Open
  `<address>?scene=<name>` on the desktop, or in the headset through `tailscale serve` (https). One server per port;
  `stage_status` lists servers, scenes, which pages are live and the server's health (workers busy, long-polls,
  threads, free disk; GET /health).
- **Drive:** each page command is a typed tool that waits for the page's answer: `stage_object_set`,
  `stage_object_select`, `stage_say`, `stage_panel_show`, `stage_waypoint_set`, `stage_actor_play`, `stage_stream`,
  `stage_scene_go` and the rest. A tool fails with the next step when no page shows the scene; `stage_cmd` is only
  for a command that has no tool yet.
- **Listen:** `stage_events(scene, since=, types=[...], wait=)` is what the person did and said: `voice_in` the
  moment a voice note lands (answer "got it" then), `voice_message` with its text and what they pointed at,
  `gesture`, `select`, `transform_end`, `cmd_done`, `page_error`, frame beats in the client log.
- **Verify from their side** before saying done: the reply's position, a `stage_view_snapshot`, or the event that
  proves it. Say "not verified yet" otherwise.
- **Rebuild a room:** `stage_scene_export(scene)` runs `world.json` `build.script` in Blender in a heavy-job slot.
  An open page swaps it in under the construct, never while the person is in VR.
- **Changes they will notice:** `stage_note(scenes, title, level)` feeds the "updates ready" card in the headset.

## Deriving a scene

A remodel, another era, the same place at dawn: a scene made from another is derived, never rebuilt. One build of a
club "today" was dressed on the first grey blockout of the 1958 bar instead of the bar as built, and the person saw
crude stools, no bottles, block trees and cylinder people: every lesson already learned in the built room was lost.

- **Start from the built version, and say which base you use.** `stage_scene_new(name, source=, pass_script=)`
  writes `derives_from` into the new scene's world.json and copies the page's own pieces (trees, names, cues,
  waypoints; the actor bodies come from the source through `assets`). The person's takes, voice notes and snapshots
  stay with the source.
- **The variant is a pass on the built room,** a script run after the source's full build and before the Quest diet
  (`pass` in world.json, `pass_env` for its switches). It removes, adds and repaints what changed; everything else
  is the source's. `stage_scene_export` runs the whole line (the source's build, every pass oldest first, the
  edits of the line merged with the variant's winning, the diet). Room scripts exec `os.environ["VR_BRIDGE"]` at
  their end so the passes and the diet run. A room with its own Quest merge defines `stage_diet()` and skips that
  merge in its build when `VR_DIET` is set: a pass that runs after the merge finds one joined mesh, not the stools.
- **Check it beside its source from the same camera** before the person sees it: the same view of both, side by
  side, and look for anything that went back to a blockout.
- **Renders of a scene go in `renders/<scene>/`** (a script reads `STAGE_SCENE`), so a camera both scenes share
  never overwrites the other's still.
- **A direction note is a direction, not an open question.** If the person said the place expanded, build it
  expanded; ask only what the notes leave open.

## Choose the surface for the decision

Each kind of decision has a place where the person can judge it fastest. Use that one, and say why.

| decision | surface |
|---|---|
| a look (skin, a material, a grade, light) | a sheet of stills, each lens changing one named thing, in the final grade |
| placement and layout (where a camera, a chair, a person goes) | the stage, in the browser or the headset |
| the final look of a shot | a real render, never the stage's preview |
| a set of numbers with sliders (a grade, a zone readout) | a hosted page whose Save writes the numbers the build applies |
| a quick verdict from inside the headset | a panel answered by a gesture or a button |

When the app's own preview panes are full, serve the page from your own local server and give the person the link.

## Looks: the eye exam, and what it taught

The method is the eye exam in `blind-tests.md`: lenses that each change one named thing against a fixed base, the
current state included, two or three numbered questions, answers kept word for word, a lock carried into the build.
For pictures:

- **Show the thing before asking about it.** A question about an object the person has not seen wastes the round.
- **Say what a sheet holds fixed on purpose.** A sheet that kept one light so only the face changed was read as a
  failed lighting test; lighting had its own exam.
- **Judge in the final context.** Combine the leading lenses into the shots they serve, in the era's grade (a red scar
  vanishes in black and white), at the real framing. A swatch is not a shot.
- **Look at your own sheet first.** Fix what you can see (a bald patch, a camera inside a dancer, weeds through a
  floor) before sending it, and write what you saw.
- **Big moves.** Small differences read as the same picture. A change of mood needs big moves in space and light,
  not in one material.
- **Lock as a constant, keep the lenses.** A locked choice becomes a named constant in the build, and every old lens
  stays renderable by its name, so a later "go back to C" costs nothing.
- **Go wide when the person is away.** Prepare several independent exams so one answer settles many things.
- **Give each subject its own exam letter.** Two exams named S1 cost a round of confusion.

## Bodies, props and contact

- **Fix locally from the state the person liked.** When a liked pose has one flaw, restore that pose and change only
  that, the way a body would (roll the shoulder, sink into the seat). Blind searches over many joints drift into
  contortion. Look at a render before the third search.
- **Score the look, not only the constraint.** Zero clipping bought with a winged elbow is a failure. Measure the
  cause first; measure contact on the skin, not on the bones.
- **Clip-check every contact** with a close-up render, at the keys and between them: chairs in walls, hands through
  partners, a mic floating off its stand, a bottle hovering over a table.
- **Measure references from photos** of real people doing the thing (a hand landmark model gives joint bends) rather
  than inventing a grip.
- **Quiet set dressing.** Surfaces in most shots must be dull to the eye; a busy floor or wallpaper steals every
  frame. Keep colour by a matte of the named objects, never by hue: a coloured key light makes everything of that hue
  keep its colour.
- **No real likenesses** of public people (`music-video.md`, "Avoid").

## When the person is inside the work

A person in a headset cannot see your terminal. Contact is part of the interface:

- **Answer at once, then briefly.** Play a short recorded acknowledgement the moment a message arrives (a generated
  one can arrive a minute late), then short spoken replies. Long silence reads as being left alone.
- **Capture what they point at when they speak.** The view and the selection at the moment a voice note ends belong
  to the note; reading them later shows a different moment.
- **Let them interrupt**, and keep what they did not hear for later.
- **Every interaction is a sound too.** A countdown ticks, a shutter fires, a lock clicks, a drop lands. A timed
  action with no sound left the person guessing when the camera would fire.
- **Things carry the names the person uses.** Keep a names map (scene item to the words the person and you say),
  so "the jukebox" means one object to both of you.
- **Teach the stage the first time.** With no history of the person on the stage, or when the events show a
  struggle (selects with no action, a grab that moves nothing, "how do I"), offer a spoken tutorial one gesture at
  a time, each step waiting for the event that proves it worked, each with its sound: talk, point and select, move
  a thing, move yourself, take a picture, set a camera, record a take, housekeeping. Keep the gesture list in one
  place the page and you both read, so a new gesture joins the tutorial when it ships.
- **Show which version is running** (a stamp on the page), and reload with a fresh address after a change.
- **Address every note.** After a session, check every message against what was done and say what was not.
- **Measure a gesture from a take before binding it.** A pinch that the system already uses collides with yours;
  gestures are personal, so calibrate them per person, and keep their recordings local without consent.
- **Keep tooling in service of the work.** An editor feature is worth building when the scene waits on it; when the
  scene is waiting for layout, build the scene.
- **Findings go to the handoff.** A gap in the engine goes in the project's HANDOFF.md, not into a message to another
  session.

## Shared editing: never lose what the person did

Every rule here cost the person work once.

- **Saves merge.** A save that overwrites the scene file drops what the other side placed. Keep a history copy of
  every save.
- **The event log is the recovery path.** Log every edit as it happens; a lost save can be rebuilt from it.
- **A page never saves before its scene has loaded.** Boot into a neutral space while the scene streams in, and
  refuse saves until it is whole: a half-loaded page that saves writes an empty scene over the real one. A load
  that stalls retries with a fresh address (a headset's pooled connection can die silently).
- **Never trust a save the page did not confirm.** Save on idle and when the page hides, and show the person that
  it saved.
- **A server running old code must say so.** After changing the server, restart it; until then every reply carries
  a stale flag.
- **Re-export after a build**, or the person edits yesterday's scene.
- **Never move the person's things.** A camera they placed that ends up inside a character gets reported, and a new
  one is added beside it.
- **A resting hand does nothing.** Selecting is free; a change needs a deliberate unlock; a limp or idle hand is
  ignored, and a selection lapses with time and distance.
- **One coordinate frame.** Convert between the editor's and Blender's axes in one place, and read world positions
  only after the scene has updated.
- **Draw on demand.** An idle page that redraws every frame keeps the GPU busy on a shared machine.
- **Silent failures to check for:** low memory renders flat pink materials and still reports success; a relative
  output folder writes renders somewhere else while stale ones look current; a syntax check can pass a page that will
  not start (check modules as modules).

## Agents first

Everything a hand can do on the stage is also a plain call an agent can make: select, grab, set a key, scrub, retime,
bind a finger to a joint, turn a knob. Every recorded take is data an agent can read, edit and replay. A knob that
must answer in milliseconds is mapped once (`live_map` in `live.md`) and applied by the engine, never routed through
a model.
