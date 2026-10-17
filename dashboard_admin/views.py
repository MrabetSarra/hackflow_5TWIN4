from django.shortcuts import render
<<<<<<< HEAD

=======
from accounts.decorators import role_required

@role_required('admin')
>>>>>>> gestion_evenements
def dashboard(request):
    """
    Cockpit principal pour les organisateurs du hackathon.
    """
    context = {
        'kpis': [
            {'label': 'Participants Inscrits', 'value': '520', 'icon': 'bi-people-fill', 'color': 'primary', 'sub': '+45 depuis hier'},
            {'label': 'Équipes Actives', 'value': '92', 'icon': 'bi-diagram-3-fill', 'color': 'success', 'sub': '84 complètes à 100%'},
            {'label': 'Participants Placés', 'value': '94%', 'icon': 'bi-pie-chart-fill', 'color': 'accent', 'sub': '31 sans équipe'},
            {'label': 'Interventions Mentors', 'value': '34', 'icon': 'bi-headset', 'color': 'warning', 'sub': 'Temps moyen : 14 min'},
        ],
        'challenges_stats': [
            {'name': 'Climat & Transition Écologique', 'count': 28, 'percent': 30},
            {'name': 'IA & Productivité Étudiante', 'count': 26, 'percent': 28},
            {'name': 'Santé & Bien-être', 'count': 20, 'percent': 22},
            {'name': 'FinTech & Inclusion', 'count': 18, 'percent': 20},
        ],
        'live_activity': [
            {'event': 'Nouvelle équipe formée : "CodeCraft"', 'time': 'Il y a 3 min', 'icon': 'bi-people-fill', 'color': 'success'},
            {'event': 'Ticket mentor #T-108 ouvert par "FinEd"', 'time': 'Il y a 8 min', 'icon': 'bi-bell-fill', 'color': 'warning'},
            {'event': 'Livrable intermédiaire déposé par "EcoTrack"', 'time': 'Il y a 14 min', 'icon': 'bi-cloud-check-fill', 'color': 'primary'},
            {'event': 'Nouveau participant inscrit : Sarah K. (Polytech)', 'time': 'Il y a 22 min', 'icon': 'bi-person-plus-fill', 'color': 'info'},
        ],
        'pending_alerts': [
            {'msg': '31 étudiants sont encore orphelins d\'équipe.', 'action': 'Lancer le matching auto', 'urgent': True},
            {'msg': 'Table 14 : Signalement de problème de connexion WiFi.', 'action': 'Notifier support réseau', 'urgent': False},
        ]
    }
    return render(request, 'dashboard_admin/dashboard.html', context)


<<<<<<< HEAD
=======
@role_required('admin')
>>>>>>> gestion_evenements
def participants(request):
    """
    Gestion des participants et filtrage.
    """
    context = {
        'participants_list': [
            {
                'name': 'Camille Laurent',
                'email': 'camille.laurent@etu.univ.fr',
                'school': 'Université Polytechnique',
                'role': 'Étudiant',
                'team': 'EcoTrack',
                'skills': ['Python', 'Django', 'React'],
                'status': 'En équipe',
                'status_color': 'success',
            },
            {
                'name': 'Antoine Mercier',
                'email': 'antoine.m@etu.univ.fr',
                'school': 'Faculté des Sciences',
                'role': 'Étudiant',
                'team': 'Aucune',
                'skills': ['Data Science', 'PyTorch'],
                'status': 'Sans équipe',
                'status_color': 'danger',
            },
            {
                'name': 'Inès Haddad',
                'email': 'ines.haddad@design-ecole.fr',
                'school': 'École Nationale de Design',
                'role': 'Étudiant',
                'team': 'Aucune',
                'skills': ['Figma', 'UI/UX'],
                'status': 'Sans équipe',
                'status_color': 'danger',
            },
            {
                'name': 'Dr. Marc Dubois',
                'email': 'marc.dubois@mentor.hackflow.fr',
                'school': 'Scaleway / Telecom Paris',
                'role': 'Mentor',
                'team': 'Référent (4 équipes)',
                'skills': ['DevOps', 'Cloud', 'Kubernetes'],
                'status': 'Actif',
                'status_color': 'primary',
            },
            {
                'name': 'Youssef El Mansouri',
                'email': 'youssef.m@etu.univ.fr',
                'school': 'Université Polytechnique',
                'role': 'Étudiant',
                'team': 'EcoTrack',
                'skills': ['React Native', 'Tailwind'],
                'status': 'En équipe',
                'status_color': 'success',
            },
            {
                'name': 'Sarah Benali',
                'email': 'sarah.benali@inria.fr',
                'school': 'Inria Sophia',
                'role': 'Mentor',
                'team': 'Référente (3 équipes)',
                'skills': ['IA', 'NLP', 'PyTorch'],
                'status': 'Actif',
                'status_color': 'primary',
            },
        ]
    }
    return render(request, 'dashboard_admin/participants.html', context)


