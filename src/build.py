#!/usr/bin/env python3
"""Draws every picture on the profile page.

The hero is a year of practice: one brush mark per day, darker the more was done, and the busiest
days in bloom. Four plates show four forms, numbered like kata. A seal with a blossom closes the page.

Every word is set as outlines from the fonts in src/fonts, so the pictures look the same on every
screen and need nothing from outside. Numbers come from GitHub and crates.io; when a fetch fails,
the last good numbers in src/data.json are used, so a bad day never breaks the page.

    pip install fonttools uharfbuzz
    python src/build.py            # fetch, then draw
    python src/build.py --offline  # draw from src/data.json only
"""

import json
import math
import os
import random
import re
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / 'src' / 'fonts'
ASSETS = ROOT / 'assets'
DATA = ROOT / 'src' / 'data.json'
USER = 'alan890104'

# The forms on the plates, in order. A form with no repo shows the roles instead of numbers.
FORMS = [
    dict(key='torch', repo=None, name='Torch Finance',
         line="Stablecoin liquidity on TON, and Curve Finance's official TVM partner.",
         roles=['Founder', 'Architect'], tags=['TON', 'Tolk', 'FunC']),
    dict(key='sumi', repo='alan890104/sumi', name='Sumi',
         line='Press a key, speak, and the words land at your cursor, already tidied.',
         tags=['Rust', 'Tauri', 'macOS']),
    dict(key='asr', repo='alan890104/qwen3-asr-rs', name='qwen3-asr-rs',
         line='Qwen3-ASR speech recognition in pure Rust, streaming on Metal and CUDA.',
         tags=['Rust', 'candle']),
    dict(key='paste', repo='alan890104/claude-code-paste-preview', name='paste-preview',
         line='See the images you paste into Claude Code, and circle what matters.',
         tags=['Claude Code', 'macOS', 'Linux', 'Windows']),
    dict(key='tact', repo='Ton-Dynasty/tondynasty-contracts', name='tondynasty-contracts',
         line='Reusable traits and standards for TON smart contracts, written in Tact.',
         tags=['Tact', 'TON']),
]

# Colour only ever means ink, paper or bloom. Each picture carries both themes as CSS variables.
THEMES = {
    'light': dict(
        ink='#1f1d1a', mute='#6f6a61', faint='#ddd7cc', panel='#f6f3ec', card='#fffdf8', edge='#e2dccf',
        lv=['#e2ddd2', '#b9b0a1', '#8a8174', '#544d44', '#1f1d1a'],
        petal='#f3b6c6', petal2='#f9d3dd', heart='#c4456b', seal='#c23b62', on_seal='#fff8f1',
    ),
    'dark': dict(
        ink='#ece6da', mute='#9c978d', faint='#2a3037', panel='#141a21', card='#1a2129', edge='#283039',
        lv=['#262c33', '#4a5057', '#7d8084', '#b5b1a9', '#ece6da'],
        petal='#efa7bc', petal2='#f6c5d3', heart='#e3678d', seal='#d9557d', on_seal='#0d1117',
    ),
}


# ---------- type ----------

class Face:
    """A font that sets a line of text as one SVG path, kerned by HarfBuzz."""

    def __init__(self, file):
        path = str(FONTS / file)
        blob = hb.Blob.from_file_path(path)
        self.hb = hb.Font(hb.Face(blob))
        self.upem = self.hb.face.upem
        tt = TTFont(path)
        self.glyphs = tt.getGlyphSet()
        self.order = tt.getGlyphOrder()

    def _shape(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {'kern': True, 'liga': True})
        return list(zip(buf.glyph_infos, buf.glyph_positions))

    def width(self, text, size, track=0):
        run = self._shape(text)
        return sum(p.x_advance for _, p in run) * size / self.upem + track * max(len(run) - 1, 0)

    def path(self, text, size, x, y, track=0, anchor='start'):
        s = size / self.upem
        w = self.width(text, size, track)
        x -= {'start': 0, 'middle': w / 2, 'end': w}[anchor]
        digits = 0 if size >= 60 else 1
        pen = SVGPathPen(self.glyphs, ntos=lambda v: f'{v:.{digits}f}'.rstrip('0').rstrip('.') if digits else f'{v:.0f}')
        for info, pos in self._shape(text):
            name = self.order[info.codepoint]
            gx = x + pos.x_offset * s
            gy = y - pos.y_offset * s
            self.glyphs[name].draw(TransformPen(pen, (s, 0, 0, -s, gx, gy)))
            x += pos.x_advance * s + track
        return pen.getCommands()

    def wrap(self, text, size, width):
        lines, cur = [], ''
        for word in text.split():
            nxt = f'{cur} {word}'.strip()
            if cur and self.width(nxt, size) > width:
                lines.append(cur)
                cur = word
            else:
                cur = nxt
        return lines + [cur]


