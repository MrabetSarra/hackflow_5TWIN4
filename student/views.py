from django.shortcuts import render

def dashboard(request):
    """
    Tableau de bord de l'espace étudiant participant.
    """
    context = {
        'team': {
            'name': 'EcoTrack',
            'project_title': 'Calculateur d\'empreinte carbone campus & défis étudiants',
            'category': 'Impact Écologique & Smart Campus',
            'member_count': 4,
            'max_members': 5,
            'progress': 68,
        },
        'timeline': [
            {'title': 'Kick-off & Idéation', 'time': 'Vendredi 18h00', 'status': 'done', 'icon': 'bi-check-circle-fill'},
            {'title': 'Validation du concept par un mentor', 'time': 'Samedi 10h00', 'status': 'done', 'icon': 'bi-check-circle-fill'},
            {'title': 'Jalon 1 : Dépôt Architecture & Wireframes', 'time': 'Samedi 18h00', 'status': 'active', 'icon': 'bi-play-circle-fill'},
            {'title': 'Jalon 2 : Dépôt du MVP fonctionnel', 'time': 'Dimanche 10h00', 'status': 'pending', 'icon': 'bi-clock-fill'},
            {'title': 'Pitch Final devant le Jury', 'time': 'Dimanche 14h00', 'status': 'pending', 'icon': 'bi-trophy-fill'},
        ],
        'upcoming_deadlines': [
            {'label': 'Dépôt du Jalon 1 (Architecture)', 'deadline': 'Dans 4h 15m', 'badge': 'Aujourd\'hui 18h00', 'urgent': True},
            {'label': 'Rendez-vous de suivi avec Dr. Marc Dubois', 'deadline': 'À 16h30', 'badge': 'Google Meet', 'urgent': False},
            {'label': 'Arrêt des dépôts de code (Code Freeze)', 'deadline': 'Dimanche 11h30', 'badge': 'Demain', 'urgent': False},
        ],
        'recent_announcements': [
            {
                'title': 'Le buffet de pizzas est ouvert au bâtiment B !',
                'author': 'Alexandre (Organisateur)',
                'time': 'Il y a 25 min',
                'badge': 'Logistique'
            },
            {
                'title': 'Rappel : Les mentors Cloud sont disponibles sur le Discord salon #devops',
                'author': 'Staff HackFlow',
                'time': 'Il y a 1h',
                'badge': 'Mentorat'
            },
        ],
        'stats': [
            {'label': 'Tâches terminées', 'value': '12/18', 'icon': 'bi-check2-square', 'color': 'success'},
            {'label': 'Demandes mentor résolues', 'value': '3', 'icon': 'bi-headset', 'color': 'primary'},
            {'label': 'Place restante dans l\'équipe', 'value': '1 profil', 'icon': 'bi-person-plus', 'color': 'warning'},
        ]
    }
    return render(request, 'student/dashboard.html', context)


def team_detail(request):
    """
    Fiche de l'équipe étudiante et gestion des membres.
    """
    context = {
        'team': {
            'name': 'EcoTrack',
            'tagline': 'Rendre la transition écologique accessible et ludique sur les campus universitaires grâce à l\'IA.',
            'category': 'Climat & Énergie',
            'table_number': 'Table 14 - Halle Informatique',
            'created_at': 'Il y a 20 heures',
            'repo_url': 'https://github.com/hackflow-teams/ecotrack-app',
            'figma_url': 'https://figma.com/file/ecotrack-wireframes',
            'demo_url': 'https://ecotrack.demo.hackflow.fr',
            'members': [
                {
                    'name': 'Camille Laurent',
                    'role': 'Capitaine & Lead Dev Fullstack',
                    'email': 'camille.laurent@etu.univ.fr',
                    'avatar': 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100&auto=format&fit=crop&q=80',
                    'skills': ['Django', 'React', 'Docker'],
                    'is_leader': True,
                },
                {
                    'name': 'Youssef El Mansouri',
                    'role': 'Développeur Front-End & Mobile',
                    'email': 'youssef.m@etu.univ.fr',
                    'avatar': 'https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=100&auto=format&fit=crop&q=80',
                    'skills': ['React Native', 'Tailwind', 'TypeScript'],
                    'is_leader': False,
                },
                {
                    'name': 'Éléonore Morin',
                    'role': 'Product Designer UI/UX',
                    'email': 'eleonore.m@etu.univ.fr',
                    'avatar': 'https://images.unsplash.com/photo-1517841905240-472988babdf9?w=100&auto=format&fit=crop&q=80',
                    'skills': ['Figma', 'User Research', 'Design System'],
                    'is_leader': False,
                },
                {
                    'name': 'Lucas Bernard',
                    'role': 'Développeur Back-End & API',
                    'email': 'lucas.b@etu.univ.fr',
                    'avatar': 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=100&auto=format&fit=crop&q=80',
                    'skills': ['Python', 'PostgreSQL', 'FastAPI'],
                    'is_leader': False,
                },
            ],
            'seeking_skill': 'Data Scientist / Ingénieur IA (Prompt Engineering & Modèles Climat)',
        }
    }
    return render(request, 'student/team_detail.html', context)


