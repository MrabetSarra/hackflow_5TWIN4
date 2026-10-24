"""Deterministic technology-stack detection for repository summaries.

The stack is computed from the files that are really in the repository
(manifest files, source extensions, project markers) so the AI summary can be
grounded in facts instead of guesses made from a README.
"""
import json
import re
from collections import Counter
from pathlib import Path

from . import git_service

LANGUAGES = {
    '.py': 'Python', '.pyw': 'Python', '.ipynb': 'Python',
    '.js': 'JavaScript', '.mjs': 'JavaScript', '.cjs': 'JavaScript', '.jsx': 'JavaScript',
    '.ts': 'TypeScript', '.tsx': 'TypeScript',
    '.php': 'PHP', '.phtml': 'PHP', '.blade.php': 'PHP',
    '.java': 'Java', '.kt': 'Kotlin', '.kts': 'Kotlin', '.scala': 'Scala',
    '.cs': 'C#', '.fs': 'F#', '.vb': 'Visual Basic',
    '.go': 'Go', '.rb': 'Ruby', '.rs': 'Rust', '.swift': 'Swift',
    '.vue': 'Vue', '.svelte': 'Svelte', '.astro': 'Astro',
    '.html': 'HTML', '.htm': 'HTML', '.css': 'CSS', '.scss': 'SCSS', '.sass': 'Sass',
    '.sql': 'SQL', '.sh': 'Shell', '.bash': 'Shell', '.ps1': 'PowerShell',
    '.r': 'R', '.lua': 'Lua', '.dart': 'Dart', '.ex': 'Elixir', '.exs': 'Elixir',
}

VENDORED_SEGMENTS = {
    'vendor', 'node_modules', 'dist', 'build', 'coverage', 'third_party', 'third-party',
    'bower_components', 'site-packages', '.venv', 'venv',
}

VENDORED_PREFIXES = ('storage/framework', 'public/build')

MANIFEST_FILES = {
    'package.json', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'requirements.txt', 'requirements-dev.txt', 'pyproject.toml', 'pipfile', 'setup.py', 'setup.cfg',
    'composer.json', 'composer.lock', 'artisan',
    'pom.xml', 'build.gradle', 'build.gradle.kts', 'settings.gradle',
    'gemfile', 'go.mod', 'cargo.toml',
    'dockerfile', 'docker-compose.yml', 'docker-compose.yaml', 'compose.yml',
    'angular.json', 'manage.py', 'nuxt.config.ts', 'nuxt.config.js',
    'next.config.js', 'next.config.mjs', 'next.config.ts',
    'vite.config.js', 'vite.config.ts', 'svelte.config.js', 'astro.config.mjs',
    'tsconfig.json', 'tailwind.config.js', 'tailwind.config.ts', 'postcss.config.js',
    'webpack.config.js', 'nx.json', 'turbo.json',
}

# Dependency name -> human readable technology.
FRAMEWORK_HINTS = {
    'react': 'React', 'react-dom': 'React', 'react-router': 'React Router', 'react-router-dom': 'React Router',
    '@angular/core': 'Angular', '@angular/cli': 'Angular', '@angular/common': 'Angular',
    'next': 'Next.js', 'nuxt': 'Nuxt', 'vue': 'Vue', 'svelte': 'Svelte',
    '@sveltejs/kit': 'SvelteKit', 'express': 'Express', '@nestjs/core': 'NestJS', 'koa': 'Koa',
    'gatsby': 'Gatsby', 'remix': 'Remix', '@remix-run/react': 'Remix',
    'django': 'Django', 'djangorestframework': 'Django REST Framework', 'flask': 'Flask',
    'fastapi': 'FastAPI', 'starlette': 'Starlette', 'uvicorn': 'Uvicorn', 'gunicorn': 'Gunicorn',
    'celery': 'Celery', 'sqlalchemy': 'SQLAlchemy', 'pydantic': 'Pydantic', 'tornado': 'Tornado',
    'laravel/framework': 'Laravel', 'laravel/laravel': 'Laravel', 'symfony/framework-bundle': 'Symfony',
    'symfony/console': 'Symfony', 'laravel/sanctum': 'Laravel Sanctum', 'laravel/tinker': 'Laravel',
    'spring-boot-starter': 'Spring Boot', 'spring-boot-starter-web': 'Spring Boot',
    'org.springframework.boot': 'Spring Boot', 'rails': 'Ruby on Rails', 'sinatra': 'Sinatra',
    'gin-gonic/gin': 'Gin', 'gorm.io/gorm': 'GORM', 'actix-web': 'Actix', 'rocket': 'Rocket',
    'axum': 'Axum', 'inertiajs/inertia-laravel': 'Inertia.js',
}