SERIF = Face('InstrumentSerif-Regular.ttf')
ITALIC = Face('InstrumentSerif-Italic.ttf')
MONO = Face('JetBrainsMono-Regular.ttf')
MONO_M = Face('JetBrainsMono-Medium.ttf')


def text(face, s, size, x, y, fill, track=0, anchor='start', cls=''):
    c = f' class="{cls}"' if cls else ''
    return f'<path{c} fill="{fill}" d="{face.path(s, size, x, y, track, anchor)}"/>'


def palette(theme):
    t = THEMES[theme]
    return ';'.join([f'--{k}:{v}' for k, v in t.items() if k != 'lv'] + [f'--lv{i}:{c}' for i, c in enumerate(t['lv'])])


def variables(tag):
    """fill="var(--ink)" is not allowed as an attribute, so it moves into the tag's style."""
    decls = [f'{prop}:var(--{name})' for prop, name in re.findall(r' (fill|stroke)="var\(--(\w+)\)"', tag)]
    if not decls:
        return tag
    tag = re.sub(r' (fill|stroke)="var\(--\w+\)"', '', tag)
    if ' style="' in tag:
        return tag.replace(' style="', f' style="{";".join(decls)};', 1)
    return re.sub(r'(/?>)$', f' style="{";".join(decls)}"\\1', tag)


def svg(w, h, title, body, style=''):
    """One picture for both themes: it reads the page's colour scheme, as GitHub sets it."""
    body = re.sub(r'<[a-zA-Z][^>]*>', lambda m: variables(m.group(0)), body)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{title}">'
        f'<title>{title}</title><style>:root{{{palette("light")}}}'
        f'@media (prefers-color-scheme: dark){{:root{{{palette("dark")}}}}}{style}'
        '@media (prefers-reduced-motion: reduce){*{animation:none!important}.motion{display:none}}'
        f'</style>{body}</svg>\n'
    )


def fmt(n):
    return f'{n:,}'


# ---------- shared marks ----------

def tick_shape(level):
    """The day's mark: the single horizontal stroke a calligrapher practices first. A slanted entry, a body that
    thins a little, and the press at the end; longer and heavier with more practice."""
    L = 5.5 + level * 2.6
    T = 2.4 + level * .44
    h = L / 2
    return (f'M{-h:.2f} {T * .25:.2f}L{-h + T * .35:.2f} {-T * .45:.2f}'
            f'C{-L / 6:.2f} {-T * .3:.2f} {L / 6:.2f} {-T * .28:.2f} {h - T * .9:.2f} {-T * .35:.2f}'
            f'C{h - T * .6:.2f} {-T * .72:.2f} {h - T * .1:.2f} {-T * .58:.2f} {h:.2f} {-T * .05:.2f}'
            f'C{h + T * .05:.2f} {T * .35:.2f} {h - T * .35:.2f} {T * .55:.2f} {h - T * .8:.2f} {T * .42:.2f}'
            f'C{L / 6:.2f} {T * .3:.2f} {-L / 6:.2f} {T * .32:.2f} {-h:.2f} {T * .25:.2f}Z')


# A sakura petal, tip notched, pointing up from the flower's heart, radius 10.
PETAL = 'M0 0C-5.6-2.6-7.4-8.4-2.4-10.6L0-8.9L2.4-10.6C7.4-8.4 5.6-2.6 0 0Z'
# The seal's petal: lifted off the heart and more deeply notched, since it is cut small.
SEAL_PETAL = 'M0-2.8C-5.8-4.4-7.4-10-3.1-12.2L0-10.4L3.1-12.2C7.4-10 5.8-4.4 0-2.8Z'


