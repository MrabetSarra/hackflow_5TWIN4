# ⚡ HackFlow - Plateforme de Gestion de Hackathon Étudiant

> Conçu pour une équipe de 5 développeurs. Couche Front-End & Templates sous **Django 5** et **Bootstrap 5.3**.

---

## 🎯 Présentation du Projet

HackFlow simplifie et centralise l'organisation d'un hackathon étudiant, de la formation des équipes jusqu'au pitch final devant le jury :
- **Matching des compétences** : algorithme et bourse aux talents pour équilibrer les équipes.
- **Gestion de sprint agile** : tableau Kanban pour répartir les tâches et anticiper les blocages.
- **Mentorat en continu** : file d'attente d'assistance et accompagnement direct en visio.
- **Cockpit organisateur** : suivi des 500 participants, KPIs en temps réel et notation officielle du jury.

---

## 🛠️ Stack Technique

- **Backend** : Django 5.2 (Python 3.11+)
- **Templates** : Django Template Language (DTL)
- **Front-End & UI/UX** : Bootstrap 5.3 (CDN), Bootstrap Icons 1.11, Google Fonts (*Plus Jakarta Sans* & *JetBrains Mono*), CSS personnalisé (`static/css/custom.css`)
- **Base de données** : SQLite 3 (`db.sqlite3`)
- **Stockage des médias** : `/media/uploads/`
- **Langue & Région** : Français (`fr-fr`), Fuseau horaire Paris (`Europe/Paris`)

---

## 🚀 Démarrage Rapide

### 1. Cloner le projet et créer un environnement virtuel
```powershell
git clone https://github.com/MrabetSarra/hackflow_5TWIN4.git
cd hackflow_5TWIN4
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Appliquer les migrations
```powershell
python manage.py migrate
```

### 3. Lancer le serveur de développement
```powershell
python manage.py runserver
```
L'application est disponible sur : **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

La clé Django de développement peut être remplacée en définissant la variable
d'environnement `DJANGO_SECRET_KEY`. Configurez impérativement une clé secrète
privée avant tout déploiement.

---

## 🧭 Les 4 Espaces Utilisateurs & 19 Routes Démo

Une **barre flottante de bascule (Demo Switcher)** en bas à droite de l'écran permet de naviguer en un clic entre les espaces sans se déconnecter.

### 1. Espace Visiteur (Public)
| Route | Nom de l'URL | Description |
|---|---|---|
| `/` | `core:landing` | Landing page complète avec compte à rebours, étapes, chiffres clés, mentors et FAQ |
| `/accounts/login/` | `accounts:login` | Page de connexion avec raccourcis de démo rapide (Étudiant, Mentor, Admin) |
| `/accounts/register/` | `accounts:register` | Inscription avec choix de rôle et tags de compétences pour le matching |
| `/accounts/profile/` | `accounts:profile` | Consultation et édition du profil utilisateur avec badges de succès |

### 2. Espace Étudiant (Participant)
| Route | Nom de l'URL | Description |
|---|---|---|
| `/student/` | `student:dashboard` | Tableau de bord avec jalons, deadlines urgentes et KPIs du sprint |
| `/student/team/` | `student:team_detail` | Fiche d'équipe (*EcoTrack*), membres, liens (GitHub, Figma) et invitation |
| `/student/matching/` | `student:skills_matching` | Bourse aux compétences (participants sans équipe & équipes qui recrutent) |
| `/student/tasks/` | `student:tasks_kanban` | Tableau Kanban interactif (À faire, En cours, Revue, Terminé) |
| `/student/mentor-request/` | `student:mentor_request` | Demande d'assistance mentor en direct et historique des tickets |
| `/student/submission/` | `student:project_submission` | Formulaire de rendu final du projet (liens, vidéo, slides PDF) |

### 3. Espace Mentor (Accompagnement)
| Route | Nom de l'URL | Description |
|---|---|---|
| `/mentor/` | `mentor:dashboard` | Cockpit mentor (*Dr. Marc Dubois*), tickets urgents et planning de sessions |
| `/mentor/teams/` | `mentor:teams_list` | Répertoire des équipes avec barre de progression et recherche par défi |
| `/mentor/requests/` | `mentor:help_requests` | File d'attente complète des tickets d'aide avec niveau de criticité |
| `/mentor/evaluations/` | `mentor:evaluations` | Fiches de retours et feedbacks constructifs post-session |

### 4. Espace Admin (Organisateur)
| Route | Nom de l'URL | Description |
|---|---|---|
| `/cockpit/` | `dashboard_admin:dashboard` | Cockpit global de supervision, KPIs, répartition par défi et fil d'activité live |
| `/cockpit/participants/` | `dashboard_admin:participants` | Table des 500 participants avec recherche et filtres par statut |
| `/cockpit/teams/` | `dashboard_admin:teams` | Gestion des 92 équipes, mentors assignés et état des livrables |
| `/cockpit/announcements/` | `dashboard_admin:announcements` | Outil de diffusion d'annonces push en direct |
| `/cockpit/judging/` | `dashboard_admin:judging` | Grille de notation officielle du jury et podium final en direct |

---

## 🏗️ Architecture du Code

```text
hackflow/
├── hackflow/                  # Configuration principale (settings, urls, wsgi)
├── core/                      # Application publique (Landing)
├── accounts/                  # Authentification & Profils
├── student/                   # Espace étudiant participant
├── mentor/                    # Espace accompagnateur mentor
├── dashboard_admin/           # Espace organisateur admin
├── static/
│   ├── css/custom.css         # Design system & styles HackFlow
│   └── js/main.js             # Interactions, toasts démo, timer & toggle
├── templates/
│   ├── base.html              # Template racine
│   ├── components/            # Composants réutilisables (demo_switcher.html)
│   ├── layouts/               # Layouts parents par espace
│   │   ├── base_public.html
│   │   ├── base_student.html
│   │   ├── base_mentor.html
│   │   └── base_admin.html
│   ├── core/
│   ├── accounts/
│   ├── student/
│   ├── mentor/
│   └── dashboard_admin/
└── media/uploads/             # Dossier de téléversement des fichiers
```

---

## 🔌 Préparé pour la suite (Modèles ORM)

Les contextes de données factices dans chaque `views.py` sont modélisés comme de futurs objets Django (`dict` facilement remplaçables par `Model.objects.all()` ou `filter()`). Les formulaires sont prêts à être convertis en `ModelForm` ou `Form` Django lors de l'étape suivante.