LIBRARY_HINTS = {
    'bootstrap': 'Bootstrap', 'tailwindcss': 'Tailwind CSS', 'jquery': 'jQuery',
    'chart.js': 'Chart.js', 'react-chartjs-2': 'Chart.js', 'apexcharts': 'ApexCharts',
    'axios': 'Axios', 'lodash': 'Lodash', 'moment': 'Moment.js', 'date-fns': 'date-fns',
    'typescript': 'TypeScript', 'prisma': 'Prisma', 'mongoose': 'Mongoose', 'sequelize': 'Sequelize',
    'firebase': 'Firebase', '@supabase/supabase-js': 'Supabase', 'supabase': 'Supabase',
    'socket.io': 'Socket.IO', 'socket.io-client': 'Socket.IO', 'leaflet': 'Leaflet',
    'mapbox-gl': 'Mapbox GL', 'three': 'Three.js', 'd3': 'D3.js', 'redux': 'Redux',
    '@reduxjs/toolkit': 'Redux Toolkit', 'zustand': 'Zustand', 'lucide-react': 'Lucide',
    'pandas': 'pandas', 'numpy': 'NumPy', 'scikit-learn': 'scikit-learn', 'tensorflow': 'TensorFlow',
    'torch': 'PyTorch', 'opencv-python': 'OpenCV', 'pillow': 'Pillow', 'matplotlib': 'Matplotlib',
    'requests': 'requests', 'beautifulsoup4': 'Beautiful Soup', 'beautifulsoup': 'Beautiful Soup',
    'jwt': 'PyJWT', 'passport': 'Passport', 'bcrypt': 'bcrypt', 'nodemon': 'nodemon',
    'vite': 'Vite', 'webpack': 'Webpack', 'esbuild': 'esbuild', 'jest': 'Jest', 'vitest': 'Vitest',
    'pytest': 'pytest', 'phpunit/phpunit': 'PHPUnit', 'guzzlehttp/guzzle': 'Guzzle',
}

# Project marker file -> (technology, category).
MARKER_FILES = {
    'dockerfile': ('Docker', 'tool'),
    'docker-compose.yml': ('Docker Compose', 'tool'),
    'docker-compose.yaml': ('Docker Compose', 'tool'),
    'compose.yml': ('Docker Compose', 'tool'),
    'angular.json': ('Angular', 'framework'),
    'nx.json': ('Nx', 'tool'),
    'turbo.json': ('Turborepo', 'tool'),
    'manage.py': ('Django', 'framework'),
    'artisan': ('Laravel', 'framework'),
    'next.config.js': ('Next.js', 'framework'),
    'next.config.mjs': ('Next.js', 'framework'),
    'next.config.ts': ('Next.js', 'framework'),
    'nuxt.config.ts': ('Nuxt', 'framework'),
    'nuxt.config.js': ('Nuxt', 'framework'),
    'svelte.config.js': ('Svelte', 'framework'),
    'astro.config.mjs': ('Astro', 'framework'),
    'vite.config.js': ('Vite', 'tool'),
    'vite.config.ts': ('Vite', 'tool'),
    'tailwind.config.js': ('Tailwind CSS', 'tool'),
    'tailwind.config.ts': ('Tailwind CSS', 'tool'),
    'webpack.config.js': ('Webpack', 'tool'),
    'tsconfig.json': ('TypeScript', 'tool'),
}


