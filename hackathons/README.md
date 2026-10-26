# Intelligence artificielle du module Hackathons

Ce document décrit uniquement les fonctionnalités IA du module Django `hackathons` : génération de contenu et de bannières pour les organisateurs, accompagnement et recommandations pour les étudiants, et explications pour les mentors.

## 1. Fonctionnalités disponibles

| Fonction | Utilisateur | Ce que fait l’IA | Fournisseur |
|---|---|---|---|
| Brouillon de hackathon | Organisateur (`admin` ou `organization`) | Propose des titres, une description courte et complète, des règles et des idées de challenges à partir du titre et de consignes | Gemini |
| Brouillon de challenge | Organisateur (`admin` ou `organization`) | Propose les descriptions, objectifs, problématique, contraintes, livrables, consignes, technologies, difficulté et idées de récompense | Gemini |
| Bannière | Organisateur (`admin` ou `organization`) | Génère une image à partir du titre, du track, de la description courte et d’indications de style | Hugging Face Inference, puis Pollinations en secours si activé |
| Coach d’un challenge | Étudiant | Explique un challenge publié, suggère des premières étapes, des conseils, les pièges à éviter et les compétences à apprendre | Gemini |
| Recommandations | Étudiant | Classe les challenges publiés par compatibilité locale, puis demande à Gemini d’expliquer les meilleures recommandations | Classement Django local + Gemini |
| Explication d’un hackathon ou challenge | Mentor | Produit un résumé, les points clés, les difficultés probables, des questions et des conseils de mentorat | Gemini |

Les résultats générés sont des propositions. Les organisateurs gardent la main sur la rédaction et la publication. Le classement étudiant est calculé dans Django ; Gemini ajoute des explications et des conseils, il ne décide pas de l’inscription.

## 2. Architecture générale

### Assistant texte Gemini

1. L’interface envoie une requête `POST` au serveur Django avec le nom de la fonctionnalité et les champs nécessaires.
2. `ai_views.py` vérifie la session, le rôle, les champs et l’accès aux objets publiés. Le serveur construit une charge utile limitée et ne prend pas directement un prompt libre du navigateur.
3. `ai_services.py` choisit le prompt, applique le quota utilisateur et cherche une réponse réussie en cache.
4. Une entrée `AIJob` est enregistrée en base. Son statut progresse de `pending` à `running`, puis à `done` ou `failed`.
5. La tâche Celery appelle le client `gemini.py`. Celui-ci envoie le prompt au modèle principal, valide la sortie, puis essaie le modèle de secours si l’appel ou le format de réponse échoue.
6. `ai_prompts.py` impose un format JSON et valide/limite les champs retournés avant qu’ils soient transmis à l’interface.
7. Le navigateur affiche le résultat et, lorsque c’est pertinent, permet à l’utilisateur de donner un avis positif ou négatif.

Dans la configuration actuelle de Render, `CELERY_TASK_ALWAYS_EAGER=true` exécute la tâche dans le processus web, sans broker ni worker séparé. Si cette option est désactivée, un broker Celery joignable et un worker doivent être déployés ; sinon la demande échoue à la mise en file.

### Génération d’image

1. Le navigateur envoie le titre du hackathon, son track, sa description courte et les instructions de style à `banner_generate`.
2. Le serveur vérifie le rôle organisateur et le titre, construit le prompt et limite le nombre de demandes.
3. `images.py` appelle le modèle Hugging Face configuré avec le jeton serveur.
4. Si Hugging Face échoue et que le secours est activé, le serveur essaie Pollinations.
5. Le résultat est vérifié comme image, converti en JPEG, recadré en `1280 × 720`, enregistré dans le stockage média et renvoyé au navigateur pour aperçu.
6. Le formulaire conserve le chemin généré ; l’image n’est associée au hackathon que lorsque le formulaire est ensuite enregistré. Si l’organisateur téléverse une image, son téléversement est prioritaire.

## 3. Fichiers concernés

