#!/usr/bin/env python3
"""Post-process dragon PNGs: crop to 4:5, resize to 600x750, save webp,
then inject them into ../index.html as base64 data URIs.

The page template must contain __DRG_CODEX__ / __DRG_CLAUDE__ / __DRG_GEMINI__ /
__DRG_GROK__ placeholder tokens (the published index.html already has the images
baked in, so this only matters when you regenerate the art from scratch).

Usage: python3 drg_post.py   (expects ./out/drg_*.png from gen_dragons.py)
"""
import base64
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'out')
HTML = os.path.join(HERE, '..', 'index.html')

NAMES = ['codex', 'claude', 'gemini', 'grok']
HEADROOM = 28          # px kept above the topmost bright (golden) pixel
Q = 80


def top_bright(im):
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(0, w, 4):
            if max(px[x, y]) > 120:
                return y
    return 0


uris = {}
for n in NAMES:
    p = os.path.join(SRC, 'drg_%s.png' % n)
    im = Image.open(p).convert('RGB')
    w, h = im.size
    ch = int(w * 5 / 4)
    if ch <= h:
        y0 = max(0, min(top_bright(im) - HEADROOM, h - ch))
        im = im.crop((0, y0, w, y0 + ch))
        print('@@ %s top-crop y0=%d' % (n, y0))
    else:
        cw = int(h * 4 / 5)
        x0 = (w - cw) // 2
        im = im.crop((x0, 0, x0 + cw, h))
    im = im.resize((600, 750), Image.LANCZOS)
    out = os.path.join(HERE, 'drg_%s.webp' % n)
    im.save(out, 'WEBP', quality=Q, method=6)
    kb = os.path.getsize(out) / 1024
    print('@@ %s -> 600x750 webp %.0fKB' % (n, kb))
    with open(out, 'rb') as f:
        uris[n] = 'data:image/webp;base64,' + base64.b64encode(f.read()).decode('ascii')

html = open(HTML, encoding='utf-8').read()
for n in NAMES:
    tok = '__DRG_%s__' % n.upper()
    assert tok in html, 'missing token ' + tok
    html = html.replace(tok, uris[n])
assert '__DRG_' not in html
for n in NAMES:
    assert len(uris[n]) > 10000
open(HTML, 'w', encoding='utf-8').write(html)
print('@@ INJECTED total html bytes = %d' % len(html))
