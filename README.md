<p align="center">
  <img src="static/images/hackflow-logo.png" alt="HackFlow" width="340">
</p>

<h1 align="center">HackFlow</h1>

<p align="center"><strong>Build Â· Collaborate Â· Create</strong></p>

<p align="center">
  La plateforme qui aide les Ã©quipes Ã©tudiantes Ã  transformer une idÃ©e en projet de hackathon.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white">
  <img alt="Django" src="https://img.shields.io/badge/Django-5.2-092E20?logo=django&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white">
</p>

## Ã€ propos

HackFlow rassemble dans un mÃªme espace les outils utiles pendant un hackathon Ã©tudiant : trouver des coÃ©quipiers, partager ses compÃ©tences, demander conseil Ã  un mentor et suivre lâ€™avancement dâ€™un projet.

Lâ€™expÃ©rience sâ€™articule autour de trois espaces â€” **Ã©tudiant**, **mentor** et **organisateur** â€” afin que chacun retrouve les informations et les actions adaptÃ©es Ã  son rÃ´le.

## Ce que propose HackFlow

- **Trouver son Ã©quipe** : dÃ©couvrir des profils complÃ©mentaires et mettre en valeur ses compÃ©tences.
- **Avancer ensemble** : visualiser les tÃ¢ches, les jalons et le rendu du projet.
- **ÃŠtre accompagnÃ©** : solliciter un mentor et consulter les demandes dâ€™aide.
- **Organiser lâ€™Ã©vÃ©nement** : suivre les participants, les Ã©quipes, les annonces et les Ã©valuations depuis un cockpit dÃ©diÃ©.
- **PrÃ©senter son profil** : gÃ©rer ses informations, sa photo et son CV.
- **OpportunitÃ©s carriÃ¨re** : consulter des offres modÃ©rÃ©es, comprendre le score de correspondance et suivre ses candidatures.

## Trois espaces, un objectif commun

| Ã‰tudiants | Mentors | Organisateurs |
|---|---|---|
| Profil et compÃ©tences | Suivi des Ã©quipes | Vue dâ€™ensemble du hackathon |
| Ã‰quipes et matching | Demandes dâ€™accompagnement | Participants et Ã©quipes |
| TÃ¢ches et rendu du projet | Ã‰valuations et retours | Annonces et notation |

## Ã‰tat du projet

HackFlow est un **prototype web en cours de dÃ©veloppement**. La crÃ©ation de compte Ã©tudiant ou mentor, la connexion, les rÃ´les, la gestion du profil et les fichiers associÃ©s sont reliÃ©s Ã  la base de donnÃ©es. Les espaces mÃ©tier prÃ©sentent le parcours et lâ€™interface cible ; plusieurs listes reposent encore sur des donnÃ©es dâ€™exemple, et certaines actions affichent une confirmation de dÃ©monstration sans enregistrer de donnÃ©es.

Cette version permet de dÃ©couvrir lâ€™expÃ©rience envisagÃ©e et constitue une base pour connecter progressivement les Ã©quipes, tÃ¢ches, demandes et Ã©valuations Ã  des donnÃ©es persistantes.

## AperÃ§u

Lâ€™application comprend une page dâ€™accueil publique et des tableaux de bord distincts pour chaque rÃ´le. Pour explorer lâ€™interface localement, consultez le dÃ©marrage rapide ci-dessous.

## DÃ©marrage rapide

PrÃ©requis : Python 3.10 ou plus rÃ©cent.

```bash
git clone https://github.com/MrabetSarra/hackflow_5TWIN4.git
cd hackflow_5TWIN4
python -m venv .venv
```

