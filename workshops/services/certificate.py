"""
workshops/services/certificate.py
===================================
Generation du PDF de certificat via fpdf2.

Mise en page : A4 paysage
  - Encadre dore (border)
  - Logo HackFlow (texte stylise)
  - Nom du beneficiaire, atelier, intervenant, date, heures
  - Numero de serie + QR code vers /workshops/verify/<code>/

NOTE : Helvetica (police core FPDF) ne supporte que Latin-1.
Tous les textes inseres dans le PDF utilisent uniquement des
caracteres ASCII / Latin-1 pour eviter FPDFUnicodeEncodingException.

Sans cle API requise.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Polices Unicode candidates : DejaVu (Linux), Arial (Windows/macOS).
# Si aucune n'est disponible, on retombe sur Helvetica + translittération.
_FONT_CANDIDATES = [
    (
        Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'DejaVuSans.ttf',
        Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'DejaVuSans-Bold.ttf',
        Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'DejaVuSans-Oblique.ttf',
    ),
    (
        Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'arial.ttf',
        Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'arialbd.ttf',
        Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'ariali.ttf',
    ),
    (
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf'),
    ),
    (
        Path('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'),
        Path('/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
        Path('/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf'),
    ),
    (
        Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
        Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
        Path('/System/Library/Fonts/Supplemental/Arial Italic.ttf'),
    ),
]


def _register_unicode_font(pdf):
    """Enregistre une police Unicode si disponible.

    Retourne ``(famille, styles_disponibles)``. ``(None, set())`` signifie
    qu'il faut utiliser Helvetica (Latin-1 uniquement).
    """
    for regular, bold, italic in _FONT_CANDIDATES:
        if not regular.exists():
            continue
        try:
            pdf.add_font('CertFont', '', str(regular))
            styles = {''}
            if bold.exists():
                pdf.add_font('CertFont', 'B', str(bold))
                styles.add('B')
            if italic.exists():
                pdf.add_font('CertFont', 'I', str(italic))
                styles.add('I')
            logger.info('Police certificat : %s', regular)
            return 'CertFont', styles
        except Exception as exc:
            logger.info('Police %s inutilisable : %s', regular, exc)
    logger.info('Aucune police Unicode trouvée : certificat en Latin-1.')
    return None, set()


def _draw_border(pdf):
    """Dessine un encadre dore sur la page courante."""
    pdf.set_draw_color(212, 175, 55)   # or
    pdf.set_line_width(3)
    pdf.rect(8, 8, pdf.w - 16, pdf.h - 16)
    pdf.set_line_width(1)
    pdf.rect(11, 11, pdf.w - 22, pdf.h - 22)


def _safe(text: str) -> str:
    """
    Remplace les caracteres non-Latin-1 par leur equivalent ASCII
    pour eviter FPDFUnicodeEncodingException avec Helvetica.
    """
    replacements = {
        '\u2014': '-',   # em dash
        '\u2013': '-',   # en dash
        '\u2019': "'",   # right single quotation
        '\u2018': "'",   # left single quotation
        '\u201c': '"',   # left double quotation
        '\u201d': '"',   # right double quotation
        '\u00e9': 'e',   # e accent aigu
        '\u00e8': 'e',   # e accent grave
        '\u00ea': 'e',   # e accent circumflex
        '\u00eb': 'e',   # e trema
        '\u00e0': 'a',   # a accent grave
        '\u00e2': 'a',   # a accent circumflex
        '\u00f4': 'o',   # o accent circumflex
        '\u00fb': 'u',   # u accent circumflex
        '\u00f9': 'u',   # u accent grave
        '\u00fc': 'u',   # u umlaut
        '\u00ee': 'i',   # i accent circumflex
        '\u00ef': 'i',   # i trema
        '\u00e7': 'c',   # c cedille
        '\u00c9': 'E',   # E accent aigu
        '\u00c0': 'A',   # A accent grave
        '\u00ab': '"',   # guillemet gauche
        '\u00bb': '"',   # guillemet droit
        '\u2026': '...', # ellipsis
        '\u00b0': 'deg', # degre
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    # Encode en Latin-1 en ignorant les caracteres restants
    return text.encode('latin-1', errors='replace').decode('latin-1')


def generate_certificate_pdf(cert) -> bytes | None:
    """
    Genere le PDF du certificat et retourne les octets bruts.
    Retourne None si fpdf2 n'est pas installe.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        logger.warning('fpdf2 non installe : generation PDF desactivee.')
        return None

    # -- Calcul de la duree -------------------------------------------
    hours_val = float(cert.hours) if cert.hours else 1.0
    h_int = int(hours_val)
    m_int = int((hours_val - h_int) * 60)
    duration_str = f'{h_int}h{m_int:02d}' if m_int else f'{h_int}h'

    issued_str = cert.issued_at.strftime('%d/%m/%Y') if cert.issued_at else '-'

    # -- Initialisation FPDF (A4 paysage) ----------------------------
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    family, styles = _register_unicode_font(pdf)

    def set_font(style, size):
        if family:
            pdf.set_font(family, style if style in styles else '', size)
        else:
            pdf.set_font('Helvetica', style, size)

    def text(value):
        """Conserve les accents si une police Unicode est disponible."""
        return str(value) if family else _safe(str(value))

    # Fond blanc
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(0, 0, pdf.w, pdf.h, 'F')

    # Encadre dore
    _draw_border(pdf)

    # -- En-tete : logo HackFlow -----------------------------------
    set_font('B', 32)
    pdf.set_text_color(30, 30, 30)
    pdf.set_xy(0, 22)
    pdf.cell(pdf.w / 2 - 22, 12, 'Hack', align='R')

    # "Flow" en couleur primaire — indigo approx
    pdf.set_text_color(99, 102, 241)
    pdf.set_xy(pdf.w / 2, 22)
    pdf.cell(pdf.w / 2, 12, 'Flow', align='L')

    # Sous-titre
    set_font('', 11)
    pdf.set_text_color(120, 120, 120)
    pdf.set_xy(0, 36)
    pdf.cell(pdf.w, 7, text('Plateforme d\'ateliers & de formation'), align='C',
             new_x='LMARGIN', new_y='NEXT')

    # -- Ligne de separation or -----------------------------------
    pdf.set_draw_color(212, 175, 55)
    pdf.set_line_width(0.8)
    pdf.line(30, 46, pdf.w - 30, 46)

    # -- Corps principal ------------------------------------------
    set_font('', 13)
    pdf.set_text_color(80, 80, 80)
    pdf.set_xy(0, 52)
    pdf.cell(pdf.w, 8, text('Ce certificat est décerné à'), align='C',
             new_x='LMARGIN', new_y='NEXT')

    # Nom du beneficiaire
    full_name = text(cert.user.get_full_name() or cert.user.username)
    set_font('B', 28)
    pdf.set_text_color(30, 30, 30)
    pdf.set_xy(0, 62)
    pdf.cell(pdf.w, 14, full_name, align='C',
             new_x='LMARGIN', new_y='NEXT')

    # Pour avoir participe a
    set_font('', 12)
    pdf.set_text_color(80, 80, 80)
    pdf.set_xy(0, 78)
    pdf.cell(pdf.w, 7, text('pour avoir participé à l\'atelier'), align='C',
             new_x='LMARGIN', new_y='NEXT')

    # Titre de l'atelier
    set_font('B', 20)
    pdf.set_text_color(99, 102, 241)
    pdf.set_xy(0, 87)
    title = text(cert.workshop.title)
    if len(title) > 60:
        title = title[:57] + '...'
    pdf.cell(pdf.w, 10, title, align='C',
             new_x='LMARGIN', new_y='NEXT')

    # Intervenant
    set_font('I', 12)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(0, 99)
    speaker_line = text(f'Par {cert.workshop.speaker_name}')
    if cert.workshop.speaker_company:
        speaker_line += text(f' - {cert.workshop.speaker_company}')
    pdf.cell(pdf.w, 7, speaker_line, align='C',
             new_x='LMARGIN', new_y='NEXT')

    # -- Metadonnees (date, duree, n de serie) ------------------
    pdf.set_line_width(0.4)
    pdf.set_draw_color(220, 220, 220)
    pdf.line(30, 111, pdf.w - 30, 111)

    set_font('', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(30, 114)
    pdf.cell(60, 6, f'Date : {issued_str}', align='L')
    pdf.set_xy(pdf.w / 2 - 30, 114)
    pdf.cell(60, 6, f'Durée : {duration_str}', align='C')
    pdf.set_xy(pdf.w - 90, 114)
    pdf.cell(60, 6, f'No de série : {cert.serial or "-"}', align='R')

    # -- Code de verification ------------------------------------
    set_font('B', 9)
    pdf.set_text_color(150, 150, 150)
    pdf.set_xy(30, 122)
    pdf.cell(pdf.w - 60, 5, f'Code de vérification : {cert.code}', align='C')

    # -- QR code (optionnel) ------------------------------------
    try:
        import qrcode
        from django.urls import reverse
        from django.conf import settings

        verify_path = reverse('workshops:verify', kwargs={'code': cert.code})
        base_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        verify_url = base_url.rstrip('/') + verify_path

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=2,
        )
        qr.add_data(verify_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        qr_x = pdf.w - 45
        qr_y = pdf.h - 45
        pdf.image(buf, x=qr_x, y=qr_y, w=32, h=32)

        set_font('', 6)
        pdf.set_text_color(150, 150, 150)
        pdf.set_xy(qr_x - 2, qr_y + 33)
        pdf.cell(36, 4, text('Vérifier en ligne'), align='C')

    except Exception as exc:
        logger.info('QR code non genere : %s', exc)

    # -- Pied de page --------------------------------------------
    set_font('', 8)
    pdf.set_text_color(180, 180, 180)
    pdf.set_xy(0, pdf.h - 14)
    pdf.cell(pdf.w, 6,
             f'HackFlow | hackflow.app/workshops/verify/{cert.code}',
             align='C')

    return bytes(pdf.output())


def attach_pdf_to_certificate(cert) -> bool:
    """
    Genere et attache le PDF au certificat.
    Retourne True si succes, False sinon.
    """
    from django.core.files.base import ContentFile

    pdf_bytes = generate_certificate_pdf(cert)
    if not pdf_bytes:
        return False

    filename = f'certificate_{cert.code}.pdf'
    cert.pdf.save(filename, ContentFile(pdf_bytes), save=True)
    return True