<<<<<<< HEAD
=======
@role_required('admin')
>>>>>>> gestion_evenements
def teams(request):
    """
    Gestion des équipes du hackathon.
    """
    context = {
        'teams_list': [
            {
                'name': 'EcoTrack',
                'challenge': 'Climat & Énergie',
                'leader': 'Camille Laurent',
                'members_count': 4,
                'table': 'Table 14',
                'mentor': 'Dr. Marc Dubois',
                'submission_status': 'Brouillon prêt',
                'submission_color': 'warning',
                'progress': 68,
            },
            {
                'name': 'MediConnect',
                'challenge': 'Santé & Bien-être',
                'leader': 'Karim Bensaid',
                'members_count': 3,
                'table': 'Table 08',
                'mentor': 'Dr. Marc Dubois',
                'submission_status': 'Non soumis',
                'submission_color': 'danger',
                'progress': 45,
            },
            {
                'name': 'StudyBuddy AI',
                'challenge': 'Éducation & IA',
                'leader': 'Claire Fontaine',
                'members_count': 5,
                'table': 'Table 19',
                'mentor': 'Thomas Vasseur',
                'submission_status': 'Validé & Rendu',
                'submission_color': 'success',
                'progress': 88,
            },
            {
                'name': 'FinEd',
                'challenge': 'FinTech Éducative',
                'leader': 'Julien Fabre',
                'members_count': 4,
                'table': 'Table 21',
                'mentor': 'Sarah Benali',
                'submission_status': 'En cours',
                'submission_color': 'secondary',
                'progress': 55,
            },
        ]
    }
    return render(request, 'dashboard_admin/teams.html', context)


<<<<<<< HEAD
=======
@role_required('admin')
>>>>>>> gestion_evenements
def announcements(request):
    """
    Gestion et diffusion des annonces organisateur.
    """
    context = {
        'past_announcements': [
            {
                'id': '#ANN-04',
                'title': 'Le buffet de pizzas est ouvert au bâtiment B !',
                'audience': 'Tous les participants',
                'category': 'Logistique',
                'date': 'Aujourd\'hui 12h30',
                'author': 'Alexandre Moreau',
                'badge': 'Envoyé',
            },
            {
                'id': '#ANN-03',
                'title': 'Rappel Jalon 1 : Dépôt architecture obligatoire avant 18h00',
                'audience': 'Étudiants',
                'category': 'Jalon Hackathon',
                'date': 'Aujourd\'hui 10h00',
                'author': 'Alexandre Moreau',
                'badge': 'Envoyé',
            },
            {
                'id': '#ANN-02',
                'title': 'Briefing des mentors dans le salon visio #staff',
                'audience': 'Mentors uniquement',
                'category': 'Organisation',
                'date': 'Hier 17h00',
                'author': 'Équipe HackFlow',
                'badge': 'Envoyé',
            },
        ]
    }
    return render(request, 'dashboard_admin/announcements.html', context)


<<<<<<< HEAD
=======
@role_required('admin')
>>>>>>> gestion_evenements
def judging(request):
    """
    Grille de notation du jury et classement final.
    """
    context = {
        'podium': [
            {
                'rank': 1,
                'team': 'StudyBuddy AI',
                'score': 18.75,
                'category': 'Éducation & IA',
                'award': '1er Prix (5 000 €)',
                'badge_color': 'warning',
            },
            {
                'rank': 2,
                'team': 'EcoTrack',
                'score': 18.20,
                'category': 'Climat & Énergie',
                'award': '2e Prix (3 000 €)',
                'badge_color': 'secondary',
            },
            {
                'rank': 3,
                'team': 'MediConnect',
                'score': 17.40,
                'category': 'Santé & Bien-être',
                'award': '3e Prix (2 000 €)',
                'badge_color': 'info',
            },
        ],
        'teams_ranking': [
            {
                'rank': 1,
                'team': 'StudyBuddy AI',
                'innovation': 4.8,
                'tech': 4.9,
                'design': 4.5,
                'pitch': 4.55,
                'total': 18.75,
            },
            {
                'rank': 2,
                'team': 'EcoTrack',
                'innovation': 4.7,
                'tech': 4.6,
                'design': 4.9,
                'pitch': 4.0,
                'total': 18.20,
            },
            {
                'rank': 3,
                'team': 'MediConnect',
                'innovation': 4.5,
                'tech': 4.3,
                'design': 4.4,
                'pitch': 4.2,
                'total': 17.40,
            },
            {
                'rank': 4,
                'team': 'FinEd',
                'innovation': 4.2,
                'tech': 4.1,
                'design': 4.3,
                'pitch': 4.4,
                'total': 17.00,
            },
            {
                'rank': 5,
                'team': 'SafeCity',
                'innovation': 4.0,
                'tech': 3.9,
                'design': 4.1,
                'pitch': 4.2,
                'total': 16.20,
            },
        ]
    }
    return render(request, 'dashboard_admin/judging.html', context)
