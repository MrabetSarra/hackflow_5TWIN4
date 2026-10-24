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

Ouvrez [http://127.0.0.1:8000/](http://127.0.0.1:8000/). La base SQLite locale est créée lors de l’application des migrations. Sans identifiants SMTP configurés, les courriels de réinitialisation s’affichent dans la console Django.

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

## Deployment

### Architecture

Render runs one native Python web service from the `main` branch. The Blueprint pins Python 3.12.11, collects static files, starts Django with Gunicorn through `scripts/start.sh`, and uses `/healthz/` for its health check. WhiteNoise serves static files. GitHub Actions is the deployment controller: a successful CI run on `main` triggers the Render Deploy Hook, waits for health, and runs the smoke checks. The app logs to stdout.

The service uses SQLite and the free Render filesystem. `DATABASE_PATH`, uploads, private files, and Git repositories are stored under `/tmp`; they are ephemeral. **The free Render instance resets its data on restart and re-seeds the demo data at startup** (`SEED_DEMO=1`). Real user data will not survive a restart on this plan. Celery runs eagerly in the web process because this deployment has no background worker.

### Environment variables

The complete example is in `.env.production.example`. Configure the following values in Render; values marked **secret** must be stored in Render’s environment settings and must never be committed.

| Variable | Render value or source | Purpose |
| --- | --- | --- |
| `PYTHON_VERSION` | `3.12.11` | Native runtime version. |
| `DJANGO_DEBUG` | `false` | Production mode. |
| `DJANGO_SECRET_KEY` | **Secret** | Required Django signing key. |
| `DJANGO_ALLOWED_HOSTS` | `esprit-5twin4-Hackflow.onrender.com` | Hostnames accepted by Django. |
| `CSRF_TRUSTED_ORIGINS` | `https://esprit-5twin4-HackFlow.onrender.com` | Trusted browser origin. |
| `SECURE_SSL_REDIRECT` | `true` | Redirect HTTP to HTTPS. |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | `true` | Send cookies only over HTTPS. |
| `SECURE_HSTS_SECONDS` | `31536000` | HSTS duration in seconds. |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `true` | Apply HSTS to subdomains. |
| `SECURE_HSTS_PRELOAD` | `false` | Keep preload opt-in until explicitly reviewed. |
| `SECURE_CONTENT_TYPE_NOSNIFF` | `true` | Add the nosniff response header. |
| `X_FRAME_OPTIONS` | `DENY` | Prevent framing by other sites. |
| `SECURE_PROXY_SSL_HEADER` | `HTTP_X_FORWARDED_PROTO,https` | Trust Render’s HTTPS proxy header. |
| `DATABASE_PATH` | `/tmp/hackflow.sqlite3` | Ephemeral SQLite database file. |
| `MEDIA_ROOT` | `/tmp/media/uploads` | Upload storage. |
| `PRIVATE_MEDIA_ROOT` | `/tmp/private_media` | Private student files. |
| `HACKFLOW_REPOS_ROOT` | `/tmp/.repository-data` | Private Git repository storage. |
| `STATIC_ROOT` | `/opt/render/project/src/staticfiles` | `collectstatic` output served by WhiteNoise. |
| `SEED_DEMO` | `1` | Re-create demo data at startup. |
| `CELERY_TASK_ALWAYS_EAGER` | `true` | Run jobs inline; no worker is deployed. |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Unused while eager execution is enabled. |
| `DJANGO_SUPERUSER_USERNAME` | **Secret/configuration** | Optional admin bootstrap username. |
| `DJANGO_SUPERUSER_EMAIL` | **Secret/configuration** | Optional admin bootstrap email. |
| `DJANGO_SUPERUSER_PASSWORD` | **Secret** | Optional admin bootstrap password. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS` | `localhost`, `587`, `true` | SMTP connection settings. |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | **Secret** | Optional SMTP credentials; without both, Django uses its console backend. |
| `DEFAULT_FROM_EMAIL` | `webmaster@localhost` | Sender address when SMTP is configured. |
| `REPOSITORY_AI_PROVIDER` | `openai` | Selected optional AI provider. |
| `REPOSITORY_AI_TIMEOUT` | `30` | Provider request timeout in seconds. |
| `OPENAI_API_KEY` | **Secret** | Optional OpenAI credential. |
| `OPENAI_MODEL` | `gpt-5-mini` | OpenAI model name. |
| `ANTHROPIC_API_KEY` | **Secret** | Optional Anthropic credential. |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Anthropic model name. |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Local defaults in the example | Optional local Ollama configuration. |
| `PORT` | Set by Render | Port bound by the startup script. |
| `RENDER_DEPLOY_HOOK_URL` | **GitHub `production` environment secret** | Starts the Render deploy after CI passes. |
| `SITE_URL` | **GitHub `production` environment secret** | Public base URL used for health and smoke checks. |

Render values declared with `sync: false` in `render.yaml` are intentionally entered in Render’s dashboard rather than stored in the repository. The admin command skips creation when any `DJANGO_SUPERUSER_*` value is missing; it never prints the password.

### First deploy

1. Connect the GitHub repository to Render and apply `render.yaml` to the intended web service. Confirm the service name and public hostname match the existing `esprit-5twin4-HackFlow` deployment before applying a Blueprint to an existing service.
2. In Render, set `DJANGO_SECRET_KEY`. Set all three `DJANGO_SUPERUSER_*` values if the deployment needs the configured admin account. Add AI and SMTP credentials only when those integrations are used.
3. In GitHub, create the `production` environment and add `RENDER_DEPLOY_HOOK_URL` and `SITE_URL` as environment secrets. Set `SITE_URL` to the HTTPS public URL, with no required trailing slash.
4. Ensure the `main` branch requires the CI status check. Merge a pull request into `main`; the workflow runs checks and tests before calling the deploy hook, waiting for `/healthz/`, and running `scripts/smoke_test.sh`.

The Blueprint sets Render `autoDeployTrigger: off` to avoid a second, duplicate deploy. As an alternative, use Render’s **After CI Checks Pass** auto-deploy setting and disable the GitHub Actions deploy-hook job. Do not enable both deployment paths at once.

### Update and rollback

Normal update flow: create a feature branch, open a pull request, wait for CI and review, then merge to `main`. The `main` push runs the test job and deploys only after it succeeds. The workflow polls the service for up to five minutes, then runs the curl smoke checks. The CI workflow also uploads an HTML coverage report artifact.

Run the same HTTP smoke checks manually with `sh scripts/smoke_test.sh https://esprit-5twin4-Hackflow.onrender.com` (requires `curl`).

To roll back, open the Render service’s deploy history and redeploy a previously successful commit. A rollback restores code, not ephemeral SQLite or uploaded data; the free instance may re-seed demo records on its next restart.

### Troubleshooting

- **Cold start:** Free services sleep while idle. The first request may take a minute; the deploy job allows five minutes for `/healthz/` to return HTTP 200.
- **Data reset after restart:** This is expected on the free filesystem. Demo rows are re-seeded when `SEED_DEMO=1`; uploads and user-created records are not durable.
- **Git is unavailable:** Check startup warnings. The app remains available, but repository operations and the optional repository demo seed need the Git executable in the runtime. The demo seed is skipped with a warning if Git is absent.
- **CSRF 403 behind the proxy:** Check that `CSRF_TRUSTED_ORIGINS` contains the exact HTTPS origin and that `SECURE_PROXY_SSL_HEADER` matches Render’s forwarded protocol header.
- **SQLite locked:** The app uses a 20-second SQLite timeout and WAL mode, but a single ephemeral SQLite file is not intended for sustained concurrent writes. Keep background jobs eager and avoid adding a second writer process on this plan.
- **AI unavailable:** AI is optional. Check the selected `REPOSITORY_AI_PROVIDER`, its credential, and startup warnings. Missing credentials or an unreachable provider should not prevent the web service from starting.
- **CI coverage or deployment fails:** Inspect the workflow summary, uploaded `hackflow-coverage-html` artifact, the failing job logs, and Render’s deploy logs. Verify both GitHub `production` secrets are present without printing their values.

### Grading evidence

| Requirement | Evidence |
| --- | --- |
| `DEBUG=False` and production configuration | Render environment plus `render.yaml`; `python manage.py check --deploy` in the CI log. |
| Secrets outside source control | `sync: false` entries in `render.yaml`, GitHub `production` secrets, and `.gitignore` entries for `.env` and the database. |
| CSRF protection | Production security settings and the smoke test’s POST-without-token check. |
| Role access | `tests/test_access_matrix.py` and its CI test result. |
| Custom error pages | `templates/404.html`, `templates/403.html`, `templates/500.html`, and `core/tests.py`. |
| Tests and coverage | CI test count/coverage summary and the uploaded HTML coverage artifact. |
| CI-gated deployment | GitHub Actions `test` then `deploy` jobs and the Render deploy history. |
| Public service health | `https://esprit-5twin4-HackFlow.onrender.com/healthz/` and the post-deploy smoke-test output. |