def blossom(t, cx, cy, r, turn, delay, cls='bl'):
    s = r / 10
    petals = ''.join(f'<use href="#petal" transform="rotate({a * 72})"/>' for a in range(5))
    stamens = ''.join(
        f'<circle r=".75" cx="{3.6 * math.sin(math.radians(a * 72 + 36)):.2f}" '
        f'cy="{-3.6 * math.cos(math.radians(a * 72 + 36)):.2f}"/>' for a in range(5))
    return (f'<g transform="translate({cx:.1f} {cy:.1f}) rotate({turn:.0f}) scale({s:.2f})">'
            f'<g class="{cls}" style="animation-delay:{delay:.2f}s">'
            f'<g fill="{t["petal"]}" stroke="{t["petal2"]}" stroke-width=".6">{petals}</g>'
            f'<circle r="2.3" fill="{t["heart"]}"/><g fill="{t["heart"]}">{stamens}</g></g></g>')


def seal(t, x, y, size, carved, turn=0, cls=''):
    """A square seal with a cherry blossom in it, and no words.
    Carved: the flower is cut out of the red. Raised: the flower and its border are the red.
    The petals stand apart and the small seal is cut clean, so it reads as a flower, not a gear."""
    c = f' class="{cls}"' if cls else ''
    pad = size * 0.11
    cx, cy = x + size / 2, y + size / 2
    flower, hole = (t['on_seal'], t['seal']) if carved else (t['seal'], t['on_seal'])
    petals = ''.join(f'<path d="{SEAL_PETAL}" transform="rotate({a * 72})"/>' for a in range(5))
    bloom = (f'<g transform="translate({cx:.1f} {cy + size * .02:.1f}) rotate(18) scale({size * .032:.3f})" fill="{flower}">'
             f'{petals}<circle r="2" fill="{hole}"/></g>')
    if carved:
        body = f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{size * .09:.1f}" fill="{t["seal"]}"/>{bloom}'
    else:
        body = (f'<rect x="{x + pad / 2}" y="{y + pad / 2}" width="{size - pad}" height="{size - pad}" '
                f'rx="{size * .07:.1f}" fill="none" stroke="{t["seal"]}" stroke-width="{size * .055:.1f}"/>{bloom}')
    rough = '' if size < 60 else ' filter="url(#rough)"'
    return (f'<g{c}{rough} transform="rotate({turn} {cx} {cy})">{body}</g>')


ROUGH = ('<filter id="rough" x="-10%" y="-10%" width="120%" height="120%">'
         '<feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="7"/>'
         '<feDisplacementMap in="SourceGraphic" scale="2.2"/></filter>')


# ---------- the hero ----------

