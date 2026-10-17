from django.shortcuts import render
<<<<<<< HEAD

=======
from accounts.decorators import role_required

@role_required('mentor')
>>>>>>> gestion_evenements
def dashboard(request):
    """
    Tableau de bord de l'espace Mentor.
    """
    context = {
        'mentor_name': 'Dr. Marc Dubois',
        'specialty': 'Cloud Architecture & DevOps Lead',
        'stats': [
            {'label': 'Équipes assignées', 'value': '4', 'icon': 'bi-people-fill', 'color': 'primary'},
            {'label': 'Demandes d\'aide en attente', 'value': '3', 'icon': 'bi-bell-fill', 'color': 'warning'},
            {'label': 'Sessions réalisées', 'value': '8', 'icon': 'bi-headset', 'color': 'success'},
            {'label': 'Feedbacks envoyés', 'value': '6', 'icon': 'bi-pencil-square', 'color': 'accent'},
        ],
        'urgent_requests': [
            {
                'id': '#T-105',
                'team': 'MediConnect',
                'category': 'Infra & Déploiement',
                'urgency': 'Bloquant',
                'subject': 'Problème de configuration des variables d\'environnement sur AWS ECS',
                'time_waiting': 'Il y a 8 min',
                'table': 'Table 08',
            },
            {
                'id': '#T-106',
                'team': 'FinEd',
                'category': 'Architecture Base de Données',
                'urgency': 'Important',
                'subject': 'Optimisation des index PostgreSQL pour le calcul de simulation',
                'time_waiting': 'Il y a 15 min',
                'table': 'Table 21',
            },
        ],
        'today_sessions': [
            {
                'time': '16h30 - 17h00',
                'team': 'EcoTrack',
                'topic': 'Point d\'étape sur l\'architecture API et le modèle d\'impact',
                'status': 'Confirmé',
                'meeting_url': 'https://meet.google.com/ecotrack-hackflow-room',
            },
            {
                'time': '17h30 - 18h00',
                'team': 'SafeCity',
                'topic': 'Revue de la sécurité des webhooks de notification citoyenne',
                'status': 'En attente',
                'meeting_url': 'https://meet.google.com/safecity-room',
            },
        ]
    }
    return render(request, 'mentor/dashboard.html', context)


<<<<<<< HEAD
=======
@role_required('mentor')
>>>>>>> gestion_evenements
def teams_list(request):
    """
    Répertoire des équipes du hackathon consultables par le mentor.
    """
    context = {
        'teams': [
            {
                'name': 'EcoTrack',
                'category': 'Climat & Énergie',
                'pitch': 'Calculateur d\'empreinte carbone campus & défis étudiants.',
                'cover_img': 'https://images.unsplash.com/photo-1497435334941-8c899ee9e8e9?w=500&auto=format&fit=crop&q=80',
                'members_count': 4,
                'progress': 68,
                'status': 'Sprint actif',
                'table': 'Table 14',
                'mentor_assigned': 'Dr. Marc Dubois',
            },
            {
                'name': 'MediConnect',
                'category': 'Santé & Bien-être',
                'pitch': 'Plateforme d\'orientation des urgences basée sur le triage intelligent.',
                'cover_img': 'https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=500&auto=format&fit=crop&q=80',
                'members_count': 3,
                'progress': 45,
                'status': 'Besoin d\'aide',
                'table': 'Table 08',
                'mentor_assigned': 'Dr. Marc Dubois',
            },
            {
                'name': 'FinEd',
                'category': 'FinTech Éducative',
                'pitch': 'Micro-épargne ludique pour les étudiants avec simulation d\'investissement éthique.',
                'cover_img': 'https://images.unsplash.com/photo-1559526324-4b87b5e36e44?w=500&auto=format&fit=crop&q=80',
                'members_count': 4,
                'progress': 55,
                'status': 'Sprint actif',
                'table': 'Table 21',
                'mentor_assigned': 'Sarah Benali',
            },
            {
                'name': 'SafeCity',
                'category': 'Smart City & Sécurité',
                'pitch': 'Application citoyenne de signalement d\'incivilités et entraide locale.',
                'cover_img': 'https://images.unsplash.com/photo-1477959858617-67f30bc75b82?w=500&auto=format&fit=crop&q=80',
                'members_count': 3,
                'progress': 40,
                'status': 'Besoin d\'aide',
                'table': 'Table 05',
                'mentor_assigned': 'Dr. Marc Dubois',
            },
            {
                'name': 'StudyBuddy AI',
                'category': 'Éducation & IA',
                'pitch': 'Assistant d\'apprentissage adaptatif pour synthétiser les cours magistraux.',
                'cover_img': 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=500&auto=format&fit=crop&q=80',
                'members_count': 5,
                'progress': 80,
                'status': 'Avancé',
                'table': 'Table 19',
                'mentor_assigned': 'Thomas Vasseur',
            },
            {
                'name': 'GreenDelivery',
                'category': 'Logistique Durable',
                'pitch': 'Mutualisation des livraisons de repas étudiants à vélo.',
                'cover_img': 'https://images.unsplash.com/photo-1526367790999-0150786686a2?w=500&auto=format&fit=crop&q=80',
                'members_count': 4,
                'progress': 60,
                'status': 'Sprint actif',
                'table': 'Table 11',
                'mentor_assigned': 'Léa Rousseau',
            },
        ]
    }
    return render(request, 'mentor/teams_list.html', context)


