# The person: working with the human in the loop

The agent cannot hear or see; the person can. Everything in ismail that turns a draft into something good went
through their senses and their words: blind exams, eye exams, a feedback log, a lock written into code. This
reference is how an agent works with the person so the work improves and their culture is kept: their **words**
(the lexicon), their **senses** (exams and pages), their **intent** (objectives) and their **consent**.

Read it at the start of a session that works with a person, beside SKILL.md.

## What we record, and what we never record

- Record: the person's words about the work, their answers to exams, the decisions they lock, and the objective
  they set for a piece.
- Never record emotion, mood, health, personality or any inference about the person. The lexicon measures their
  eloquence in the vernacular, and only that. "The snare is boxy" goes in; "the user seemed frustrated" never does.
- All of it stays on the machine (`songs/_user/`, `notes/feedback.md`). A quote or a number measured from the person
  goes public only after they say yes to exactly what would be published (development.md, the inclusion review).

## The lexicon: their words, our terms

A music culture lives in how its people talk about sound: "the pocket", "boxy", "too clean", "30% there", "muddy". Those words carry what the ear and eye noticed. An agent that keeps them, maps them to what ismail does, and
says things back the person's way loses less in every request. Kept over months, the lexicon is a record of that
culture and of how the person's craft grows.

**When to note a word.** Every time the person names a quality, a problem, a fix or a place in the music, and the
first time they use a trade term. Note it at once, verbatim, before acting on it:

```
lexicon_note(project, said="the snare is boxy", craft="mixing engineer", where="exam 7, bar 33")
```

The reply shows what the same words meant before, if anything. Use that first.

**Map it once you act.** When you know what the word meant in ismail terms (an op, a parameter and its direction,
an effect, a measurement), add it, and add the outcome when the next answer or exam shows whether it worked:

```
lexicon_note(id="L0007", means=["fx eq peak 400 Hz -3 dB on snare", "analyze_timbre centroid"])
lexicon_note(id="L0007", outcome="worked", why="exam 8: snare passed")
```

The words never change; the mapping and the outcome do, and the file keeps every version.

**Read it.**
- At the start of a session: `lexicon_view` (by craft, outcomes, the newest entries, words not mapped yet).
- Before acting on a word: `lexicon_find(text="boxy")`. A word that "worked" last time is the first thing to try.
- Before explaining a change: `lexicon_find(text="eq peak")` finds the person's word for it, so say "less boxy"
  instead of "a 3 dB cut at 400 Hz", unless they speak in Hz themselves.

**Pictures have a vernacular too.** Words about how something looks ("waxy", "cluttered", "flat", "the shadows are
muddy") go in the same lexicon, with the visual crafts (director, cinematographer, colourist), mapped to what
changed: a material setting, a light, a grade value.

**Crafts.** Each entry names the role the word belongs to, the roles a record used to need people for: composer,
arranger, performer, sound designer, recording engineer, mixing engineer, mastering engineer, producer, DJ,
director, cinematographer, colourist, editor, choreographer, listener.

**The learning curve.** `lexicon_view` shows the share of trade words in what the person says, by month, and which
crafts their vocabulary grows in. Use it to pitch explanations at their level and to notice when they want finer
control (they start naming frequencies, so show them frequencies). It is never a grade.

**Other people.** A friend's or a client's feedback goes in with `who="dj friend"`, and only with that person's
consent, the same as the user's.

## Their senses: exams and pages

The method is in `blind-tests.md`. Editing through pages built for the person's senses (audio pairs, stills, clips,
a view of the stage) has been the fastest route to a good result. The rules that hold for every sense:

- Show the thing before asking about it.
- One named change per lens against a fixed base, the current state included, and moves big enough to hear or see.
- Two or three numbered questions, one per variable.
- Log every answer verbatim in the song's `notes/feedback.md`, carry a lock into the build as a constant, and note
  any new words in the lexicon.

## Their intent: objectives

Every piece states what it is for, in the person's words: `project_set(objective="keep a listener asleep for 3
hours, nothing sudden after midnight")`, or `project_new(..., objective=...)`. A changed objective is a new entry;
the earlier ones stay as history. `project_info` shows the current objective.

- Judge drafts against it. A sleep set that scores well but jumps at 2 a.m. fails its objective.
- **Intent provenance.** A version, remix or derivative is made with `project_new(..., derived_from=<the original>)`;
  it carries the original's objectives and lineage, so anyone reading it sees the intent it came from and how its own
  differs.
- An objective set by an agent says so (`objective_by="agent"`) and is confirmed with the person before it guides
  the work.