def hero(t, d):
    W, H = 1000, 474
    weeks = d['calendar']
    pitch = W / len(weeks)
    top = 280
    rnd = random.Random(890104)

    days = [(wi, day) for wi, wk in enumerate(weeks) for day in wk]
    best = sorted((x for x in days if x[1]['count'] > 0), key=lambda x: (-x[1]['count'], x[1]['date']))[:13]
    blooms = {day['date']: rank for rank, (_, day) in enumerate(best)}

    marks, flowers = [], []
    for wi, wk in enumerate(weeks):
        delay = 0.25 + wi * 0.022
        cx = (wi + 0.5) * pitch
        row = []
        for day in wk:
            cy = top + (day['weekday'] + 0.5) * pitch
            jitter = rnd.uniform(-4, 4)
            stretch = rnd.uniform(.88, 1.12)
            if day['date'] in blooms:
                rank = blooms[day['date']]
                r = 11.5 - rank * 0.32
                flowers.append(blossom(t, cx, cy, r, rnd.uniform(0, 72), delay + 0.55 + rank * 0.03))
            elif day['level'] == 0:
                row.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="1.25" fill="{t["lv"][0]}"/>')
            else:
                lv = day['level']
                row.append(f'<use href="#t{lv}" fill="{t["lv"][lv]}" '
                           f'transform="translate({cx:.1f} {cy:.1f}) rotate({-7 + jitter:.0f}) scale({stretch:.2f} 1)"/>')
        marks.append(f'<g class="wk" style="animation-delay:{delay:.3f}s">{"".join(row)}</g>')

    falling = []
    for i, (x0, y0, dur, start, size) in enumerate([(720, -20, 17, 2.2, .78), (930, 40, 23, 8.5, .62), (520, -30, 29, 15, .7)]):
        falling.append(f'<g transform="translate({x0} {y0}) scale({size})"><g class="fall f{i}" '
                       f'style="animation-duration:{dur}s;animation-delay:{start}s">'
                       f'<use href="#petal" fill="{t["petal"]}" stroke="{t["petal2"]}" stroke-width=".6"/></g></g>')

    total = fmt(d['total'])
    body = (
        f'<defs>{ROUGH}<path id="petal" d="{PETAL}"/>'
        + ''.join(f'<path id="t{lv}" d="{tick_shape(lv)}"/>' for lv in range(1, 5)) + '</defs>'
        + seal(t, 0, 6, 36, carved=True, turn=-2)
        + text(MONO_M, 'KATA BUILDER', 15, 52, 30, t['mute'], track=4.2)
        + text(SERIF, 'Yu Lun Hsu', 132, -5, 166, t['ink'], cls='rise')
        + text(ITALIC, 'Same form, every day, until it blooms.', 40, 0, 226, t['mute'], cls='rise r2')
        + ''.join(marks) + ''.join(flowers)
        + text(MONO, f'{total} contributions in the last year', 15, 0, 458, t['mute'])
        + f'<g class="motion">{"".join(falling)}</g>'
    )
    style = (
        '.wk{animation:ink .7s ease-out both}'
        '@keyframes ink{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}'
        '.bl{transform-box:fill-box;transform-origin:center;animation:bloom 1s cubic-bezier(.2,1.5,.4,1) both}'
        '@keyframes bloom{from{transform:scale(0) rotate(-70deg);opacity:0}to{transform:none;opacity:1}}'
        '.rise{animation:rise 1.1s cubic-bezier(.2,.7,.2,1) both}.r2{animation-delay:.15s}'
        '@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}'
        '.fall{opacity:0;animation-name:fall;animation-timing-function:linear;animation-iteration-count:infinite}'
        '@keyframes fall{0%{transform:translate(0,0) rotate(0);opacity:0}8%{opacity:.85}'
        '50%{transform:translate(-160px,250px) rotate(200deg)}88%{opacity:.85}'
        '100%{transform:translate(-300px,520px) rotate(380deg);opacity:0}}'
    )
    title = f'Yu Lun Hsu, kata builder. Same form, every day, until it blooms. {total} contributions in the last year.'
    return svg(W, H, title, body, style)


# ---------- the plates ----------

PW, PH = 1000, 320
AX, AY, AW, AH = 580, 40, 380, 240


def plate(t, d, n, form, motif):
    stats = d['forms'].get(form['key'], {})
    name_size = min(80, 470 / SERIF.width(form['name'], 1))
    lines = SERIF.wrap(form['line'], 29, 470)[:2]
    meta = [(fmt(stats['stars']), 'stars')] if 'stars' in stats else []
    if stats.get('downloads'):
        meta.append((fmt(stats['downloads']), 'downloads'))
    meta_svg, x = '', 48
    for role in form.get('roles', []):
        meta_svg += text(MONO_M, role, 15, x, 280, t['ink'])
        x += MONO_M.width(role, 15) + 18
    if form.get('roles'):
        x += 8
    for num, word in meta:
        meta_svg += text(MONO_M, num, 15, x, 280, t['ink'])
        x += MONO_M.width(num, 15) + 8
        meta_svg += text(MONO, word, 15, x, 280, t['mute'])
        x += MONO.width(word, 15) + 26
    for tag in form['tags']:
        meta_svg += text(MONO, tag, 15, x, 280, t['mute'])
        x += MONO.width(tag, 15) + 18

    body = (
        f'<rect width="{PW}" height="{PH}" rx="24" fill="{t["panel"]}"/>'
        + text(MONO_M, f'FORM {n:02d}', 14, 48, 66, t['seal'], track=4)
        + text(SERIF, form['name'], name_size, 46, 146, t['ink'])
        + ''.join(text(SERIF, ln, 29, 48, 194 + i * 36, t['mute']) for i, ln in enumerate(lines))
        + meta_svg
        + motif(t)
    )
    title = f'Form {n:02d}: {form["name"]}. {form["line"]}'
    return svg(PW, PH, title, body, STYLES[form['key']])


