#!/usr/bin/env python3
"""Build the deployable copy of the rent book into mozart/dist/.

index.html is kept readable in git; the deployed copy is compacted so it fits
in a single Vercel deploy call. Run from the mozart/ folder:

    python3 build.py
"""
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, 'dist')


def compact_css(css):
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    css = re.sub(r'\s*\n\s*', '', css)
    return re.sub(r'\s*([{}:;,>])\s*', r'\1', css)


def compact_js(js):
    """Drop whole-line comments, blank lines and indentation.

    Newlines are kept so automatic semicolon insertion still behaves, and only
    whole-line comments are removed so '//' inside strings (URLs) survives.
    """
    out = []
    for line in js.split('\n'):
        t = line.strip()
        if not t or t.startswith('//'):
            continue
        if t.startswith('/*') and t.endswith('*/'):
            continue
        out.append(t)
    return '\n'.join(out)


def main():
    src = open(os.path.join(HERE, 'index.html')).read()
    head, rest = src.split('<style>', 1)
    css, rest = rest.split('</style>', 1)
    body, rest = rest.split('<script>', 1)
    js, tail = rest.split('</script>', 1)

    dist_html = (head + '<style>' + compact_css(css) + '</style>'
                 + body + '<script>' + compact_js(js) + '</script>' + tail)

    os.makedirs(DIST, exist_ok=True)
    with open(os.path.join(DIST, 'index.html'), 'w') as f:
        f.write(dist_html)

    # seed.json ships minified; the rest are copied as-is
    seed = json.load(open(os.path.join(HERE, 'seed.json')))
    with open(os.path.join(DIST, 'seed.json'), 'w') as f:
        f.write(json.dumps(seed, separators=(',', ':')))
    for name in ('manifest.json', 'icon.png'):
        shutil.copyfile(os.path.join(HERE, name), os.path.join(DIST, name))

    print('source : %6d bytes' % len(src.encode()))
    print('dist   : %6d bytes' % len(dist_html.encode()))
    total = sum(os.path.getsize(os.path.join(DIST, f)) for f in os.listdir(DIST))
    print('bundle : %6d bytes across %d files' % (total, len(os.listdir(DIST))))


if __name__ == '__main__':
    main()
