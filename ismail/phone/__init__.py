"""The phone page: a live set in the person's pocket, over the tailnet.

One small server (ismail.phone.server, port 8870 by default) relays the live engine's master to a phone as an mp3
stream that keeps playing with the screen off, takes the person's taps and voice notes back (each stamped with the
bar they actually heard, since the phone lags the engine), and shows what the agents put there: captions, panels,
questions, blind exams, downloads and buttons. Agents drive it with the phone_* ops (ismail/phone/ops.py) and read
what the person said with phone_listen or by watching the inbox file. The page is ismail/phone/page/.
"""
