"""The page's look, set by an agent to fit the music (Nate, 2026-10-06: "you should be able to change stuff about this
page to make the page fit with the song ... song covers ... in the background, blurred out ... JavaScript effects ...
like the VR environment almost, where I feel like you're there"). A vibe is data: a palette, a heading face, an art
layer and one ambient effect. The server checks it (contrast, known names) and the page only applies it.
"""
import colorsys
import re

# heading faces: name -> (CSS family, Google Fonts css2 spec or None when the page already loads it)
FONTS = {
    'archivo': ("'Archivo'", None),
    'fraunces': ("'Fraunces'", 'Fraunces:opsz,wght@9..144,400..800'),
    'playfair': ("'Playfair Display'", 'Playfair+Display:wght@500..800'),
    'cormorant': ("'Cormorant Garamond'", 'Cormorant+Garamond:wght@500..700'),
    'space grotesk': ("'Space Grotesk'", 'Space+Grotesk:wght@400..700'),
    'syne': ("'Syne'", 'Syne:wght@500..800'),
    'unbounded': ("'Unbounded'", 'Unbounded:wght@400..800'),
    'bebas': ("'Bebas Neue'", 'Bebas+Neue'),
    'major mono': ("'Major Mono Display'", 'Major+Mono+Display'),
}
EFFECTS = {
    'none': 'nothing moves',
    'rain': 'thin drops falling, a little slanted',
    'particles': 'slow dust drifting and twinkling',
    'pulse': 'a glow from below that breathes on every beat (the set tempo)',
    'grain': 'film grain',
    'aurora': 'three soft colour fields drifting slowly',
}
DEFAULT = {'ground': '#0e0d0b', 'ink': '#efe9dd', 'accent': 'hsl(293 68% 66%)', 'heading': 'archivo', 'image': None,
           'blur': 14, 'dim': 0.62, 'effect': 'none', 'intensity': 0.5, 'transition_ms': 1200, 'layers': None,
           'hue_drift': 0.0, 'react': None}
# One layer of the background (ledger:M160, Nate 10-06 14:47: "way more creative control over the background"). Up to
# MAX_LAYERS at once, drawn in order. Each value: (default, low, high); colours default to the vibe's ink or accent.
LAYER = {'intensity': (0.5, 0.0, 1.0),      # how present it is overall
         'speed': (1.0, 0.1, 4.0),          # how fast it moves (pulse: beats per breath, 1 = every beat)
         'density': (0.5, 0.0, 1.0),        # how many drops, motes, grains
         'size': (1.0, 0.25, 4.0),          # how big each is
         'angle': (8.0, -60.0, 60.0),       # rain's slant, in degrees
         'opacity': (1.0, 0.0, 1.0)}        # the layer's alpha on top of its intensity
BLENDS = {'normal': 'source-over', 'add': 'lighter', 'screen': 'screen', 'multiply': 'multiply', 'overlay': 'overlay'}
MAX_LAYERS = 3
# what a track's notes do on the page, each on the beat the phone hears it (ledger:M160 phase 2)
REACTIONS = {'flash': 'the whole page lights in the colour for a moment (a stab, a crash)',
             'glow': 'a glow swells from the floor (a kick, a sub)',
             'burst': 'a burst of motes from a point (a clap, a snare)',
             'sparks': 'a few quick sparks (hats, qraqeb, a shaker)',
             'drops': 'a streak falls, a note from above (piano, a lead)',
             'ring': 'a ring opens from the middle (a bell, a pad entering)'}
MAX_REACT = 16
PRESETS = {
    'default': {},
    'rain': {'ground': '#0b0f14', 'ink': '#e3e9ef', 'accent': 'hsl(205 70% 64%)', 'heading': 'fraunces',
             'effect': 'rain', 'intensity': 0.55},
    'calm': {'ground': '#0d1110', 'ink': '#e6ece6', 'accent': 'hsl(160 45% 60%)', 'heading': 'cormorant',
             'effect': 'aurora', 'intensity': 0.35},
    'warm': {'ground': '#120d09', 'ink': '#f1e6d6', 'accent': 'hsl(32 85% 60%)', 'heading': 'playfair',
             'effect': 'grain', 'intensity': 0.4},
    'night': {'ground': '#08080d', 'ink': '#e7e6f2', 'accent': 'hsl(258 80% 72%)', 'heading': 'syne',
              'effect': 'particles', 'intensity': 0.5},
    'peak': {'ground': '#100808', 'ink': '#f6ebe8', 'accent': 'hsl(352 90% 64%)', 'heading': 'bebas',
             'effect': 'pulse', 'intensity': 0.7},
}