<<<<<<< HEAD
=======
@role_required('mentor')
>>>>>>> gestion_evenements
def help_requests(request):
    """
    File d'attente complète des tickets de mentorat.
    """
    context = {
        'requests': [
            {
                'id': '#T-105',
                'team': 'MediConnect',
                'subject': 'Problème de configuration des variables d\'environnement sur AWS ECS',
                'description': 'Notre conteneur Docker crash au lancement car les secrets AWS ne sont pas injectés correctement dans l\'image Django.',
                'category': 'DevOps & Cloud',
                'urgency': 'Bloquant',
                'urgency_color': 'danger',
                'time_waiting': 'Il y a 8 min',
                'table': 'Table 08 (Bâtiment B)',
                'meet_url': 'https://meet.google.com/mediconnect-room',
            },
            {
                'id': '#T-106',
                'team': 'FinEd',
                'subject': 'Optimisation des index PostgreSQL pour le calcul de simulation financière',
                'description': 'La requête de projection à 5 ans prend plus de 4 secondes à s\'exécuter sur 10 000 transactions simulées.',
                'category': 'Bases de Données',
                'urgency': 'Important',
                'urgency_color': 'warning',
                'time_waiting': 'Il y a 15 min',
                'table': 'Table 21 (Halle Centrale)',
                'meet_url': 'https://meet.google.com/fined-room',
            },
            {
                'id': '#T-107',
                'team': 'SafeCity',
                'subject': 'Conseils sur la modération automatisée des signalements photos',
                'description': 'Nous voulons intégrer une API de computer vision pour flouter automatiquement les visages et plaques d\'immatriculation.',
                'category': 'IA & Vision',
                'urgency': 'Conseil',
                'urgency_color': 'secondary',
                'time_waiting': 'Il y a 22 min',
                'table': 'Table 05 (Bâtiment A)',
                'meet_url': 'https://meet.google.com/safecity-room',
            },
        ]
    }
    return render(request, 'mentor/help_requests.html', context)


<<<<<<< HEAD
=======
@role_required('mentor')
>>>>>>> gestion_evenements
def evaluations(request):
    """
    Historique et saisie des retours / feedbacks mentor.
    """
    context = {
        'feedbacks': [
            {
                'team_name': 'EcoTrack',
                'date': 'Aujourd\'hui 11h15',
                'mentor': 'Dr. Marc Dubois',
                'tech_rating': 4,
                'design_rating': 5,
                'pitch_readiness': 'En bonne voie',
                'comment': 'Excellente vision produit. L\'équipe a bien compris les enjeux d\'éco-conception. Attention à ne pas surcharger l\'onboarding pour la démo jury.',
            },
            {
                'team_name': 'StudyBuddy AI',
                'date': 'Hier 21h30',
                'mentor': 'Sarah Benali',
                'tech_rating': 5,
                'design_rating': 4,
                'pitch_readiness': 'Prêt',
                'comment': 'Pipeline RAG très solide et temps de réponse bluffant. Mettez en avant le benchmark comparatif lors de la présentation orale.',
            },
        ]
    }
    return render(request, 'mentor/evaluations.html', context)