def envelope(u, rnd_peaks):
    return sum(a * math.exp(-((u - c) ** 2) / (2 * w * w)) for c, a, w in rnd_peaks)


def motif_torch(t):
    """Curve's StableSwap invariant, the curve Torch's pools trade on: flat in the middle like a sum,
    bending like a product at the ends. The pool's state slides along it, swap after swap."""
    A, D, top = 8, 1, 1.25
    ox, oy, side = AX + 84, AY + 226, 222

    def at(x, y):
        return ox + x / top * side, oy - y / top * side

    def stable(x):
        a = 16 * A * x
        b = 16 * A * x * x + 4 * D * x - 16 * A * D * x
        return (-b + math.sqrt(b * b + 4 * a * D ** 3)) / (2 * a)

    def line(points):
        return 'M' + ' L'.join(f'{px:.1f} {py:.1f}' for px, py in points)

    xs = [0.03 * (top / 0.03) ** (i / 140) for i in range(141)]
    curve = line([at(x, stable(x)) for x in xs if stable(x) <= top])
    product = line([at(x, .25 / x) for x in xs if .2 <= x <= top and .25 / x <= top])
    middle = line([at(x, stable(x)) for x in [.28 + i * .44 / 40 for i in range(41)]])
    (x0, y0), (x1, y1) = at(0, top), at(top, 0)
    sx, sy = at(1, 0)
    tx, ty = at(0, 1)
    return (
        f'<path d="M{x0:.1f} {y0:.1f}V{oy}H{x1:.1f}" fill="none" stroke="{t["edge"]}" stroke-width="1.6"/>'
        f'<path d="M{tx:.1f} {ty:.1f}L{sx:.1f} {sy:.1f}" fill="none" stroke="{t["mute"]}" stroke-width="1.4" stroke-dasharray="3 6" stroke-linecap="round" opacity=".7"/>'
        f'<path d="{product}" fill="none" stroke="{t["mute"]}" stroke-width="1.4" opacity=".55"/>'
        f'<path d="{curve}" fill="none" stroke="{t["ink"]}" stroke-width="2.8" stroke-linecap="round"/>'
        f'<g><circle r="13" fill="{t["seal"]}" opacity=".16"/><circle r="5.5" fill="{t["seal"]}"/>'
        f'<animateMotion dur="7s" repeatCount="indefinite" path="{middle}" keyPoints="0;1;0" keyTimes="0;.5;1" '
        'calcMode="spline" keySplines=".45 0 .55 1;.45 0 .55 1"/></g>'
        + text(MONO, 'USDT', 14, x1, oy + 22, t['mute'], anchor='end')
        + text(MONO, 'tgUSD', 14, ox - 12, y0 + 10, t['mute'], anchor='end')
    )


def motif_sumi(t):
    """A voice becomes a line of writing: the waveform above, the words it leaves below, the cursor."""
    rnd = random.Random(31)
    peaks = [(.08, .7, .05), (.22, 1, .06), (.36, .55, .04), (.5, .9, .06), (.66, .75, .05), (.82, .95, .06), (.94, .45, .03)]
    bars, n = [], 30
    for i in range(n):
        u = i / (n - 1)
        h = 6 + 92 * min(1, envelope(u, peaks) + rnd.uniform(0, .12))
        x = AX + 10 + i * (AW - 20) / (n - 1)
        bars.append(f'<rect class="bar" style="animation-delay:{-rnd.uniform(0, 1.6):.2f}s;animation-duration:{rnd.uniform(1.1, 1.8):.2f}s" '
                    f'x="{x - 2.2:.1f}" y="{AY + 62 - h / 2:.1f}" width="4.4" height="{h:.1f}" rx="2.2"/>')
    words, delay = [], 0.4
    for row, (y, limit) in enumerate([(AY + 168, AW - 20), (AY + 204, 210)]):
        x = AX + 10
        while True:
            w = rnd.uniform(26, 74)
            if x + w > AX + limit:
                break
            words.append(f'<rect class="word" style="animation-delay:{delay:.2f}s" x="{x:.1f}" y="{y - 4}" width="{w:.1f}" height="8" rx="4"/>')
            x += w + 10
            delay += 0.16
        last = x
    caret = f'<rect class="caret" x="{last + 2:.1f}" y="{AY + 190}" width="3" height="28" rx="1.5" fill="{t["seal"]}"/>'
    return (f'<g fill="{t["mute"]}">{"".join(bars)}</g>'
            f'<g fill="{t["ink"]}">{"".join(words)}</g>{caret}')


