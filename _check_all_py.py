import ast
import pathlib

bad = []
for path in pathlib.Path('.').rglob('*.py'):
    if '.git' in path.parts or '.venv' in path.parts or '__pycache__' in path.parts:
        continue
    try:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except Exception as exc:
        bad.append((str(path), str(exc)))
        print('BROKEN:', path, exc)

print('checked done, broken:', len(bad))
