import glob
import re

pats = [r"@bp\.(route|get|post)\('/api/"]
files = glob.glob('qinghe/routes/*.py')
for f in files:
    for i, line in enumerate(open(f, encoding='utf-8', errors='replace').read().split('\n'), 1):
        for p in pats:
            if re.search(p, line):
                print('%s:%d: %s' % (f, i, line.strip()[:110]))
                break
