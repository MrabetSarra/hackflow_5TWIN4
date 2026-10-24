import subprocess

incoming = subprocess.run(
    ['git', 'show', ':3:core/views.py'],
    capture_output=True, text=True, check=True,
).stdout

with open('core/views.py', encoding='utf-8') as fh:
    mine = fh.read()

if mine == incoming:
    print('IDENTICAL to incoming')
else:
    import difflib
    diff = list(difflib.unified_diff(incoming.splitlines(), mine.splitlines(), 'incoming', 'mine', lineterm=''))
    print('\n'.join(diff))
