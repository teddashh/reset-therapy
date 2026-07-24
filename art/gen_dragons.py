#!/usr/bin/env python3
"""Generate the four golden dragon busts (dark dungeon background PNG) via gpt-image-2.

Usage:
    OPENAI_API_KEY=sk-... python3 gen_dragons.py

Writes drg_{codex,claude,gemini,grok}.png into ./out/.
"""
import base64
import json
import os
import sys
import time
import urllib.request

KEY = os.environ.get('OPENAI_API_KEY')
assert KEY, 'set OPENAI_API_KEY in the environment'

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
os.makedirs(OUT, exist_ok=True)

STYLE = ('Ornate golden dragon head bust portrait, cropped at the upper chest like a '
         'trophy bust, subject centered and filling most of the frame with a little '
         'headroom above the head. Dark-fantasy video game relic style: polished '
         'golden-bronze metal with intricately engraved scales, dramatic warm '
         'torchlight rim lighting, rich painterly detail, slight low-angle hero shot. '
         'Background: plain very dark desaturated charcoal dungeon stone wall, softly '
         'vignetted, kept dark and simple so the golden dragon pops. '
         'No text, no letters, no watermark.')

DRAGONS = {
    'codex': ('A fierce majestic war dragon: long swept-back curved horns, bared metal '
              'fangs in a controlled snarl, fierce glowing amber eyes, regal and menacing.'),
    'claude': ('A fierce majestic war dragon: a crown of many radiating horns bursting '
               'outward like a star, jaws slightly open showing fangs, intense glowing '
               'copper-orange eyes, imperial menace.'),
    'gemini': ('A silly goofy comic-relief dragon in the exact same golden metal style: '
               'big googly derpy cartoon eyes pointing in different directions, wide dumb '
               'grin, long pink tongue flopping out sideways, small floppy bent horns, '
               'cheerful idiot energy, still made of engraved golden metal.'),
    'grok': ('A fierce sleek war dragon: angular blade-like swept horns, narrowed glowing '
             'ice-blue eyes, sharp chin spikes and angular jaw armor, cold calculating menace.'),
}


def gen(name, desc, tries=3):
    body = json.dumps({
        'model': 'gpt-image-2',
        'prompt': STYLE + ' ' + desc,
        'size': '1024x1536',
        'quality': 'high',
        'n': 1,
    }).encode('utf-8')
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(
            'https://api.openai.com/v1/images/generations',
            data=body,
            headers={'Authorization': 'Bearer ' + KEY,
                     'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read().decode('utf-8'))
            png = base64.b64decode(data['data'][0]['b64_json'])
            path = os.path.join(OUT, 'drg_%s.png' % name)
            with open(path, 'wb') as f:
                f.write(png)
            print('@@ OK %s bytes=%d' % (name, len(png)), flush=True)
            return True
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', 'replace')[:400]
            print('@@ HTTP %s %s attempt %d: %s' % (e.code, name, attempt, msg), flush=True)
            if e.code in (400, 401, 402, 403) or 'billing' in msg.lower():
                print('@@ FATAL billing/auth/prompt problem - stopping', flush=True)
                return False
            time.sleep(8)
        except Exception as e:  # noqa: BLE001
            print('@@ ERR %s attempt %d: %s' % (name, attempt, e), flush=True)
            time.sleep(8)
    return False


ok = True
for n, d in DRAGONS.items():
    ok = gen(n, d) and ok
print('@@ DONE all_ok=%s' % ok, flush=True)
sys.exit(0 if ok else 1)