def _is_vendored(path):
    lowered = path.lower()
    parts = lowered.split('/')
    for part in parts[:-1]:
        if part in VENDORED_SEGMENTS:
            return True
    return lowered.startswith(VENDORED_PREFIXES)


def _language_of(path):
    lowered = path.lower()
    if lowered.endswith('.blade.php'):
        return 'PHP'
    return LANGUAGES.get(Path(lowered).suffix)


def _read_text(repository, blob, limit=200_000):
    try:
        return git_service.blob_text(repository, blob, limit=limit)
    except git_service.GitError:
        return ''


def _package_json_dependencies(text):
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return []
    names = []
    for key in ('dependencies', 'devDependencies', 'peerDependencies'):
        block = payload.get(key)
        if isinstance(block, dict):
            names.extend(block.keys())
    return names


def _requirement_names(text):
    names = []
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        line = line.split(';', 1)[0]
        name = re.split(r'[\[\(<>=!~]', line.strip(), 1)[0]
        name = name.strip().strip('"\'')
        if name:
            names.append(name)
    return names


def _toml_requirements(text):
    names = []
    for block in re.finditer(r'dependencies\s*=\s*\[(.*?)\]', text, re.S):
        for entry in re.findall(r'["\']([^"\']+)["\']', block.group(1)):
            names.append(re.split(r'[\s\[\]<>=!~;]', entry, 1)[0].strip().lower())
    for name in re.findall(r'^\s*([A-Za-z0-9_.-]+)\s*=\s*["\']', text, re.M):
        names.append(name.lower())
    return names


def _composer_requirements(text):
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return []
    names = []
    for key in ('require', 'require-dev'):
        block = payload.get(key)
        if isinstance(block, dict):
            names.extend(block.keys())
    return names


def _maven_dependencies(text):
    return re.findall(r'<artifactId>([^<]+)</artifactId>', text)


def _gradle_dependencies(text):
    return [item.split(':')[1] if ':' in item else item
            for item in re.findall(r"['\"]([\w.-]+:[\w.-]+(?::[^'\"]+)?)['\"]", text)]


def _gem_dependencies(text):
    return re.findall(r"^\s*gem\s+['\"]([^'\"]+)['\"]", text, re.M)


def _go_dependencies(text):
    names = []
    for block in re.finditer(r'require\s*\((.*?)\)', text, re.S):
        names.extend(re.findall(r'^\s*([\w./-]+)', block.group(1), re.M))
    names.extend(re.findall(r'^require\s+([\w./-]+)', text, re.M))
    return names


def _cargo_dependencies(text):
    names = []
    for block in re.finditer(r'\[dependencies\](.*?)(?=\n\[|\Z)', text, re.S):
        names.extend(re.findall(r'^\s*([A-Za-z0-9_-]+)\s*=', block.group(1), re.M))
    return names


def _dotnet_dependencies(text):
    return re.findall(r'Include="([^"]+)"', text)


DEPENDENCY_READERS = {
    'package.json': _package_json_dependencies,
    'requirements.txt': _requirement_names,
    'requirements-dev.txt': _requirement_names,
    'pipfile': _requirement_names,
    'setup.py': _requirement_names,
    'setup.cfg': _requirement_names,
    'pyproject.toml': _toml_requirements,
    'composer.json': _composer_requirements,
    'pom.xml': _maven_dependencies,
    'build.gradle': _gradle_dependencies,
    'build.gradle.kts': _gradle_dependencies,
    'gemfile': _gem_dependencies,
    'go.mod': _go_dependencies,
    'cargo.toml': _cargo_dependencies,
}


def detect_stack(repository, branch):
    """Describe the technologies that the repository really uses."""
    entries = git_service.tree_entries(repository, branch)

    def read_text(path):
        return git_service.blob_text(repository, entries[path], limit=200_000)

    return detect_stack_from_paths(entries.keys(), read_text)


