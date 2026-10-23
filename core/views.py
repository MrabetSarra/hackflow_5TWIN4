from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def csrf_failure(request, reason=''):
    """Give users a safe way to reopen forms after their CSRF cookie rotates."""
    referer = request.META.get('HTTP_REFERER', '')
    retry_url = referer if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ) else reverse('core:landing')
    response = render(request, 'core/csrf_failure.html', {'retry_url': retry_url}, status=403)
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

def landing(request):
    """
    Vue de la page d'accueil publique (Landing Page).
    Fournit un jeu de données mockées pour un affichage réaliste.
    """
    context = {
        'hackathon_name': 'HackFlow 2026',
        'tagline': 'La plateforme collaborative des hackathons étudiants de nouvelle génération.',
        'stats': [
            {'label': 'Étudiants inscrits', 'value': '520', 'icon': 'bi-people-fill', 'color': 'primary'},
            {'label': 'Équipes en compétition', 'value': '92', 'icon': 'bi-diagram-3-fill', 'color': 'accent'},
            {'label': 'Mentors & Experts', 'value': '28', 'icon': 'bi-lightbulb-fill', 'color': 'success'},
            {'label': 'Enveloppe de prix', 'value': '10 000 €', 'icon': 'bi-trophy-fill', 'color': 'warning'},
        ],
        'steps': [
            {
                'num': '01',
                'title': 'Inscription & Profil de compétences',
                'desc': 'Renseignez vos technologies de prédilection (React, Django, Flutter, IA, UI/UX, etc.) et votre niveau.',
                'badge': 'Avant le 15 Octobre'
            },
            {
                'num': '02',
                'title': 'Matching & Formation d\'équipe',
                'desc': 'Trouvez les coéquipiers complémentaires manquants grâce à notre algorithme de matching par compétences.',
                'badge': 'Équipes de 4 à 5 pers.'
            },
            {
                'num': '03',
                'title': 'Sprint 48h & Mentorat en continu',
                'desc': 'Organisez vos tâches en Kanban, sollicitez les mentors sur appel vidéo et validez les jalons clés.',
                'badge': 'Accompagnement 24/7'
            },
            {
                'num': '04',
                'title': 'Pitch & Évaluation par le Jury',
                'desc': 'Déposez votre prototype fonctionnel, passez devant le jury d\'experts et tentez de remporter le podium.',
                'badge': 'Démonstration Live'
            },
        ],
        'mentors': [
            {
                'name': 'Sarah Benali',
                'role': 'Senior AI Researcher @ Inria',
                'skills': ['Python', 'PyTorch', 'LLMs', 'Prompt Eng.'],
                'photo': 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=150&auto=format&fit=crop&q=80',
            },
            {
                'name': 'Marc Dubois',
                'role': 'Cloud Architect & DevOps @ Scaleway',
                'skills': ['Docker', 'Kubernetes', 'CI/CD', 'Django'],
                'photo': 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&auto=format&fit=crop&q=80',
            },
            {
                'name': 'Léa Rousseau',
                'role': 'Head of Product Design @ Qonto',
                'skills': ['Figma', 'Design System', 'User Research', 'Pitch'],
                'photo': 'https://images.unsplash.com/photo-1580489944761-15a19d654956?w=150&auto=format&fit=crop&q=80',
            },
            {
                'name': 'Thomas Vasseur',
                'role': 'Fullstack Lead Engineer @ Vercel',
                'skills': ['Next.js', 'TypeScript', 'Tailwind', 'GraphQL'],
                'photo': 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&auto=format&fit=crop&q=80',
            },
        ],
        'faq': [
            {
                'q': 'Puis-je m\'inscrire seul si je n\'ai pas encore d\'équipe ?',
                'a': 'Absolument ! HackFlow intègre une bourse aux compétences et un module de matching qui vous mettra en relation avec d\'autres étudiants ayant des compétences complémentaires.'
            },
            {
                'q': 'Quelle est la taille recommandée pour une équipe ?',
                'a': 'Les équipes sont composées de 4 à 5 participants pour assurer un bon équilibre entre développement, design, produit et pitch.'
            },
            {
                'q': 'Comment fonctionne l\'aide des mentors pendant le sprint ?',
                'a': 'Vous soumettez un ticket d\'aide directement depuis votre tableau de bord étudiant. Le premier mentor disponible spécialisé dans votre problématique prend en charge votre appel.'
            },
            {
                'q': 'Quels sont les critères d\'évaluation finale ?',
                'a': 'Les projets sont notés selon 4 axes : Innovation & Originalité (25%), Faisabilité technique & Qualité du code (25%), Design & Expérience utilisateur (25%), et Clarté du pitch de démo (25%).'
            },
        ],
        'sponsors': ['GitHub', 'AWS Educate', 'Supabase', 'Vercel', 'Postman', 'Notion'],
    }
    return render(request, 'core/landing.html', context)