def skills_matching(request):
    """
    Bourse aux compétences : étudiants cherchant équipe & équipes recrutant.
    """
    context = {
        'students_looking': [
            {
                'name': 'Antoine Mercier',
                'school': 'Master 1 Data Science',
                'avatar': 'https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=100&auto=format&fit=crop&q=80',
                'skills': ['Python', 'PyTorch', 'Pandas', 'Scikit-Learn'],
                'bio': 'Recherche une équipe dynamique avec un projet orienté IA ou data viz. Très à l\'aise sur les scripts ML.',
                'preferred_role': 'Data Scientist',
            },
            {
                'name': 'Inès Haddad',
                'school': 'L3 Design Numérique',
                'avatar': 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=100&auto=format&fit=crop&q=80',
                'skills': ['Figma', 'UI Design', 'Pitch Deck', 'After Effects'],
                'bio': 'Spécialiste de l\'identité visuelle et des présentations percutantes. Je rends vos prototypes séduisants.',
                'preferred_role': 'Product Designer',
            },
            {
                'name': 'Théo Garnier',
                'school': 'Cycle Ingénieur DevOps',
                'avatar': 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=100&auto=format&fit=crop&q=80',
                'skills': ['Docker', 'AWS', 'Terraform', 'CI/CD'],
                'bio': 'Prêt à monter vos pipelines de déploiement et héberger vos MVP en 2 temps 3 mouvements.',
                'preferred_role': 'DevOps / SysAdmin',
            },
            {
                'name': 'Sofia Belkacem',
                'school': 'Master 2 Sécurité & Systèmes',
                'avatar': 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=100&auto=format&fit=crop&q=80',
                'skills': ['Go', 'Rust', 'OAuth2', 'Web Security'],
                'bio': 'Développeuse backend pointue, aime les architectures robustes et sécurisées.',
                'preferred_role': 'Back-End Developer',
            },
        ],
        'teams_looking': [
            {
                'name': 'MediConnect',
                'pitch': 'Plateforme d\'orientation des urgences hospitalières basée sur le triage intelligent.',
                'category': 'Santé & Bien-être',
                'cover_img': 'https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=500&auto=format&fit=crop&q=80',
                'current_members': 3,
                'target_members': 5,
                'missing_skills': ['UI/UX Designer', 'Développeur Flutter'],
            },
            {
                'name': 'FinEd',
                'pitch': 'Micro-épargne ludique pour les étudiants avec simulation d\'investissement éthique.',
                'category': 'FinTech Éducative',
                'cover_img': 'https://images.unsplash.com/photo-1559526324-4b87b5e36e44?w=500&auto=format&fit=crop&q=80',
                'current_members': 4,
                'target_members': 5,
                'missing_skills': ['Data Analyst / Python'],
            },
            {
                'name': 'SafeCity',
                'pitch': 'Application citoyenne de signalement d\'incivilités et entraide de quartier.',
                'category': 'Smart City & Sécurité',
                'cover_img': 'https://images.unsplash.com/photo-1477959858617-67f30bc75b82?w=500&auto=format&fit=crop&q=80',
                'current_members': 3,
                'target_members': 4,
                'missing_skills': ['Front-End React'],
            },
        ]
    }
    return render(request, 'student/skills_matching.html', context)


