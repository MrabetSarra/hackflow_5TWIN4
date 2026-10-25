# Déploiement des fonctionnalités IA sur Render

Ce guide explique comment faire fonctionner sur le site déployé sur Render les fonctionnalités IA de HackFlow : génération de bannière (Hugging Face), assistant de génération de tâches et d'annonces (Gemini), assistant de jury, copilote organisateur, tri des demandes du mentor et suggestions de tâches des dépôts.

## 1. Fonctionnement du déploiement

- Le workflow GitHub Actions `.github/workflows/django.yml` lance les tests (413 tests, couverture de 81 % d'après le dernier run) puis déclenche le déploiement sur Render.
- Le fichier `render.yaml` définit le service web et ses variables d'environnement. Les variables marquées `sync: false` doivent être renseignées dans le tableau de bord Render. Elles ne doivent jamais être écrites dans le dépôt Git.
- Au démarrage, `scripts/start.sh` applique les migrations (`python manage.py migrate`) puis lance Gunicorn.

## 2. État des fonctionnalités IA sur Render

| Fonctionnalité | Fournisseur | Fonctionne sur Render avec une simple clé ? |
|---|---|---|
| Génération de bannière | Hugging Face (`HF_API_TOKEN`) | Oui, avec le jeton. Sans jeton, le secours Pollinations peut être utilisé si `HF_IMAGE_FALLBACK=pollinations`. |
| Assistant de tâches et d'annonces (hackathons) | Gemini (`GEMINI_API_KEY`) | Oui, avec la clé. |
| Dépôts : suggestions de tâches | `REPOSITORY_AI_PROVIDER` (`openai`, `anthropic` ou `ollama`) | Oui avec `openai` ou `anthropic`. Avec `ollama` (valeur actuelle de `render.yaml`), il faut un serveur Ollama joignable. |
| Copilote organisateur, annonces, assistant de jury | Ollama uniquement | Non, sauf si un serveur Ollama est joignable depuis Render. |
| Tri des demandes du mentor | Ollama (via proxy) | Non, sauf si le proxy Ollama est joignable depuis Render. |

Point important : `127.0.0.1:11434` est la machine Render elle-même. Ollama installé sur votre PC n'y est donc jamais visible. Les fonctionnalités marquées « Ollama uniquement » échoueront sur le site déployé tant qu'aucun serveur Ollama accessible n'est configuré.

## 3. Obtenir les clés

1. **Hugging Face** : créez un jeton sur [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) avec la permission « Inference Providers ». Le jeton commence par `hf_`.
2. **Gemini** : créez une clé sur [Google AI Studio](https://aistudio.google.com/apikey).
3. **OpenAI ou Anthropic** (facultatif, pour les dépôts) : créez une clé sur la plateforme du fournisseur.

## 4. Variables à ajouter dans Render

Dans Render : service `esprit-5twin4-hackflow` → **Environment** → **Add Environment Variable**.

| Variable | Valeur | Obligatoire |
|---|---|---|
| `HF_API_TOKEN` | votre jeton `hf_...` | Oui, pour la bannière |
| `HF_IMAGE_MODEL` | `stabilityai/stable-diffusion-3-medium-diffusers` | Non (valeur par défaut) |
| `HF_IMAGE_FALLBACK` | `pollinations` | Non |
| `HF_IMAGE_TIMEOUT` | `90` | Non |
| `GEMINI_API_KEY` | votre clé Gemini | Oui, pour l'assistant de tâches |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Non (valeur par défaut) |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Non (valeur par défaut) |
| `GEMINI_TIMEOUT` | `40` | Non |
| `HACKATHONS_AI_REQUESTS_PER_HOUR` | `30` | Non |
| `REPOSITORY_AI_PROVIDER` | `openai` ou `anthropic` | Recommandé sur Render, sinon `ollama` |
| `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY` | votre clé | Si le fournisseur choisi l'exige |
| `OLLAMA_BASE_URL` | URL HTTPS d'un serveur Ollama accessible | Seulement pour le copilote, le jury, les annonces et le mentor |
| `OLLAMA_PROXY_TOKEN` | jeton partagé avec le proxy | Seulement si Ollama passe par le proxy |

Après avoir enregistré les variables, Render redéploie automatiquement le service.

## 5. Ajouter les variables au fichier `render.yaml` (facultatif)

Pour que la configuration soit documentée dans le dépôt sans valeurs secrètes, ajoutez ceci dans `envVars` :

```yaml
      - key: GEMINI_API_KEY
        sync: false
      - key: HF_API_TOKEN
        sync: false
      - key: HF_IMAGE_FALLBACK
        value: pollinations
```

Les valeurs secrètes restent dans le tableau de bord Render. Le fichier ne contient que les noms des variables.

## 6. Activer les fonctionnalités Ollama (si nécessaire)

Deux options :

**Option A : garder Ollama.** Il faut un serveur Ollama accessible en HTTPS depuis Render, par exemple une machine ou un VPS sur lequel Ollama tourne avec le modèle installé (`ollama pull qwen2.5:7b`). Sur ce serveur, lancez le proxy protégé par jeton du dépôt :

```bash
export OLLAMA_PROXY_TOKEN="un-long-jeton-aleatoire"
python ollama_proxy.py
```

Le proxy écoute sur le port 8001 et refuse toute requête sans `Authorization: Bearer <jeton>`. Exposez-le en HTTPS (reverse proxy ou tunnel), puis renseignez sur Render :

- `OLLAMA_BASE_URL` = l'URL HTTPS publique du proxy ;
- `OLLAMA_PROXY_TOKEN` = le même jeton ;
- `OLLAMA_COPILOT_MODEL` = le modèle installé, par exemple `qwen2.5:7b` ;
- `OLLAMA_MODEL` = le modèle utilisé pour le mentor et les dépôts.

**Option B : passer ces fonctionnalités sur Gemini.** Le copilote, l'assistant de jury et les annonces n'utilisent aujourd'hui que Ollama. Les faire passer sur Gemini demande une modification du code, car ces modules n'ont pas de secours. Vous pouvez me demander cette modification.

## 7. Vérifier le déploiement

1. Vérifiez que le déploiement est terminé dans Render (statut « Live »).
2. Ouvrez les logs Render en cas d'erreur. Aucune clé n'apparaît dans les messages affichés aux utilisateurs.
3. Testez dans cet ordre :
   - connexion organisateur, puis création d'une bannière de hackathon ;
   - assistant de génération de tâches (Gemini) ;
   - suggestion de tâches dans un dépôt ;
   - copilote, assistant de jury et tri mentor, uniquement si Ollama est configuré.
4. Vérifiez la santé du service : `https://esprit-5twin4-hackflow.onrender.com/healthz/`.

## 8. Limites du plan gratuit à connaître

- La base SQLite est dans `/tmp` (`DATABASE_PATH`). Elle est réinitialisée à chaque redémarrage ou redéploiement du service. Les comptes, les données et les bannières générées (dans `/tmp/media`) disparaissent donc alors. Pour une persistance réelle, il faut un disque persistant Render ou une base PostgreSQL.
- Le service gratuit se met en veille après une période d'inactivité. La première requête peut être lente.
- `CELERY_TASK_ALWAYS_EAGER` vaut `true` : les tâches IA s'exécutent dans la requête, sans worker séparé.

## 9. Sécurité

- Ne commitez jamais de clé dans le dépôt. Le fichier `.env` doit rester dans `.gitignore`.
- Si une clé a été exposée (dans un commit, un message ou une capture), révoquez-la et créez-en une nouvelle.
- Utilisez des clés distinctes pour le développement local et pour Render.
