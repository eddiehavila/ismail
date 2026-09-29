"""ismail live: play a queue of clips in real time while an agent edits it.

engine.py   the player process (clock, scheduler, render workers, mixer, device, local HTTP control)
timeline.py the queue rules in beats (pure; tested without audio)
safety.py   master trim, level rider, lookahead limiter, hard ceiling (limits come from the environment)
worker.py   render one note/phrase with the offline instrument code
ops.py      the live_* agent ops (registered into ismail.api.OPS)
"""
