<p align="center">
  <img src="static/images/hackflow-logo.png" alt="HackFlow" width="340">
</p>

<h1 align="center">HackFlow</h1>

<p align="center"><strong>Build · Collaborate · Create</strong></p>

<p align="center">
  La plateforme qui aide les équipes étudiantes à transformer une idée en projet de hackathon.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white">
  <img alt="Django" src="https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white">
</p>

## À propos

HackFlow rassemble dans un même espace les outils utiles pendant un hackathon étudiant : trouver des coéquipiers, partager ses compétences, demander conseil à un mentor et suivre l’avancement d’un projet.

L’expérience s’articule autour de trois espaces — **étudiant**, **mentor** et **organisateur** — afin que chacun retrouve les informations et les actions adaptées à son rôle.

## Ce que propose HackFlow

- **Trouver son équipe** : découvrir des profils complémentaires et mettre en valeur ses compétences.
- **Avancer ensemble** : visualiser les tâches, les jalons et le rendu du projet.
- **Être accompagné** : solliciter un mentor et consulter les demandes d’aide.
- **Organiser l’événement** : suivre les participants, les équipes, les annonces et les évaluations depuis un cockpit dédié.
- **Présenter son profil** : gérer ses informations, sa photo et son CV.

## Trois espaces, un objectif commun

| Étudiants | Mentors | Organisateurs |
|---|---|---|
| Profil et compétences | Suivi des équipes | Vue d’ensemble du hackathon |
| Équipes et matching | Demandes d’accompagnement | Participants et équipes |
| Tâches et rendu du projet | Évaluations et retours | Annonces et notation |

## État du projet

HackFlow est un **prototype web en cours de développement**. La création de compte étudiant ou mentor, la connexion, les rôles, la gestion du profil et les fichiers associés sont reliés à la base de données. Les espaces métier présentent le parcours et l’interface cible ; plusieurs listes reposent encore sur des données d’exemple, et certaines actions affichent une confirmation de démonstration sans enregistrer de données.

Cette version permet de découvrir l’expérience envisagée et constitue une base pour connecter progressivement les équipes, tâches, demandes et évaluations à des données persistantes.

## Aperçu

L’application comprend une page d’accueil publique et des tableaux de bord distincts pour chaque rôle. Pour explorer l’interface localement, consultez le démarrage rapide ci-dessous.

## Démarrage rapide

Prérequis : Python 3.10 ou plus récent.

```bash
git clone https://github.com/MrabetSarra/hackflow_5TWIN4.git
cd hackflow_5TWIN4
python -m venv .venv
```

Activez l’environnement virtuel, puis installez et lancez le projet :

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Ouvrez [http://127.0.0.1:8000/](http://127.0.0.1:8000/). La base SQLite locale est créée lors de l’application des migrations. L’envoi des codes de réinitialisation du mot de passe nécessite une configuration SMTP Gmail.

## Technologies

- **Backend :** Python et Django
- **Données locales :** SQLite
- **Interface :** Django Templates, Bootstrap, CSS et JavaScript
- **Médias :** Pillow pour la photo de profil ; CV conservés dans un stockage privé local

## AI task generation

AI task suggestions reuse the repository AI provider configuration. Set `REPOSITORY_AI_PROVIDER` to `ollama`, `openai`, or `anthropic`; configure `OLLAMA_BASE_URL` and `OLLAMA_MODEL` for Ollama, `OPENAI_API_KEY` and `OPENAI_MODEL` for OpenAI, or `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` for Anthropic. `REPOSITORY_AI_TIMEOUT` controls provider timeouts.

For background processing, set `CELERY_BROKER_URL` (default: `redis://localhost:6379/0`) and `CELERY_TASK_ALWAYS_EAGER` (`true` runs jobs synchronously; it defaults to the Django `DEBUG` value). Set `CELERY_TASK_ALWAYS_EAGER=false` when using a worker. Start it with:

```bash
celery -A hackflow worker -l info
```

Run `python manage.py evaluate_ai` for reproducible mocked metrics, or add `--live` to call the configured AI provider. The report is written to `reports/ai_metrics.md`.

## Organisation du dépôt

```text
accounts/          Comptes, rôles et profils
core/              Page publique
student/           Espace étudiant
mentor/            Espace mentor
dashboard_admin/   Espace organisateur
templates/         Pages et layouts
static/             Styles, scripts et identité visuelle
```

## Pistes d’évolution

- Remplacer les données d’exemple par des modèles métier persistants.
- Connecter les actions de gestion des équipes, tâches et demandes.
- Ajouter des tests couvrant les parcours de compte et les permissions par rôle.

---

**HackFlow — Build · Collaborate · Create**

## Testing and coverage

Install the development dependencies and run the full Django suite:

```bash
python -m pip install -r requirements-dev.txt
python manage.py test
```

For local Windows PowerShell, set a development key before running Django commands if your `.env` has `DJANGO_DEBUG=false`:

```powershell
$env:DJANGO_DEBUG = 'true'
$env:DJANGO_SECRET_KEY = 'local-test-key-change-me'
python manage.py test
```

Generate coverage reports with:

```bash
coverage run manage.py test
coverage report --fail-under=70
coverage html
```

The HTML report is written to `htmlcov/`. CI enforces 70% coverage and uploads that report as an artifact.

## Environment variables

Copy `.env.example` to `.env` and set the values for your environment:

- Django: `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`.
- Production security: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS`, `SECURE_PROXY_SSL_HEADER`, and `CSRF_TRUSTED_ORIGINS`.
- Email: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`. The console backend is used unless both SMTP credentials are set.
- Private repository storage: `HACKFLOW_REPOS_ROOT`.
- AI providers: `REPOSITORY_AI_PROVIDER`, `REPOSITORY_AI_TIMEOUT`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`.
- Background jobs: `CELERY_BROKER_URL`, `CELERY_TASK_ALWAYS_EAGER`.

When `DJANGO_DEBUG=false`, Django refuses to start without `DJANGO_SECRET_KEY`. Never use `*` for allowed hosts. HTTPS and proxy values must match the hosting provider's configuration.

## Security checklist

- Keep `.env`, the local SQLite database, logs, and `.repository-data/` out of Git.
- Use a long, unique production secret key and keep debug mode disabled.
- Set exact allowed hosts and CSRF trusted origins for the deployed domain.
- Enable HTTPS cookie protection and redirects when TLS is terminated by the application; configure the trusted proxy header only when the host guarantees it.
- Configure SMTP credentials through environment variables; use a restricted mail account.
- Review `python manage.py check --deploy` before deployment. HSTS preload is opt-in and should only be enabled when the domain is ready for permanent browser preload behavior.