def parse_color(c):
    """'#rgb', '#rrggbb', 'rgb(r g b)' or 'hsl(h s% l%)' (commas allowed) -> (r, g, b) in 0..1."""
    s = str(c).strip().lower()
    m = re.fullmatch(r'#([0-9a-f]{3}|[0-9a-f]{6})', s)
    if m:
        h = m.group(1)
        h = ''.join(x * 2 for x in h) if len(h) == 3 else h
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    m = re.fullmatch(r'rgb\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)\s*\)', s)
    if m:
        return tuple(min(255, int(x)) / 255 for x in m.groups())
    m = re.fullmatch(r'hsl\(\s*([\d.]+)(?:deg)?[ ,]+([\d.]+)%[ ,]+([\d.]+)%\s*\)', s)
    if m:
        h, sat, l = (float(x) for x in m.groups())
        return colorsys.hls_to_rgb((h % 360) / 360, min(l, 100) / 100, min(sat, 100) / 100)
    raise ValueError(f"colour {c!r}: use '#rrggbb', 'rgb(r g b)' or 'hsl(h s% l%)'")


def hexc(rgb):
    return '#' + ''.join(f'{round(max(0, min(1, x)) * 255):02x}' for x in rgb)


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def luminance(rgb):
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def layer(x, i=0):
    """One checked layer: {'effect': ..., and any of LAYER's keys, 'color', 'color2', 'blend'}."""
    if not isinstance(x, dict):
        raise ValueError(f"layer {i + 1}: a dict like {{'effect': 'rain', 'density': 0.8, 'angle': 20}}")
    x = {k: v for k, v in x.items() if k != 'op'}             # a resolved layer goes back in as it came out
    unknown = set(x) - set(LAYER) - {'effect', 'color', 'color2', 'blend'}
    if unknown:
        raise ValueError(f"layer {i + 1}: unknown {', '.join(sorted(unknown))}; a layer takes effect, "
                         f"{', '.join(LAYER)}, color, color2, blend")
    eff = x.get('effect', 'none')
    if eff not in EFFECTS:
        raise ValueError(f"layer {i + 1}: effect {eff!r}: one of {sorted(EFFECTS)}")
    out = {'effect': eff}
    for k, (d, lo, hi) in LAYER.items():
        try:
            out[k] = round(max(lo, min(hi, float(x.get(k, d)))), 3)
        except (TypeError, ValueError):
            raise ValueError(f"layer {i + 1}: {k} is a number from {lo:g} to {hi:g}")
    for k in ('color', 'color2'):
        if x.get(k):
            out[k] = hexc(parse_color(x[k]))
    blend = x.get('blend', 'normal')
    if blend not in BLENDS:
        raise ValueError(f"layer {i + 1}: blend {blend!r}: one of {', '.join(BLENDS)}")
    out['blend'] = blend
    out['op'] = BLENDS[blend]
    return out


def react_map(r):
    """{track: 'glow'} or {track: {'do': 'glow', 'color': '#ff8844', 'amount': 0.8}} -> checked, or None. A track
    name ending in '*' matches every track it starts."""
    if not r:
        return None
    if not isinstance(r, dict) or len(r) > MAX_REACT:
        raise ValueError(f"react: a dict of up to {MAX_REACT} tracks, e.g. {{'kick': 'glow', 'qrq*': 'sparks', "
                         f"'piano': {{'do': 'drops', 'color': '#ffd27a'}}}}")
    out = {}
    for track, x in r.items():
        x = {'do': x} if isinstance(x, str) else dict(x or {})
        if x.get('do') not in REACTIONS:
            raise ValueError(f"react[{track!r}]: {x.get('do')!r}: one of {', '.join(REACTIONS)}")
        y = {'do': x['do'], 'amount': round(max(0.1, min(1.0, float(x.get('amount', 0.7)))), 2)}
        if x.get('color'):
            y['color'] = hexc(parse_color(x['color']))
        out[str(track)[:40]] = y
    return out