def motif_asr(t):
    """A spectrogram read as it streams: the scan moves on, the columns behind it light up."""
    cols, rows = 28, 12
    sx, sy = AW / cols, AH / rows
    peaks = [(.1, .8, .06), (.27, 1, .07), (.45, .6, .05), (.6, .95, .07), (.8, .85, .06), (.93, .5, .04)]
    out = []
    for c in range(cols):
        u = c / (cols - 1)
        voiced = min(1, envelope(u, peaks) + .08)
        dots = []
        for r in range(rows):
            f = rows - 1 - r
            v = 0
            for k, base in enumerate([1.6, 4.6, 7.8]):
                centre = base + 1.4 * math.sin(c * .33 + k * 1.7)
                v += math.exp(-((f - centre) ** 2) / 2.2)
            v = min(1, v) * voiced
            rad = .9 + 4.4 * v
            dots.append(f'<circle cx="{AX + (c + .5) * sx:.1f}" cy="{AY + (r + .5) * sy:.1f}" r="{rad:.2f}"/>')
        out.append(f'<g class="col" style="animation-delay:{u * 4.6:.2f}s">{"".join(dots)}</g>')
    scan = (f'<g class="scan"><rect x="{AX - 1}" y="{AY - 6}" width="2" height="{AH + 12}" rx="1" fill="{t["seal"]}"/>'
            f'<circle cx="{AX}" cy="{AY - 8}" r="4" fill="{t["seal"]}"/></g>')
    return f'<g fill="{t["ink"]}">{"".join(out)}</g>{scan}'


def motif_paste(t):
    """A pasted screenshot, shown as a thumbnail, with the button that matters circled by hand."""
    fx, fy, fw, fh = AX + 20, AY + 2, 340, 178
    ui = (
        f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" rx="12" fill="{t["card"]}" stroke="{t["edge"]}" stroke-width="1.5"/>'
        + ''.join(f'<circle cx="{fx + 18 + i * 13}" cy="{fy + 17}" r="3.6" fill="{t["faint"]}"/>' for i in range(3))
        + f'<rect x="{fx + 22}" y="{fy + 42}" width="150" height="11" rx="5.5" fill="{t["mute"]}" opacity=".55"/>'
        + f'<rect x="{fx + 22}" y="{fy + 66}" width="210" height="8" rx="4" fill="{t["faint"]}"/>'
        + f'<rect x="{fx + 22}" y="{fy + 84}" width="180" height="8" rx="4" fill="{t["faint"]}"/>'
        + f'<rect x="{fx + 22}" y="{fy + 102}" width="120" height="8" rx="4" fill="{t["faint"]}"/>'
        + f'<path d="M{fx + 250} {fy + 108}l18-22 16 10 22-34" fill="none" stroke="{t["mute"]}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" opacity=".7"/>'
        + f'<rect x="{fx + 206}" y="{fy + 132}" width="108" height="30" rx="15" fill="{t["ink"]}"/>'
        + f'<rect x="{fx + 230}" y="{fy + 145}" width="60" height="5" rx="2.5" fill="{t["card"]}"/>'
    )
    cx, cy = fx + 260, fy + 147
    pts = []
    for i in range(0, 59):
        a = math.radians(200 + i * 6.6)
        wob = 1 + .05 * math.sin(i * .5)
        pts.append((cx + 80 * wob * math.cos(a), cy + 30 * wob * math.sin(a) - i * .06))
    ring = 'M' + ' L'.join(f'{x:.1f} {y:.1f}' for x, y in pts)
    circle = (f'<path class="ring" d="{ring}" fill="none" stroke="{t["seal"]}" stroke-width="3.2" '
              f'stroke-linecap="round" stroke-linejoin="round" pathLength="100" stroke-dasharray="100"/>')
    py = AY + 226
    prompt = (text(MONO_M, '›', 17, AX + 20, py, t['seal'])
              + text(MONO, 'make this smaller', 15, AX + 40, py, t['ink']))
    chip_x = AX + 40 + MONO.width('make this smaller ', 15) + 6
    chip_w = MONO.width('[Image #1]', 15) + 16
    prompt += (f'<rect x="{chip_x - 8:.1f}" y="{py - 16}" width="{chip_w:.1f}" height="22" rx="6" fill="{t["card"]}" stroke="{t["edge"]}"/>'
               + text(MONO, '[Image #1]', 15, chip_x, py, t['seal']))
    return ui + circle + prompt