def detect_stack_from_paths(paths, read_text):
    """Describe the technologies used by a set of files.

    ``read_text`` returns the content of a path, so the same detection works
    for a branch and for an uploaded snapshot that is not committed yet.
    """
    paths = sorted(paths)
    source_paths = [path for path in paths if not _is_vendored(path)]

    language_counts = Counter()
    for path in source_paths:
        language = _language_of(path)
        if language:
            language_counts[language] += 1

    manifests, dependencies = [], []
    for path in paths:
        name = path.rsplit('/', 1)[-1].lower()
        if name in MANIFEST_FILES:
            content = read_text(path)
            reader = DEPENDENCY_READERS.get(name)
            if reader:
                dependencies.extend(reader(content))
            if name not in manifests:
                manifests.append(name)
        elif name.endswith('.csproj'):
            dependencies.extend(_dotnet_dependencies(read_text(path)))
            if name not in manifests:
                manifests.append(name)

    frameworks, libraries = [], []
    for dependency in dependencies:
        key = dependency.strip().lower()
        if not key:
            continue
        label = FRAMEWORK_HINTS.get(key)
        if label:
            if label not in frameworks:
                frameworks.append(label)
            continue
        label = LIBRARY_HINTS.get(key)
        if label and label not in libraries:
            libraries.append(label)

    known = set(frameworks) | set(libraries)
    for path in paths:
        marker = MARKER_FILES.get(path.rsplit('/', 1)[-1].lower())
        if not marker:
            continue
        label, category = marker
        if label in known:
            continue
        known.add(label)
        if category == 'framework':
            frameworks.append(label)
        else:
            libraries.append(label)

    runtimes = []
    for manifest, runtime in RUNTIMES.items():
        if manifest in manifests and runtime not in runtimes:
            runtimes.append(runtime)

    for manifest, tool in MANIFEST_TOOLS.items():
        if manifest in manifests and tool not in libraries:
            libraries.append(tool)

    return {
        'languages': language_counts.most_common(),
        'frameworks': frameworks,
        'libraries': libraries,
        'runtimes': runtimes,
        'manifests': manifests,
        'paths': source_paths,
        'total_files': len(paths),
    }


NOISE_FILES = {
    '.gitattributes', '.gitignore', '.editorconfig', '.env', '.env.example', '.env.dist',
    'package-lock.json', 'composer.lock', 'yarn.lock', 'pnpm-lock.yaml', 'npm-shrinkwrap.json',
    'docker-compose.yml', 'docker-compose.yaml', 'phpunit.xml', 'artisan', 'favicon.ico',
}


RUNTIMES = {
    'package.json': 'Node.js',
    'composer.json': 'PHP',
    'requirements.txt': 'Python',
    'requirements-dev.txt': 'Python',
    'pyproject.toml': 'Python',
    'pipfile': 'Python',
    'setup.py': 'Python',
    'go.mod': 'Go',
    'cargo.toml': 'Rust',
    'gemfile': 'Ruby',
    'pom.xml': 'Java',
    'build.gradle': 'Java',
    'build.gradle.kts': 'Java',
}

# Vocabulary used to spot a technology the repository does not actually use.
TECHNOLOGY_NAMES = {
    'react', 'react native', 'angular', 'angularjs', 'vue', 'vue.js', 'svelte', 'sveltekit',
    'next.js', 'nuxt', 'nuxt.js', 'ember', 'jquery', 'backbone',
    'django', 'flask', 'fastapi', 'rails', 'ruby on rails', 'sinatra', 'laravel', 'symfony',
    'spring boot', 'spring', 'express', 'node.js', 'node', 'nestjs', 'koa', 'gatsby',
    'php', 'python', 'java', 'kotlin', 'c#', '.net', 'dotnet', 'go', 'golang', 'rust', 'swift',
    'typescript', 'javascript', 'html', 'css', 'scss', 'sass', 'tailwind', 'tailwind css',
    'bootstrap', 'material ui', 'redux', 'axios', 'vite', 'webpack', 'parcel', 'rollup',
    'docker', 'kubernetes', 'terraform', 'ansible', 'aws', 'azure', 'gcp', 'heroku',
    'vercel', 'netlify', 'firebase', 'supabase', 'mongodb', 'mongo', 'postgres', 'postgresql',
    'mysql', 'sqlite', 'sql server', 'redis', 'elasticsearch', 'graphql', 'grpc',
    'rest api', 'restful', 'websocket', 'websockets', 'jwt', 'oauth', 'blade', 'eloquent',
    'wordpress', 'magento', 'shopify', 'flutter', 'ionic', 'cordova', 'unity', 'unreal',
    'tensorflow', 'pytorch', 'opencv', 'pandas', 'numpy', 'scikit-learn', 'pytorch',
}