def resolve(v):
    """A checked vibe and the CSS values the page sets. Raises ValueError saying what to change."""
    out = dict(DEFAULT, **{k: x for k, x in v.items() if k in DEFAULT})
    g, ink, acc = parse_color(out['ground']), parse_color(out['ink']), parse_color(out['accent'])
    if luminance(g) > 0.2:
        raise ValueError(f"ground {out['ground']} is light: the page is a night radio (dark ground, light ink); pick a "
                         f"ground under about 20% luminance, e.g. '#0e0d0b', and carry the colour in the accent")
    c = contrast(ink, g)
    if c < 7:
        raise ValueError(f"ink {out['ink']} on ground {out['ground']} is {c:.1f}:1; text read on a walk needs 7:1: lighten "
                         f"the ink (e.g. '#efe9dd') or darken the ground")
    ca = contrast(acc, g)
    if ca < 3:
        raise ValueError(f"accent {out['accent']} on ground {out['ground']} is {ca:.1f}:1; keys and marks need 3:1: a "
                         f"lighter or more saturated accent")
    head = str(out['heading']).lower()
    if head not in FONTS:
        raise ValueError(f"heading {out['heading']!r}: one of {sorted(FONTS)}")
    if out['effect'] not in EFFECTS:
        raise ValueError(f"effect {out['effect']!r}: one of {sorted(EFFECTS)}")
    if out.get('layers'):
        if not isinstance(out['layers'], list) or len(out['layers']) > MAX_LAYERS:
            raise ValueError(f"layers: a list of at most {MAX_LAYERS} layers, drawn in order")
        out['layers'] = [layer(x, i) for i, x in enumerate(out['layers'])]
    else:                                              # the one-effect shortcut is layer 1
        out['layers'] = [layer({'effect': out['effect'], 'intensity': out['intensity']})]
    out['effect'], out['intensity'] = out['layers'][0]['effect'], out['layers'][0]['intensity']
    out['hue_drift'] = round(max(-120.0, min(120.0, float(out.get('hue_drift') or 0.0))), 2)
    out['react'] = react_map(out.get('react'))
    out['heading'] = head
    out['blur'] = max(0, min(40, int(out['blur'])))
    out['dim'] = round(max(0.2, min(0.9, float(out['dim']))), 2)
    out['intensity'] = round(max(0.0, min(1.0, float(out['intensity']))), 2)
    out['transition_ms'] = max(0, min(5000, int(out['transition_ms'])))
    family, spec = FONTS[head]
    out['css'] = {'--ground': hexc(g), '--ink': hexc(ink), '--accent': hexc(acc),
                  '--panel': hexc(mix(g, ink, 0.045)), '--panel-2': hexc(mix(g, ink, 0.08)),
                  '--line': hexc(mix(g, ink, 0.15)), '--dim': hexc(mix(ink, g, 0.32)),
                  '--accent-deep': hexc(mix(acc, g, 0.78)),
                  '--head': f"{family},'Archivo','Arial Narrow',system-ui,sans-serif"}
    out['font_css'] = (f"https://fonts.googleapis.com/css2?family={spec}&display=swap" if spec else None)
    return out


def describe_layer(x):
    extra = [f"{k} {x[k]:g}" for k, (d, _, _) in LAYER.items() if k != 'intensity' and x.get(k, d) != d]
    extra += [f"{k} {x[k]}" for k in ('color', 'color2') if x.get(k)]
    extra += [f"blend {x['blend']}"] if x.get('blend', 'normal') != 'normal' else []
    return f"{x['effect']} at {x['intensity']:g}" + (f" ({', '.join(extra)})" if extra else '')


def describe(v):
    ls = v.get('layers') or [{'effect': v['effect'], 'intensity': v['intensity']}]
    fx = (f"effect {describe_layer(ls[0])}" if len(ls) == 1 else
          f"layers: " + '; '.join(f"{i + 1}. {describe_layer(x)}" for i, x in enumerate(ls)))
    return (f"vibe: ground {v['ground']}, ink {v['ink']}, accent {v['accent']}, heading {v['heading']}, {fx}"
            + (f", hue drift {v['hue_drift']:g} deg/min" if v.get('hue_drift') else '')
            + (", notes: " + ', '.join(f"{t} {x['do']}" for t, x in v['react'].items()) if v.get('react') else '')
            + (f", art {v['image_name']} (blur {v['blur']} px, dim {v['dim']})" if v.get('image') else ', no art'))


def menu():
    return ("presets: " + ', '.join(PRESETS) + "\nheadings: " + ', '.join(FONTS) + "\neffects: "
            + '; '.join(f"{k} ({d})" for k, d in EFFECTS.items())
            + f"\nlayers (up to {MAX_LAYERS}): effect, " + ', '.join(f"{k} {lo:g}-{hi:g} (default {d:g})"
                                                              for k, (d, lo, hi) in LAYER.items())
            + ", color, color2, blend (" + ', '.join(BLENDS) + ")\nhue_drift: degrees a minute the colours turn"
            + "\nreact (a track's notes on the beat the phone hears): " + '; '.join(f"{k} ({d})" for k, d in REACTIONS.items()))
