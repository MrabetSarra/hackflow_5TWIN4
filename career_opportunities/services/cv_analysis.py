"""Local, deterministic extraction of limited career evidence from private PDFs."""
import hashlib
import re
from io import BytesIO

from django.utils import timezone
from pdfminer.high_level import extract_text

from ..models import StudentCVAnalysis

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
SKILL_ALIASES = {
    'Python': ('python',), 'Django': ('django',), 'Java': ('java',),
    'JavaScript': ('javascript', 'js'), 'TypeScript': ('typescript', 'ts'),
    'React': ('react', 'react.js', 'reactjs'), 'Vue.js': ('vue.js', 'vuejs'),
    'SQL': ('sql',), 'PostgreSQL': ('postgresql', 'postgres'), 'MySQL': ('mysql',),
    'Git': ('git',), 'Docker': ('docker',), 'Kubernetes': ('kubernetes', 'k8s'),
    'AWS': ('aws', 'amazon web services'), 'Azure': ('azure',), 'Linux': ('linux',),
    'Figma': ('figma',), 'Machine Learning': ('machine learning', 'ml'),
    'TensorFlow': ('tensorflow',), 'PyTorch': ('pytorch',), 'C++': ('c++',),
    'C#': ('c#',), 'PHP': ('php',), 'Node.js': ('node.js', 'nodejs'),
    'FastAPI': ('fastapi',), 'Flutter': ('flutter',), 'PostgreSQL': ('postgresql', 'postgres'),
}
LANGUAGES = ('Arabic', 'English', 'French', 'German', 'Italian', 'Spanish', 'Turkish')


def _evidence_line(text, term):
    for line in text.splitlines():
        if re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', line, re.I):
            clean = ' '.join(line.split())
            if 4 <= len(clean) <= 500:
                return clean
    return ''


def _language_level(text, language):
    for line in text.splitlines():
        match = re.search(r'(?<!\w)' + re.escape(language) + r'(?!\w)', line, re.I)
        if match:
            nearby = line[max(0, match.start() - 12):match.end() + 18]
            level = re.search(r'\b(C2|C1|B2|B1|A2|A1)\b', nearby, re.I)
            return level.group(1).upper() if level else ''
    return ''


def _extract_profile(text):
    skills = []
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            evidence = _evidence_line(text, alias)
            if evidence:
                skills.append({'name': canonical, 'evidence': evidence, 'source': 'cv'})
                break
    education = []
    education_terms = ('bachelor', 'licence', 'license', 'master', 'engineering degree', 'ingénieur', 'phd', 'doctorate', 'university degree')
    for line in text.splitlines():
        value = ' '.join(line.split())
        if value and len(value) <= 250 and any(term in value.casefold() for term in education_terms):
            education.append({'text': value, 'source': 'cv'})
            if len(education) == 10:
                break
    languages = []
    for language in LANGUAGES:
        evidence = _evidence_line(text, language)
        if evidence:
            proficiency = _language_level(text, language)
            languages.append({'name': language, 'proficiency': proficiency or 'not stated', 'evidence': evidence})
    experience = []
    for line in text.splitlines():
        value = ' '.join(line.split())
        if re.search(r'\b\d+\+?\s*(?:years?|ans?)\b', value, re.I) and len(value) <= 500:
            experience.append({'evidence': value, 'source': 'cv'})
            if len(experience) == 8:
                break
    projects = []
    in_projects = False
    for line in text.splitlines():
        value = ' '.join(line.split())
        if re.search(r'^\s*(projects?|projets?)\s*:?\s*$', value, re.I):
            in_projects = True
            continue
        if in_projects and re.match(r'^[A-Z][A-Z /&-]{2,}$', value):
            break
        if in_projects and 12 <= len(value) <= 350:
            projects.append({'evidence': value, 'source': 'cv'})
            if len(projects) == 12:
                break
    return {'skills': skills, 'education': education, 'languages': languages,
            'experience': experience, 'projects': projects,
            'text_characters_analyzed': len(text)}


def analyze_student_cv(user, *, force=False):
    """Return cached analysis or parse the authenticated user's private CV locally."""
    if not user.cv:
        return {'status': 'missing', 'analyzed_at': None, 'cv_digest': '', 'data': {}}
    try:
        with user.cv.open('rb') as stream:
            content = stream.read(MAX_PDF_BYTES + 1)
    except (OSError, ValueError):
        return {'status': 'unreadable', 'analyzed_at': None, 'cv_digest': '', 'data': {}}
    if len(content) > MAX_PDF_BYTES:
        return {'status': 'unreadable', 'analyzed_at': None, 'cv_digest': '', 'data': {}}
    digest = hashlib.sha256(content).hexdigest()
    cached = StudentCVAnalysis.objects.filter(user=user, cv_digest=digest).first()
    if cached and not force:
        return {'status': cached.status, 'analyzed_at': cached.analyzed_at, 'cv_digest': digest, 'data': cached.structured_data}
    if not content.startswith(b'%PDF-'):
        status, data = StudentCVAnalysis.Status.UNREADABLE, {}
    else:
        try:
            text = extract_text(BytesIO(content), maxpages=MAX_PDF_PAGES) or ''
            if not text.strip():
                status, data = StudentCVAnalysis.Status.EMPTY, {}
            else:
                status, data = StudentCVAnalysis.Status.READY, _extract_profile(text[:250_000])
        except Exception:
            # Never log or persist parser errors that may include document content.
            status, data = StudentCVAnalysis.Status.UNREADABLE, {}
    analysis, _ = StudentCVAnalysis.objects.update_or_create(
        user=user,
        defaults={'cv_digest': digest, 'status': status, 'structured_data': data, 'analyzed_at': timezone.now()},
    )
    return {'status': analysis.status, 'analyzed_at': analysis.analyzed_at, 'cv_digest': digest, 'data': analysis.structured_data}