MANIFEST_TOOLS = {
    'composer.json': 'Composer',
    'package-lock.json': 'npm',
    'yarn.lock': 'Yarn',
    'pnpm-lock.yaml': 'pnpm',
    'phpunit.xml': 'PHPUnit',
}


def _is_interesting(path):
    name = path.rsplit('/', 1)[-1]
    if name in NOISE_FILES or name.startswith('.'):
        return False
    return len(name) > 3


def _structure_lines(paths, limit=120, per_folder=12):
    """Compact folder view: top level counts plus a sample of real file paths."""
    folders = Counter()
    root_files = []
    per_top = {}
    for path in paths:
        if '/' in path:
            top = path.split('/')[0]
            folders[top] += 1
            per_top.setdefault(top, []).append(path)
        else:
            root_files.append(path)
    lines = []
    if folders:
        summary = ', '.join(f'{name}/ ({count} files)' for name, count in sorted(folders.items()))
        lines.append(f'Top-level folders: {summary}')
    if root_files:
        lines.append('Root files: ' + ', '.join(sorted(root_files)[:25]))
    lines.append('Source files by folder:')
    shown = 0
    for top in sorted(per_top):
        candidates = sorted(per_top[top])
        interesting = [path for path in candidates if _is_interesting(path)]
        for path in (interesting or candidates)[:per_folder]:
            if shown >= limit:
                break
            lines.append(f'  {path}')
            shown += 1
    return lines


def find_readme(repository, branch, limit=8000):
    """Return the README content, preferring the shallowest one in the tree."""
    entries = git_service.tree_entries(repository, branch)
    candidates = [path for path in entries if path.lower().endswith('readme.md')]
    if not candidates:
        return ''
    candidates.sort(key=lambda path: (path.count('/'), len(path), path))
    return _read_text(repository, entries[candidates[0]], limit=limit)


def describe_stack(stack):
    """Render the detected stack as a compact, factual block."""
    languages = stack['languages']
    lines = ['Detected stack (computed from the repository files):']
    if languages:
        rendered = ', '.join(f'{name} ({count} files)' for name, count in languages[:8])
        lines.append(f'- Languages: {rendered}')
    else:
        lines.append('- Languages: no recognised source files')
    lines.append(f"- Frameworks: {', '.join(stack['frameworks']) if stack['frameworks'] else 'none detected'}")
    lines.append(f"- Libraries & tools: {', '.join(stack['libraries'][:12]) if stack['libraries'] else 'none detected'}")
    lines.append(f"- Manifest files: {', '.join(stack['manifests']) if stack['manifests'] else 'none detected'}")
    lines.append(f"- Total files: {stack['total_files']}")
    return '\n'.join(lines)


STACK_LABELS = {
    'languages': 'The project is written in {items}.',
    'frameworks': 'It is built with {items}.',
    'libraries': 'It also uses {items}.',
    'libraries & tools': 'It also uses {items}.',
}


