# Jeu d'évaluation du tri IA (module Mentor)

`triage_dataset.json` contient 60 demandes d'aide réalistes (français et anglais), étiquetées à la main :
10 par catégorie (les 6 catégories du formulaire étudiant) et une urgence (`blocking`, `important`, `normal`).

Lancer l'évaluation (Ollama doit tourner en local) :

```
python manage.py evaluate_triage                       # les 60 exemples
python manage.py evaluate_triage --include-corrections  # + tickets réels corrigés par les mentors
```

Le rapport est écrit dans `reports/mentor_triage_metrics.md` (lisible) et `reports/mentor_triage_metrics.json`
(affiché sur la page « Métriques IA » de l'espace mentor).

## Historique des réglages du prompt (modèle `llama3.2`, 3B, température 0)

| Version | Changement | Catégorie (accuracy / F1 macro) | Urgence (accuracy / F1 macro) |
|---|---|---|---|
| v1 | Noms des catégories seulement | 0,550 / 0,508 | 0,850 / 0,848 |
| v2 | + définition générale de chaque catégorie | 0,933 / 0,934 | 0,750 / 0,726 |
| v3 | + règle explicite bloquant / important / normal | 0,950 / 0,951 | 0,800 / 0,795 |

Erreur principale de la v1 : 8 tickets Back-End sur 10 classés DevOps (le petit modèle ne connaissait pas la
frontière « code serveur » / « déploiement »). La v2 a fait baisser l'urgence (le modèle sur-escaladait vers
« bloquant ») ; la v3 précise que « bloquant » signifie que l'équipe est totalement arrêtée.

**Limite assumée :** le prompt a été ajusté en observant ce même jeu de 60 exemples, les scores sont donc
probablement optimistes. Les corrections saisies par les mentors en conditions réelles (stockées dans
`RequestTriage.corrected_*`) fournissent une mesure indépendante via `--include-corrections`, et le taux
d'accord IA / mentor est affiché en direct sur la page « Métriques IA ».
