"""Local, deterministic extraction of limited career evidence from private PDFs."""
import hashlib
import re
from functools import lru_cache
from io import BytesIO

from django.conf import settings
from django.utils import timezone
from hackflow.ai_telemetry import timed_ai
from pdfminer.high_level import extract_text

from ..models import StudentCVAnalysis

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20
MIN_TEXT_FOR_OCR = 100
MIN_PAGE_TEXT_FOR_OCR = 35
OCR_DPI = 190
ANALYSIS_VERSION = 2
SKILL_ALIASES = {
    'Python': ('python',), 'Django': ('django',), 'Java': ('java',),
    'JavaScript': ('javascript', 'js'), 'TypeScript': ('typescript', 'ts'),
    'React': ('react', 'react.js', 'reactjs'), 'Next.js': ('next.js', 'nextjs'),
    'Vue.js': ('vue.js', 'vuejs'), 'Angular': ('angular', 'angularjs'),
    'Node.js': ('node.js', 'nodejs'), 'Express': ('express', 'express.js', 'expressjs'),
    'FastAPI': ('fastapi',), 'PHP': ('php',), 'C#': ('c#',), 'C++': ('c++',),
    'SQL': ('sql',), 'PostgreSQL': ('postgresql', 'postgres'), 'MySQL': ('mysql',),
    'MongoDB': ('mongodb', 'mongo'),
    'Git': ('git', 'github', 'gitlab'), 'Docker': ('docker',),
    'Kubernetes': ('kubernetes', 'k8s'), 'CI/CD': ('ci/cd', 'github actions', 'gitlab ci'),
    'AWS': ('aws', 'amazon web services'), 'Azure': ('azure',), 'GCP': ('gcp', 'google cloud'),
    'Linux': ('linux', 'ubuntu', 'debian'),
    'Figma': ('figma',), 'UI/UX': ('ui/ux', 'ux/ui', 'design system'),
    'Machine Learning': ('machine learning', 'ml'), 'Deep Learning': ('deep learning', 'dl'),
    'TensorFlow': ('tensorflow',), 'PyTorch': ('pytorch',),
    'Scikit-Learn': ('scikit-learn', 'sklearn'),
    'NLP': ('nlp', 'natural language processing'),
    'RAG': ('rag', 'retrieval-augmented generation', 'retrieval augmented generation'),
    'ChromaDB': ('chromadb', 'chroma'), 'LangChain': ('langchain',),
    'Tailwind CSS': ('tailwind', 'tailwindcss'),
    'HTML/CSS': ('html', 'css', 'html5', 'css3'),
    'REST API': ('rest api', 'restful', 'apis rest', 'api rest'),
    'Flutter': ('flutter',),
}
LANGUAGES = ('Arabic', 'English', 'French', 'German', 'Italian', 'Spanish', 'Turkish')


@lru_cache(maxsize=1)
def _ocr_engine():
    """Load the local OCR engine once per application process."""
    from rapidocr import RapidOCR

    return RapidOCR()


def _text_density(value):
    return len(re.sub(r'[^\w]', '', value or '', flags=re.UNICODE))


def _ocr_sparse_pages(content):
    """Read selectable text and OCR only sparse pages, entirely on this server."""
    import pymupdf

    page_texts = []
    ocr_attempted = False
    engine = None
    with pymupdf.open(stream=content, filetype='pdf') as document:
        for page in document[:MAX_PDF_PAGES]:
            text = page.get_text('text') or ''
            if _text_density(text) < MIN_PAGE_TEXT_FOR_OCR:
                ocr_attempted = True
                if engine is None:
                    engine = _ocr_engine()
                pixmap = page.get_pixmap(dpi=getattr(settings, 'CV_OCR_DPI', OCR_DPI), alpha=False)
                result = engine(pixmap.tobytes('png'))
                recognized = '\n'.join(getattr(result, 'txts', None) or [])
                if _text_density(recognized) > _text_density(text):
                    text = recognized
            if text.strip():
                page_texts.append(text.strip())
    return '\n'.join(page_texts), ocr_attempted


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


@timed_ai('cv_extraction_ocr')
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
    cached_data = cached.structured_data if cached and isinstance(cached.structured_data, dict) else {}
    if cached and not force and cached_data.get('analysis_version') == ANALYSIS_VERSION:
        return {'status': cached.status, 'analyzed_at': cached.analyzed_at, 'cv_digest': digest,
                'data': cached_data, 'ocr_status': cached_data.get('ocr_status', 'not_needed')}
    if cached and cached_data.get('analysis_version') != ANALYSIS_VERSION:
        # Older analyses may have cached scanned PDFs as empty before OCR existed.
        user.career_match_cache.all().delete()
    if not content.startswith(b'%PDF-'):
        status, data, ocr_status = StudentCVAnalysis.Status.UNREADABLE, {}, 'not_needed'
    else:
        pdf_parse_failed = False
        try:
            text = extract_text(BytesIO(content), maxpages=MAX_PDF_PAGES) or ''
        except Exception:
            text = ''
            pdf_parse_failed = True
        try:
            ocr_status = 'not_needed'
            if _text_density(text) < MIN_TEXT_FOR_OCR:
                try:
                    ocr_text, ocr_attempted = _ocr_sparse_pages(content)
                    if ocr_attempted:
                        ocr_status = 'used' if _text_density(ocr_text) else 'no_text'
                    if _text_density(ocr_text) > _text_density(text):
                        text = ocr_text
                except Exception:
                    # OCR is best-effort: never log or persist document/parser details.
                    ocr_status = 'unavailable'
            if not text.strip():
                status = (StudentCVAnalysis.Status.UNREADABLE if pdf_parse_failed and ocr_status == 'unavailable'
                          else StudentCVAnalysis.Status.EMPTY)
                data = {}
            else:
                status, data = StudentCVAnalysis.Status.READY, _extract_profile(text[:250_000])
            data['ocr_status'] = ocr_status
        except Exception:
            # Never log or persist parser errors that may include document content.
            status, data, ocr_status = StudentCVAnalysis.Status.UNREADABLE, {}, 'not_needed'
    data['analysis_version'] = ANALYSIS_VERSION
    data.setdefault('ocr_status', ocr_status)
    analysis, _ = StudentCVAnalysis.objects.update_or_create(
        user=user,
        defaults={'cv_digest': digest, 'status': status, 'structured_data': data, 'analyzed_at': timezone.now()},
    )
    return {'status': analysis.status, 'analyzed_at': analysis.analyzed_at, 'cv_digest': digest,
            'data': analysis.structured_data, 'ocr_status': ocr_status}
