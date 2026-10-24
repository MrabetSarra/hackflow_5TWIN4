import re

path = 'dashboard_admin/views.py'
with open(path, encoding='utf-8') as fh:
    text = fh.read()
lines = text.split('\n')

out = []
i = 0
n = len(lines)
while i < n:
    line = lines[i]
    if line.startswith('<<<<<<< HEAD'):
        # find markers
        j = i + 1
        while not lines[j].startswith('======='):
            j += 1
        k = j + 1
        while not lines[k].startswith('>>>>>>>'):
            k += 1
        head = lines[i + 1:j]
        theirs = lines[j + 1:k]
        if i == 9:
            # first block: imports -> keep theirs
            out.extend(theirs)
        elif i == 23:
            out.extend(theirs)
        elif i == 150:
            out.extend(theirs)
        elif i == 750:
            out.extend(head)
        else:
            raise SystemExit('unexpected block at line %d' % (i + 1))
        i = k + 1
    else:
        out.append(line)
        i += 1

with open(path, 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(out))
print('done')
