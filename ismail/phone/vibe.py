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
           'blur': 14, 'dim': 0.62, 'effect': 'none', 'intensity': 0.5, 'transition_ms': 1200}
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


def describe(v):
    return (f"vibe: ground {v['ground']}, ink {v['ink']}, accent {v['accent']}, heading {v['heading']}, effect "
            f"{v['effect']} at {v['intensity']}" + (f", art {v['image_name']} (blur {v['blur']} px, dim {v['dim']})"
                                                    if v.get('image') else ', no art'))


def menu():
    return ("presets: " + ', '.join(PRESETS) + "\nheadings: " + ', '.join(FONTS) + "\neffects: "
            + '; '.join(f"{k} ({d})" for k, d in EFFECTS.items()))