def _stack_label_sentences(text):
    """Turn copied DETECTED STACK label lines into readable sentences."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(('manifest file', 'total file', 'detected stack')):
            continue
        for label, template in STACK_LABELS.items():
            if lowered.startswith(label + ':'):
                items = re.sub(r'\(\d+\s+files?\)', '', stripped.split(':', 1)[1])
                items = ', '.join(part.strip() for part in items.split(',') if part.strip())
                if items:
                    items = re.sub(r',(?=[^,]*$)', ' and', items)
                    lines.append(template.format(items=items))
                break
        else:
            lines.append(line)
    return '\n'.join(lines)


def _drop_heading_lines(text):
    """Remove standalone title lines such as 'Technology Stack'."""
    lines = text.splitlines()
    kept = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped and len(stripped) < 90 and stripped[-1] not in '.!?,;)' and not stripped[0].islower():
            previous_blank = index == 0 or not lines[index - 1].strip()
            next_blank = index == len(lines) - 1 or not lines[index + 1].strip()
            if previous_blank or next_blank:
                continue
        kept.append(line)
    return '\n'.join(kept)


def _join(items):
    items = [item for item in items if item]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    return ', '.join(items[:-1]) + ' and ' + items[-1]


def stack_sentence(stack):
    """Build the technology paragraph from the detected stack only."""
    sentences = []
    frameworks = stack['frameworks']
    if frameworks:
        sentences.append(f'The project is built with {_join(frameworks)}.')
    languages = [name for name, _ in stack['languages']]
    if languages:
        sentences.append(f'It is written in {_join(languages)}.')
    tools = list(stack['libraries'])
    for runtime in stack['runtimes']:
        if runtime not in tools and runtime not in languages:
            tools.append(runtime)
    if tools:
        sentences.append(f'It also uses {_join(tools)}.')
    if not sentences:
        sentences.append('The repository does not contain any recognisable source file yet.')
    return ' '.join(sentences)


def allowed_technologies(stack):
    """Lowercase names of every technology the repository really uses."""
    allowed = {label.lower() for label in stack['frameworks']}
    allowed |= {label.lower() for label in stack['libraries']}
    allowed |= {label.lower() for label in stack['runtimes']}
    allowed |= {name.lower() for name, _ in stack['languages']}
    allowed |= {'php', 'python', 'javascript', 'typescript', 'html', 'css', 'java', 'go', 'rust', 'ruby', 'sql'}
    if 'laravel' in allowed:
        allowed |= {'blade', 'eloquent', 'artisan', 'phpunit', 'npm', 'node'}
    if 'django' in allowed:
        allowed |= {'orm', 'pip', 'webpack'}
    return allowed


def unknown_technologies(text, stack):
    """Return technology names mentioned in the text that the project does not use."""
    allowed = allowed_technologies(stack)
    matched = set()
    lowered = (text or '').lower()
    for name in TECHNOLOGY_NAMES:
        if re.search(r'(?<![a-z0-9+#-])' + re.escape(name) + r'(?![a-z0-9+#-])', lowered):
            matched.add(name)
    # Keep only the most specific match: 'vue.js' replaces 'vue'.
    matched = {name for name in matched
               if not any(name != other and name in other for other in matched)}
    return {name for name in matched if name not in allowed}


def strip_unknown_sentences(text, unknown):
    """Remove the sentences that mention a technology the project does not use."""
    if not unknown:
        return text
    pattern = re.compile('|'.join(re.escape(name) for name in sorted(unknown)))
    kept = []
    for sentence in re.split(r'(?<=[.!?])\s+', text or ''):
        if pattern.search(sentence.lower()):
            continue
        kept.append(sentence)
    return ' '.join(part.strip() for part in kept if part.strip())


def clean_summary(text):
    """Tidy the raw model output into editable prose."""
    text = re.sub(r'(?im)^\s*paragraph\s*\d+\s*[:.\-–]\s*', '', text or '')
    text = re.sub(r'(?im)^\s*#{1,6}\s*', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'(?m)^\s*[-*\u2022]\s+', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'\b[\w.-]+/[\w./-]*\.[A-Za-z]{1,6}\b', '', text)
    text = _stack_label_sentences(text)
    text = _drop_heading_lines(text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\s+([,.;:])', r'\1', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def description_source(stack, commits, readme):
    """Source material for the descriptive part of the submission summary.

    The technology stack is deliberately left out: it is added afterwards from
    the detected stack, so the model can never describe a technology the
    repository does not use.
    """
    sections = ['Repository structure:', '\n'.join(_structure_lines(stack['paths']))]
    if readme:
        sections.append(f'README:\n{readme[:8000]}')
    if commits:
        messages = '\n'.join(f'- {item["message"]}' for item in commits)
        sections.append(f'RECENT COMMITS:\n{messages}')
    return '\n\n'.join(section for section in sections if section)
