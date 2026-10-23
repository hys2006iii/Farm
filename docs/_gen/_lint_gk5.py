import io, re, os, sys

base = os.path.dirname(os.path.abspath(__file__))
files = [
    os.path.join(base, 'src', '概要', '80_设计权衡与风险.md'),
    os.path.join(base, 'src', '概要', '90_界面设计.md'),
    os.path.join(base, 'src', '概要', '99_附录.md'),
]

for f in files:
    t = io.open(f, encoding='utf-8').read()
    lines = t.split('\n')
    print('==', os.path.basename(f))
    print('   first line:', repr(lines[0]))
    for m in re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', t):
        p = os.path.join(base, m.group(2))
        print('   img', m.group(1), 'OK' if os.path.exists(p) else 'MISSING', m.group(2))
    i = 0
    while i < len(lines):
        if lines[i].startswith('|'):
            block = []
            j = i
            while j < len(lines) and lines[j].startswith('|'):
                block.append(lines[j]); j += 1
            cols = [len(r.strip().strip('|').split('|')) for r in block]
            sep = block[1] if len(block) > 1 else ''
            oksep = bool(re.fullmatch(r'\|(\s*:?-{3,}:?\s*\|)+', sep.strip()))
            prev = lines[i-1] if i > 0 else ''
            print('   table line %d rows %d cols %s sep_ok %s prev %r' % (i+1, len(block), set(cols), oksep, prev[:28]))
            i = j
        else:
            i += 1
    for m in re.finditer(r'```(\w*)\n(.*?)```', t, re.S):
        print('   code', m.group(1) or '(none)', 'lines', m.group(2).count('\n'))
    for bad in ['TODO', '待补充', '本章小结', '待定', 'XX']:
        if bad in t:
            print('   !! contains', bad)
    print('   chars total %d nonspace %d cjk %d' % (len(t), len(re.sub(r'\s', '', t)), len(re.findall(r'[\u4e00-\u9fff]', t))))