def tasks_kanban(request):
    """
    Tableau Kanban de suivi des tâches de l'équipe.
    """
    context = {
        'todo_tasks': [
            {'id': 1, 'title': 'Rédiger le script du pitch vidéo 3 min', 'tag': 'Pitch', 'tag_color': 'warning', 'assignee': 'Éléonore', 'urgent': True},
            {'id': 2, 'title': 'Générer les certificats SSL sur le serveur de staging', 'tag': 'DevOps', 'tag_color': 'secondary', 'assignee': 'Camille', 'urgent': False},
            {'id': 3, 'title': 'Tester les contrastes d\'accessibilité WCAG', 'tag': 'Design', 'tag_color': 'info', 'assignee': 'Éléonore', 'urgent': False},
        ],
        'in_progress_tasks': [
            {'id': 4, 'title': 'Intégration de l\'API d\'estimation carbone', 'tag': 'Backend', 'tag_color': 'primary', 'assignee': 'Lucas', 'urgent': True},
            {'id': 5, 'title': 'Finaliser les composants du Dashboard utilisateur', 'tag': 'Frontend', 'tag_color': 'success', 'assignee': 'Youssef', 'urgent': False},
        ],
        'review_tasks': [
            {'id': 6, 'title': 'Revue de code de la route d\'authentification OAuth', 'tag': 'Backend', 'tag_color': 'primary', 'assignee': 'Camille', 'urgent': False},
        ],
        'done_tasks': [
            {'id': 7, 'title': 'Maquettage Figma des 5 écrans clés', 'tag': 'Design', 'tag_color': 'info', 'assignee': 'Éléonore', 'urgent': False},
            {'id': 8, 'title': 'Initialisation du dépôt GitHub et README', 'tag': 'DevOps', 'tag_color': 'secondary', 'assignee': 'Camille', 'urgent': False},
            {'id': 9, 'title': 'Schéma de base de données relationnelle SQLite', 'tag': 'Backend', 'tag_color': 'primary', 'assignee': 'Lucas', 'urgent': False},
        ]
    }
    return render(request, 'student/tasks_kanban.html', context)


def mentor_request(request):
    """
    Demande d'accompagnement mentor et suivi des tickets de l'équipe.
    """
    context = {
        'active_requests': [
            {
                'id': '#T-104',
                'subject': 'Problème de CORS et cookies SameSite sur l\'API Django',
                'category': 'Technique / Back-end',
                'urgency': 'Bloquant (Sprint arrêté)',
                'urgency_color': 'danger',
                'status': 'En cours avec un mentor',
                'mentor_name': 'Dr. Marc Dubois',
                'mentor_avatar': 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=100&auto=format&fit=crop&q=80',
                'meeting_url': 'https://meet.google.com/abc-hackflow-demo',
                'created_at': 'Il y a 12 min',
            },
        ],
        'past_requests': [
            {
                'id': '#T-082',
                'subject': 'Validation de la charte graphique et du flux d\'onboarding',
                'category': 'Design & UX',
                'urgency': 'Normal',
                'urgency_color': 'secondary',
                'status': 'Résolu',
                'mentor_name': 'Léa Rousseau',
                'mentor_avatar': 'https://images.unsplash.com/photo-1580489944761-15a19d654956?w=100&auto=format&fit=crop&q=80',
                'resolution_note': 'Très bonne ergonomie générale. Ajout de 2 micro-interactions conseillé pour le pitch.',
                'created_at': 'Il y a 3 heures',
            },
            {
                'id': '#T-041',
                'subject': 'Orientation sur le choix du modèle NLP open-source',
                'category': 'IA & Data',
                'urgency': 'Normal',
                'urgency_color': 'secondary',
                'status': 'Résolu',
                'mentor_name': 'Sarah Benali',
                'mentor_avatar': 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=100&auto=format&fit=crop&q=80',
                'resolution_note': 'Orientation vers Mistral 7B via API plutôt qu\'un modèle lourd en local.',
                'created_at': 'Hier à 22h00',
            },
        ]
    }
    return render(request, 'student/mentor_request.html', context)


def project_submission(request):
    """
    Rendu final du projet de hackathon pour le jury.
    """
    context = {
        'submission': {
            'status': 'Brouillon en cours d\'enregistrement',
            'deadline': 'Dimanche 11h30 (Code Freeze)',
            'time_left': 'Dans 21 heures et 40 minutes',
            'project_name': 'EcoTrack - Smart Green Campus',
            'short_pitch': 'Application web et mobile qui quantifie les économies d\'énergie et de carbone des initiatives étudiantes.',
            'category': 'Défi 1 : Transition Écologique & Climat',
            'github_url': 'https://github.com/hackflow-teams/ecotrack-app',
            'demo_url': 'https://ecotrack.demo.hackflow.fr',
            'video_url': 'https://loom.com/share/ecotrack-pitch-demo-2026',
            'slide_file': 'EcoTrack_Pitch_Deck_HackFlow_Final.pdf',
        }
    }
    return render(request, 'student/project_submission.html', context)