def motif_tact(t):
    """Traits as bricks: a contract is built by stacking the forms it needs."""
    rows = [['Lockable', 'NFTRoyalty', 'Estimatable'], ['NFTCollection', 'NFTItem'], ['JettonMaster', 'JettonWallet']]
    out, h, gap, i = [], 44, 10, 0
    for r, row in enumerate(rows):
        widths = [MONO.width(w, 15) + 34 for w in row]
        total = sum(widths) + gap * (len(row) - 1)
        x = AX + AW - total - 10 - (r % 2) * 22
        y = AY + 26 + r * (h + gap)
        for w, label in zip(widths, row):
            accent = label == 'Lockable'
            fill = t['seal'] if accent else t['card']
            ink = t['on_seal'] if accent else t['ink']
            stroke = '' if accent else f' stroke="{t["edge"]}" stroke-width="1.5"'
            out.append(f'<g class="brick" style="animation-delay:{.3 + (len(rows) - r) * .25 + i * .06:.2f}s">'
                       f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{h}" rx="9" fill="{fill}"{stroke}/>'
                       + text(MONO, label, 15, x + w / 2, y + 27.5, ink, anchor='middle') + '</g>')
            x += w + gap
            i += 1
    y = AY + 26 + 3 * (h + gap) + 20
    code = (text(MONO_M, 'contract', 15, AX + 10, y, t['seal'])
            + text(MONO, 'Vault with Lockable, Jetton', 15, AX + 10 + MONO_M.width('contract ', 15), y, t['mute']))
    return ''.join(out) + code


MOTIFS = dict(torch=motif_torch, sumi=motif_sumi, asr=motif_asr, paste=motif_paste, tact=motif_tact)

STYLES = dict(
    torch='',
    sumi=('.bar{transform-box:fill-box;transform-origin:center;animation:speak ease-in-out infinite alternate}'
          '@keyframes speak{from{transform:scaleY(1)}to{transform:scaleY(.45)}}'
          '.word{animation:write .35s ease-out both}@keyframes write{from{opacity:0}to{opacity:1}}'
          '.caret{animation:blink 1.1s steps(1) infinite}@keyframes blink{50%{opacity:0}}'),
    asr=('.col{opacity:.22;animation:hear 5.6s ease-out infinite}'
         '@keyframes hear{0%{opacity:.22}3%{opacity:1}78%{opacity:1}96%,100%{opacity:.22}}'
         '.scan{animation:scan 5.6s linear infinite}'
         '@keyframes scan{0%{transform:translateX(0);opacity:1}82%{transform:translateX(380px);opacity:1}'
         '86%,100%{transform:translateX(380px);opacity:0}}'),
    paste=('.ring{animation:ring 6s cubic-bezier(.4,0,.2,1) infinite}'
           '@keyframes ring{0%,10%{stroke-dashoffset:100;opacity:1}30%,84%{stroke-dashoffset:0;opacity:1}'
           '94%{stroke-dashoffset:0;opacity:0}100%{stroke-dashoffset:100;opacity:0}}'),
    tact=('.brick{animation:stack .6s cubic-bezier(.2,1.3,.4,1) both}'
          '@keyframes stack{from{opacity:0;transform:translateY(-22px)}to{opacity:1;transform:none}}'),
)


