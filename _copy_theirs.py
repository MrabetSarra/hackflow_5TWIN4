import subprocess

paths = [
    'hackflow/settings.py',
    'accounts/models.py',
    'accounts/admin.py',
    'core/views.py',
    'dashboard_admin/tests.py',
]

for path in paths:
    data = subprocess.run(
        ['git', 'show', ':3:' + path],
        capture_output=True, check=True,
    ).stdout
    text = data.decode('utf-8-sig')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    print('wrote', path)
