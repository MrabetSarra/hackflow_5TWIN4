from django.shortcuts import render

def login_view(request):
    """
    Vue de connexion visuelle.
    Permet de tester l'authentification et offre des boutons de connexion démo directe vers les 3 rôles.
    """
    context = {
        'demo_accounts': [
            {
                'role': 'Étudiant',
                'name': 'Camille Laurent',
                'email': 'camille.laurent@etu.univ.fr',
                'url': 'student:dashboard',
                'badge_color': 'primary',
                'icon': 'bi-mortarboard-fill',
            },
            {
                'role': 'Mentor',
                'name': 'Dr. Marc Dubois',
                'email': 'marc.dubois@mentor.hackflow.fr',
                'url': 'mentor:dashboard',
                'badge_color': 'secondary',
                'icon': 'bi-lightbulb-fill',
            },
            {
                'role': 'Admin (Organisateur)',
                'name': 'Alexandre Moreau',
                'email': 'alexandre.moreau@hackflow.fr',
                'url': 'dashboard_admin:dashboard',
                'badge_color': 'danger',
                'icon': 'bi-shield-lock-fill',
            },
        ]
    }
    return render(request, 'accounts/login.html', context)


def register_view(request):
    """
    Vue d'inscription avec sélection de profil et tags de compétences.
    """
    context = {
        'available_skills': [
            'Python / Django', 'React / TypeScript', 'Vue.js', 'FastAPI',
            'UI/UX & Figma', 'IA & Machine Learning', 'DevOps & Docker',
            'Flutter / Mobile', 'PostgreSQL', 'Pitch & Business Model'
        ],
        'study_levels': [
            'Licence 1 ou 2', 'Licence 3 / BUT', 'Master 1', 'Master 2 / Cycle Ingénieur', 'Autre cursus'
        ]
    }
    return render(request, 'accounts/register.html', context)


def profile_view(request):
    """
    Vue de consultation et édition visuelle du profil utilisateur.
    """
    context = {
        'user': {
            'first_name': 'Camille',
            'last_name': 'Laurent',
            'role': 'Étudiant Participant',
            'school': 'Université Polytechnique - Faculté des Sciences',
            'level': 'Licence 3 Informatique',
            'email': 'camille.laurent@etu.univ.fr',
            'github': 'camille-laurent',
            'linkedin': 'camille-laurent-dev',
            'portfolio': 'https://camillelaurent.dev',
            'bio': 'Étudiante passionnée par le développement d\'applications web et les outils collaboratifs. Recherche des projets axés sur la transition écologique et l\'intelligence artificielle.',
            'avatar': 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=200&auto=format&fit=crop&q=80',
            'team_name': 'EcoTrack',
            'team_role': 'Team Leader & Fullstack Dev',
            'skills': ['Python', 'Django', 'React', 'TypeScript', 'Tailwind', 'PostgreSQL', 'Docker'],
            'badges': [
                {'name': 'Hackathon Vétéran', 'icon': 'bi-award-fill', 'color': 'warning'},
                {'name': 'Code Ninja', 'icon': 'bi-terminal-fill', 'color': 'primary'},
                {'name': 'Team Leader', 'icon': 'bi-star-fill', 'color': 'success'},
                {'name': 'Profil Vérifié', 'icon': 'bi-patch-check-fill', 'color': 'info'},
            ]
        }
    }
    return render(request, 'accounts/profile.html', context)