# ---------- the close ----------

def close(t, d):
    W, H = 1000, 132
    body = (f'<defs>{ROUGH}<path id="petal" d="{PETAL}"/></defs>'
            + seal(t, 4, 18, 92, carved=False, turn=-3, cls='stamp')
            + text(ITALIC, 'Still practicing.', 44, 128, 72, t['ink'])
            + text(MONO, f'drawn {d["drawn"]}', 15, 130, 106, t['mute']))
    style = ('.stamp{transform-box:fill-box;transform-origin:center;animation:stamp .5s cubic-bezier(.3,1.6,.5,1) .4s both}'
             '@keyframes stamp{from{opacity:0;transform:scale(1.25)}to{opacity:1;transform:none}}')
    return svg(W, H, 'Still practicing.', body, style)


# ---------- numbers ----------

def token():
    for k in ('GITHUB_TOKEN', 'GH_TOKEN'):
        if os.environ.get(k):
            return os.environ[k]
    try:
        return subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def get(url, body=None, auth=True):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={'User-Agent': f'{USER}-profile', 'Accept': 'application/json'})
    if auth and (tok := token()):
        req.add_header('Authorization', f'Bearer {tok}')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(old):
    d = json.loads(json.dumps(old))
    try:
        q = '''query($u:String!){ user(login:$u){ contributionsCollection{ contributionCalendar{ totalContributions
                 weeks{ contributionDays{ date weekday contributionCount contributionLevel } } } } } }'''
        cal = get('https://api.github.com/graphql', {'query': q, 'variables': {'u': USER}})
        cal = cal['data']['user']['contributionsCollection']['contributionCalendar']
        level = dict(NONE=0, FIRST_QUARTILE=1, SECOND_QUARTILE=2, THIRD_QUARTILE=3, FOURTH_QUARTILE=4)
        d['total'] = cal['totalContributions']
        d['calendar'] = [[dict(date=x['date'], weekday=x['weekday'], count=x['contributionCount'],
                               level=level[x['contributionLevel']]) for x in w['contributionDays']] for w in cal['weeks']]
    except Exception as e:
        print('calendar: kept the last one', e, file=sys.stderr)
    for form in FORMS:
        if not form['repo']:
            continue
        stats = d['forms'].setdefault(form['key'], {})
        try:
            stats['stars'] = get(f'https://api.github.com/repos/{form["repo"]}')['stargazers_count']
        except Exception as e:
            print(form['key'], 'stars: kept the last one', e, file=sys.stderr)
    try:
        total, page = 0, 1
        while rel := get(f'https://api.github.com/repos/alan890104/sumi/releases?per_page=100&page={page}'):
            total += sum(a['download_count'] for r in rel for a in r['assets'])
            page += 1
        d['forms']['sumi']['downloads'] = total
    except Exception as e:
        print('sumi downloads: kept the last one', e, file=sys.stderr)
    try:
        d['forms']['asr']['downloads'] = get('https://crates.io/api/v1/crates/qwen3-asr', auth=False)['crate']['downloads']
    except Exception as e:
        print('crate downloads: kept the last one', e, file=sys.stderr)
    return d


def main():
    old = json.loads(DATA.read_text()) if DATA.exists() else {'forms': {}}
    d = old if '--offline' in sys.argv else fetch(old)
    if 'calendar' not in d:
        sys.exit('no calendar yet: run once online')
    changed = {k: v for k, v in d.items() if k != 'drawn'} != {k: v for k, v in old.items() if k != 'drawn'}
    if changed or 'drawn' not in d:
        d['drawn'] = date.today().isoformat()
    DATA.write_text(json.dumps(d, indent=1) + '\n')

    t = {k: f'var(--{k})' for k in THEMES['light'] if k != 'lv'}
    t['lv'] = [f'var(--lv{i})' for i in range(len(THEMES['light']['lv']))]
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / 'hero.svg').write_text(hero(t, d))
    for n, form in enumerate(FORMS, 1):
        (ASSETS / f'form-{form["key"]}.svg').write_text(plate(t, d, n, form, MOTIFS[form['key']]))
    (ASSETS / 'close.svg').write_text(close(t, d))


if __name__ == '__main__':
    main()