Activez lâ€™environnement virtuel, puis installez et lancez le projet :

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Ouvrez [http://127.0.0.1:8000/](http://127.0.0.1:8000/). La base SQLite locale est crÃ©Ã©e lors de lâ€™application des migrations. Lâ€™envoi des codes de rÃ©initialisation du mot de passe nÃ©cessite une configuration SMTP Gmail.

### Configuration du copilote IA local

Le copilote admin utilise Ollama en local. Installez Ollama, tÃ©lÃ©chargez le modÃ¨le par dÃ©faut, puis dÃ©marrez le serveur Ollama :

```powershell
ollama pull qwen2.5:7b
ollama serve
```

Le serveur Django se connecte par dÃ©faut Ã  `http://127.0.0.1:11434`. `OLLAMA_BASE_URL` et `OLLAMA_COPILOT_MODEL` permettent de modifier l'adresse et le modÃ¨le du copilote. Le matching des Ã©quipes utilise un score pondÃ©rÃ© calculÃ© par Django ; ses propositions restent en attente de validation par l'organisateur.

### AI Team Formation

Les organisateurs lancent une proposition depuis la page Participants. Le score pondéré compare les compétences demandées et complémentaires, les rôles, les thèmes préférés, les disponibilités déclarées et la capacité des équipes. Les étudiants peuvent renseigner leurs rôles, thèmes et disponibilités dans leur profil (`/accounts/profile/?edit=1`). Les propositions expliquent les apports de chaque membre et les rôles ou compétences encore absents ; aucune affectation n'est enregistrée avant validation par l'organisateur. Les préférences et disponibilités sont facultatives et un champ vide reste neutre.

### AI Hackathon Copilot

Le copilote est intégré au cockpit organisateur (`/cockpit/`). Ses compteurs, risques d'échéance et listes de projets sont calculés par Django depuis la base ; Ollama génère uniquement l'explication et les recommandations. Les annonces générées peuvent être modifiées puis enregistrées comme brouillons ; elles ne sont jamais publiées automatiquement. Le modèle peut être réglé séparément via `OLLAMA_COPILOT_MODEL`.

### AI Project Evaluation Assistant

La page Jury (`/cockpit/judging/`) permet à l'organisateur de demander une analyse Ollama des soumissions réelles. L'assistant résume le projet, relève objectifs, technologies et cas d'usage, confronte les éléments visibles à la grille et propose des questions. Pour un ZIP, seuls les petits fichiers texte de présentation et manifestes connus sont lus localement, sans extraction. L'assistant n'attribue aucune note et ne classe ni ne désigne de gagnant ; la décision appartient au jury.

## Technologies

- **Backend :** Python et Django
- **DonnÃ©es locales :** SQLite
- **Interface :** Django Templates, Bootstrap, CSS et JavaScript
- **MÃ©dias :** Pillow pour la photo de profil ; CV conservÃ©s dans un stockage privÃ© local

## Career opportunities

Students browse opportunities at `/careers/`. Organizers publish and manage offers at `/cockpit/careers/`; offers are entered directly by organizers, and external applications link to the employer.

### Organizer-published offers and CV matching

Organizers create offers at `/cockpit/careers/new/`. New manual offers start as drafts; the status control supports publishing and archiving. The editor provides a live preview, explicit required/preferred skills, education, experience, languages, location/work-arrangement requirements, and project/other eligibility criteria. Skill weights use `Skill=weight` entries (for example `Python=25, SQL=15`). All positive weights are validated from 0 to 100 and normalized to exactly 100 when saved.

Student matching uses the existing private profile PDF and existing profile fields. `pdfminer.six` extracts selectable text locally, limited to 10 MB and 20 pages. CV analysis runs locally; no CV text is sent to an external service, and raw extracted text is not stored. Structured evidence snippets and their timestamp are cached by the CV's SHA-256 digest. Scanned image-only PDFs are not OCR processed; unreadable or missing CVs show no compatibility percentage.

Each explicit requirement receives an evidence-based match percentage or an unknown state. The overall score is `sum(match_pct Ã— weight) / sum(weights for requirements with reliable evidence)`. Profile coverage is evaluated requirement weight divided by all positive requirement weight. Scores are hidden below 30% coverage to avoid false precision. Explicit mandatory contradictions are shown separately; missing CV evidence remains unverified rather than being treated as proof that a student lacks a skill. Per-student/per-offer result caches are invalidated by CV, profile or offer changes. Students see only published offers whose publication date has arrived and whose deadline has not passed.

Apply the additive schema changes with `python manage.py migrate`. Run `python manage.py check` and `python manage.py test career_opportunities` to verify the career module.

```text
accounts/          Comptes, rÃ´les et profils
core/              Page publique
student/           Espace Ã©tudiant
mentor/            Espace mentor
dashboard_admin/   Espace organisateur
templates/         Pages et layouts
static/             Styles, scripts et identitÃ© visuelle
```

## Pistes dâ€™Ã©volution

- Remplacer les donnÃ©es dâ€™exemple par des modÃ¨les mÃ©tier persistants.
- Connecter les actions de gestion des Ã©quipes, tÃ¢ches et demandes.
- Ajouter des tests couvrant les parcours de compte et les permissions par rÃ´le.

---

**HackFlow â€” Build Â· Collaborate Â· Create**


