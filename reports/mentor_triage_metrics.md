# Métriques du tri IA des demandes d'aide (module Mentor)

Généré le : 2026-10-24T18:34:10.095557+00:00  
Modèle : `llama3.2` (Ollama local)  
Exemples : 60 analysés / 60 (0 échecs)

## Catégorie

Accuracy : **0.950** — Précision macro : 0.962 — Rappel macro : 0.950 — F1 macro : **0.951**

| Classe | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| Back-End Development & Databases | 1.000 | 1.000 | 1.000 | 10 |
| Front-End Development & Frameworks | 0.769 | 1.000 | 0.870 | 10 |
| AI, LLMs & Machine Learning | 1.000 | 1.000 | 1.000 | 10 |
| DevOps, Docker & Cloud Deployment | 1.000 | 0.900 | 0.947 | 10 |
| UI/UX Design & User Experience | 1.000 | 0.800 | 0.889 | 10 |
| Pitch & Presentation Structure | 1.000 | 1.000 | 1.000 | 10 |

Matrice de confusion (lignes = réel, colonnes = prédit) :

| | P1 | P2 | P3 | P4 | P5 | P6 |
|---|---:|---:|---:|---:|---:|---:|
| R1 Back-End Development & Databases | 10 | 0 | 0 | 0 | 0 | 0 |
| R2 Front-End Development & Frameworks | 0 | 10 | 0 | 0 | 0 | 0 |
| R3 AI, LLMs & Machine Learning | 0 | 0 | 10 | 0 | 0 | 0 |
| R4 DevOps, Docker & Cloud Deployment | 0 | 1 | 0 | 9 | 0 | 0 |
| R5 UI/UX Design & User Experience | 0 | 2 | 0 | 0 | 8 | 0 |
| R6 Pitch & Presentation Structure | 0 | 0 | 0 | 0 | 0 | 10 |

## Urgence

Accuracy : **0.800** — Précision macro : 0.795 — Rappel macro : 0.801 — F1 macro : **0.795**

| Classe | Précision | Rappel | F1 | Support |
|---|---:|---:|---:|---:|
| blocking | 0.750 | 0.882 | 0.811 | 17 |
| important | 0.765 | 0.650 | 0.703 | 20 |
| normal | 0.870 | 0.870 | 0.870 | 23 |

Matrice de confusion (lignes = réel, colonnes = prédit) :

| | P1 | P2 | P3 |
|---|---:|---:|---:|
| R1 blocking | 15 | 2 | 0 |
| R2 important | 4 | 13 | 3 |
| R3 normal | 1 | 2 | 20 |

## Performance

Démarrage à froid (1er appel, chargement du modèle) : 2226 ms  
Appels à chaud : moyenne 1175 ms — p50 1182 ms — p95 1333 ms — max 1403 ms

L'analyse s'exécute en arrière-plan (Celery/Redis, ou thread en développement) : la page du mentor ne bloque jamais pendant l'appel au modèle.