| Fichier | Rôle dans l’IA Hackathons |
|---|---|
| `hackathons/ai_views.py` | Contrôle des routes, des rôles, des charges utiles, démarrage et suivi des tâches, retours, recommandations, page mentor et route de bannière |
| `hackathons/ai_services.py` | Registre des fonctionnalités et rôles, classement local, construction du contexte, cache des réponses, quota texte et exécution des jobs |
| `hackathons/ai_prompts.py` | Instructions envoyées à Gemini, structure JSON attendue, nettoyage et validation de la réponse |
| `hackathons/gemini.py` | Appels HTTP Gemini, choix du modèle principal/de secours, gestion des erreurs, parsing JSON et mesures d’appel |
| `hackathons/images.py` | Prompt d’image, appel Hugging Face, secours Pollinations, contrôle et conversion de l’image |
| `hackathons/tasks.py` | Tâche Celery `hackathons.run_ai_job` qui délègue l’exécution au service IA |
| `hackathons/models.py` (`AIJob`) | Persistance des demandes, résultats, erreurs, modèles utilisés, latences, cache et retours utilisateurs |
| `hackathons/migrations/0011_ai_jobs.py` | Création de la table `AIJob` |
| `hackathons/urls.py` | Déclaration des URL de démarrage, statut, feedback, recommandations, mentor et bannières |
| `templates/hackathons/_ai_client.html` | Client JavaScript partagé : POST avec CSRF, attente du résultat, messages d’erreur, affichage et feedback |
| `templates/hackathons/_ai_assistant.html` | Fenêtre d’assistance réutilisée dans les formulaires organisateur |
| `templates/hackathons/_banner_ai.html` | Bouton de génération, envoi des champs, état de chargement et aperçu de la bannière |
| `templates/hackathons/public/ai_recommendations.html` | Page de recommandations et interface du coach étudiant |
| `templates/hackathons/public/ai_mentor.html` | Interface mentor pour demander des explications sur les éléments publiés |
| `hackathons/tests_ai.py` | Tests des clients, prompts via validateurs, rôles, jobs, cache, recommandations, mentor, images et erreurs |
| `hackathons/tests_security.py` | Tests de sécurité du module, dont CSRF et contrôle d’accès |

`static/js/main.js` ne réalise pas les appels aux fournisseurs IA ; le client propre à ces interactions est dans les templates ci-dessus.

## 4. Routes du module

Les routes sont déclarées avec le namespace `hackathons` dans `hackathons/urls.py`.

| Nom Django | Route | Méthode | Rôle / usage |
|---|---|---|---|
| `hackathons:ai_start` | `/hackathons/ia/<feature>/start/` | POST | Démarrer une fonctionnalité texte ; connexion requise et rôle vérifié selon la fonctionnalité |
| `hackathons:ai_status` | `/hackathons/ia/jobs/<job_id>/` | GET | Consulter le statut/résultat du job ; seule la personne propriétaire du job peut le consulter |
| `hackathons:ai_feedback` | `/hackathons/ia/jobs/<job_id>/feedback/` | POST | Enregistrer `1` (utile) ou `-1` (pas utile), uniquement par le propriétaire |
| `hackathons:ai_recommendations` | `/hackathons/ia/recommandations/` | GET | Page étudiant des recommandations, réservée aux étudiants |
| `hackathons:ai_mentor` | `/hackathons/ia/mentor/` | GET | Page mentor, réservée aux mentors |
| `hackathons:banner_generate` | `/hackathons/ia/banniere/` | POST | Générer une bannière, réservé aux organisateurs |

Les requêtes POST utilisent la protection CSRF de Django. L’endpoint de statut filtre également le job par utilisateur pour éviter l’accès aux résultats d’un autre compte.

## 5. Configuration des fournisseurs

### Gemini : assistant texte

Variables lues par `hackathons/gemini.py` :

| Variable | Usage | Défaut |
|---|---|---|
| `GEMINI_API_KEY` | Clé secrète Google AI Studio ; nécessaire pour toutes les fonctionnalités Gemini | Aucune |
| `GEMINI_MODEL` | Modèle principal | `gemini-3.5-flash` |
| `GEMINI_FALLBACK_MODEL` | Modèle utilisé si l’appel principal ou sa réponse échoue | `gemini-3.5-flash-lite` |
| `GEMINI_TIMEOUT` | Délai maximal d’appel en secondes | `40` |
| `HACKATHONS_AI_REQUESTS_PER_HOUR` | Nombre maximal de jobs non servis depuis le cache par utilisateur et par heure | `30` |

En local, ces variables peuvent être définies dans le `.env` ignoré par Git. En production, configurez-les dans **Render → service → Environment**. N’ajoutez jamais de clé réelle dans un commit ou dans ce README.

### Hugging Face : génération de bannières

Variables lues par `hackathons/images.py` :

| Variable | Usage | Défaut |
|---|---|---|
| `HF_API_TOKEN` | Jeton Hugging Face autorisé à utiliser Inference Providers | Aucune |
| `HF_IMAGE_MODEL` | Modèle d’image | `stabilityai/stable-diffusion-3-medium-diffusers` |
| `HF_IMAGE_FALLBACK` | Active le secours Pollinations si la valeur est `pollinations` | `pollinations` |
| `HF_IMAGE_TIMEOUT` | Délai maximal par requête d’image, en secondes | `90` |

Render doit pouvoir joindre les services externes en HTTPS. Hugging Face peut refuser une demande si le crédit est épuisé (HTTP 402), si le jeton n’a pas la permission requise, si le modèle n’est pas disponible ou si le quota est atteint. Le secours Pollinations est un service externe indépendant : il peut lui aussi être indisponible ou inaccessible depuis Render. Dans ce cas, le téléversement manuel reste disponible.

