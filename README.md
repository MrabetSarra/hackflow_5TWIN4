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

## Organisation du dépôt

```text
accounts/          Comptes, rôles et profils
core/              Page publique
student/           Espace étudiant
mentor/            Espace mentor
dashboard_admin/   Espace organisateur
workshops/         Ateliers, réservations, certificats et badges
templates/         Pages et layouts
static/             Styles, scripts et identité visuelle
```

## Module Ateliers & Formations (`workshops`)

Module autonome de formation, utilisable en **présentiel**, en **ligne (live)** ou en **replay vidéo**. Il s'appuie sur six modèles : `Workshop`, `Booking`, `Certificate`, `Badge`, `BadgeAward` et `WorkshopActivity`.

- **Catalogue et réservation** : filtres (mode, niveau, places), liste d'attente automatique, détection de conflit d'horaire, promotion du premier inscrit en attente après une annulation.
- **États temporels** : comparaison des dates/heures côté serveur ; le bouton « Réserver » est désactivé avec la raison exacte (atelier terminé, commencé, inscriptions fermées, replay expiré) et un compte à rebours en direct (jours/heures/minutes/secondes) s'affiche avant le début.
- **Certificats vérifiables** : PDF généré avec `fpdf2`, QR code de vérification, code unique consultable publiquement sur `/workshops/verify/<code>/`.
- **Badges** : cinq badges (premier atelier, assiduité, explorateur de modes, etc.) attribués automatiquement après un certificat.
- **Trois briques d'IA, 100 % hors ligne** :
  - recommandation d'ateliers par similarité TF-IDF (scikit-learn) entre le profil de l'étudiant et les ateliers ;
  - optimisation du planning (algorithme glouton avec pénalité de chevauchement) ;
  - prévision du remplissage et du taux d'absence (régression Ridge, repli sur une heuristique si l'historique est insuffisant).

### Démonstration

```bash
python manage.py seed_workshops
```

La commande est idempotente : elle crée les badges, cinq ateliers passés (historique d'entraînement de l'IA), cinq ateliers à venir couvrant les trois modes, ainsi que des réservations, présences, certificats et notes. Comptes créés si absents : `orga.hackflow` et `demo.workshop1..4` (mot de passe `HackFlow2026!`).

### Tests

```bash
python manage.py test workshops
```

21 tests couvrent le CRUD, les permissions, les réservations, la liste d'attente, les conflits d'horaire, les états temporels (terminé / commencé / à venir), le check-in QR, les certificats, les badges et les recommandations.

## Pistes d’évolution

- Remplacer les données d’exemple par des modèles métier persistants.
- Connecter les actions de gestion des équipes, tâches et demandes.
- Ajouter des tests couvrant les parcours de compte et les permissions par rôle.

---

**HackFlow — Build · Collaborate · Create**
