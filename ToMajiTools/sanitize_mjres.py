import glob, sys

replacements = {
    chr(0x2665): "(сердечко)",  # ♥ is not representable in CP932
    chr(0xAB): chr(0x201C),   # « -> "
    chr(0xBB): chr(0x201D),   # » -> "
    chr(0x2014): chr(0x2015), # — (em dash) -> ― (horizontal bar)
    chr(0x2013): chr(0x2015), # – (en dash) -> ― (horizontal bar)
    chr(0x201E): chr(0x201C), # „ (low quote) -> " (left quote)
    chr(0xF3): 'o',           # ó -> o
}

for path in glob.glob('scenario/*.mjres'):
    try:
        text = open(path, encoding='utf-8').read()
    except UnicodeDecodeError:
        print(f'WARNING: cannot read {path} as utf-8, skipping', file=sys.stderr)
        continue
    changed = False
    for src, dst in replacements.items():
        if src in text:
            text = text.replace(src, dst)
            changed = True
    if changed:
        open(path, 'w', encoding='utf-8', newline='').write(text)
        print(f'Sanitised {path}')
    else:
        print(f'OK (no changes needed): {path}')