La route limite la génération à 10 demandes par heure et par utilisateur via le cache Django. Pour un comportement fiable avec plusieurs processus/instances, le backend de cache de production doit être partagé et persistant ; le cache local en mémoire n’est pas partagé entre processus.

## 6. Comment sont calculées les recommandations

Le score de compatibilité n’est pas généré par Gemini. Dans `ai_services.py`, le module :

1. Récupère les compétences et spécialités de l’étudiant.
2. Ne prend que les challenges et hackathons publiés.
3. Compare les compétences à la technologie, au titre et au texte du challenge et du hackathon, avec des poids plus forts pour les correspondances dans les technologies.
4. Trie les challenges et hackathons selon ce score local.
5. Envoie à Gemini le profil nécessaire et une sélection limitée des résultats, avec les scores existants, pour rédiger une justification et des conseils.
6. Vérifie que les identifiants de challenges et hackathons retournés par Gemini font partie des identifiants autorisés.

Il faut donc renseigner des compétences dans le profil étudiant et disposer d’au moins un challenge publié pour obtenir des recommandations personnalisées.

## 7. Cache, quotas et mesures

- Les résultats texte terminés sont réutilisés pendant 24 heures pour une même fonctionnalité et une même charge utile. Le hash est calculé à partir du nom de la fonctionnalité et du contenu JSON normalisé.
- Une réponse en cache crée un nouvel `AIJob` pour l’utilisateur courant, mais ne rappelle pas Gemini.
- Le quota texte compte les jobs non servis depuis le cache de l’utilisateur sur la dernière heure ; valeur par défaut : 30.
- La génération d’images a une limite distincte : 10 par heure et par utilisateur.
- `AIJob` conserve le statut, le résultat, l’erreur, le modèle, l’utilisation du fallback, le temps d’attente et la latence, les tailles de prompt/réponse, les dates et le feedback.
- Les secrets ne sont pas retournés dans les réponses d’erreur prévues pour l’utilisateur. Les logs applicatifs ne doivent pas inclure les clés API.

## 8. Installation et test local

Depuis la racine du dépôt, activez l’environnement Python, installez les dépendances puis configurez au moins `GEMINI_API_KEY` et, pour tester les images, `HF_API_TOKEN` dans votre `.env` local.

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Les appels texte nécessitent une connexion Internet et une clé Gemini valide. Les tests unitaires simulent les réponses des fournisseurs ; ils ne consomment pas de crédit API lorsqu’ils sont exécutés normalement.

```powershell
python manage.py test hackathons.tests_ai hackathons.tests_security
```

Pour le contrôle Django et les migrations :

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
```

## 9. Mise en production et vérification sur Render

1. Dans **Render → Environment**, ajoutez `GEMINI_API_KEY` pour le texte et `HF_API_TOKEN` pour les images. Ajoutez les modèles et timeouts seulement si vous souhaitez remplacer les valeurs par défaut.
2. Configurez les valeurs de production sur Render ; ne copiez pas le fichier `.env` local dans Git.
3. Vérifiez que le dernier workflow GitHub Actions réussit. La CI exécute les contrôles Django et les tests, puis le job de déploiement Render.
4. Vérifiez que le service Render est `Live` et inspectez les logs de démarrage. `scripts/start.sh` applique les migrations avant de lancer l’application ; la migration `0011_ai_jobs` est nécessaire au suivi des appels texte.
5. Connectez-vous avec un organisateur et testez un brouillon, puis la génération de bannière ; faites aussi un test avec un étudiant et un mentor pour vérifier leurs accès.
6. En cas d’échec, comparez le message affiché aux logs Render et vérifiez la variable, les permissions/quota du fournisseur, l’accessibilité réseau et le backend de cache. Ne publiez jamais les secrets dans un ticket ou une capture.

Sur le service Render configuré en stockage temporaire, les fichiers médias écrits dans `/tmp` ne sont pas une conservation permanente. Les bannières générées peuvent disparaître lors d’un redémarrage ou redéploiement ; prévoyez un stockage média persistant si elles doivent être conservées.

## 10. Limites à connaître

- Le modèle peut produire du texte incorrect ou incomplet. Les sorties sont validées structurellement, mais leur contenu doit être relu avant publication.
- Le fallback Gemini ne corrige que l’échec du modèle principal. Il ne remplace pas l’absence de `GEMINI_API_KEY` et peut échouer également si son quota est épuisé.
- Le fallback Pollinations ne garantit pas la disponibilité de la génération d’image ; un HTTP 402 Hugging Face signifie que le crédit d’inférence du compte est épuisé.
- Les données nécessaires à la requête sont envoyées au fournisseur externe choisi. N’envoyez pas de données personnelles qui ne sont pas nécessaires à la fonctionnalité.
- Si `CELERY_TASK_ALWAYS_EAGER` est mis à `false`, il faut déployer et surveiller un broker et un worker Celery compatibles avec la configuration du projet.
