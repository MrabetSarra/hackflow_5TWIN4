# Audit d'accessibilité — espace Mentor

Outil : **Lighthouse 12.8.2** (catégorie Accessibilité, moteur axe-core), Chrome headless, le 24/10/2026,
connecté avec le compte de démonstration `marc.dubois` (données `python manage.py seed_mentor`).
Chaque page est auditée dans les deux thèmes de l'application (clair et sombre).

## Résultats finaux

| Page | Thème clair | Thème sombre |
|---|---:|---:|
| /mentor/ (tableau de bord) | 100 | 100 |
| /mentor/teams/ | 100 | 100 |
| /mentor/teams/1/ (fiche équipe) | 100 | 100 |
| /mentor/requests/ (demandes d'aide + IA) | 100 | 100 |
| /mentor/sessions/ | 100 | 100 |
| /mentor/sessions/new/ (formulaire) | 100 | 100 |
| /mentor/submissions/ | 100 | 100 |
| /mentor/submissions/4/evaluate/ (formulaire de notation) | 100 | 100 |
| /mentor/evaluations/ | 100 | 100 |
| /mentor/evaluations/3/ (détail) | 100 | 100 |
| /mentor/ai-metrics/ | 100 | 100 |

Rapports complets joints (exemple représentatif) : `light_dashboard.report.html`, `dark_dashboard.report.html`
(le cookie de session utilisé pour l'audit a été masqué).

## Avant / après

Score initial : **96** sur toutes les pages (thème sombre) puis 96 en thème clair après une première correction.

| Problème détecté | Correction |
|---|---|
| Contraste insuffisant (WCAG AA 4.5:1) : texte coloré Bootstrap (`text-primary`, `text-success`…) sur fonds teintés et en thème sombre | `static/css/mentor.css` : variantes « emphasis » de Bootstrap, limitées aux pages mentor (`body.mentor-space`) pour ne pas modifier le thème commun |
| Bouton principal : blanc sur #6366f1 = 4.46:1 | Teinte #4f46e5 (6.3:1) dans l'espace mentor |
| Badge d'urgence « Important » : blanc sur jaune = 1.63:1 | `text-bg-*` : Bootstrap choisit automatiquement une couleur de texte lisible |
| Menu profil : nom accessible (« Menu du profil ») différent du texte visible (initiales) | Texte masqué visuellement ajouté après les initiales (WCAG 2.5.3 « Label in Name ») |

## Bonnes pratiques déjà en place

- Structure sémantique : `<header>`, `<nav>`, `<main id="main-content">` (lien d'évitement), `<aside>`, `<section>`
  et `<article>` titrés, un seul `<h1>` par page puis `<h2>`/`<h3>`.
- Formulaires : chaque champ a un `<label>`, `aria-required`, erreurs reliées par `aria-describedby`.
- Boutons à icône seule : `aria-label` ; icônes décoratives : `aria-hidden="true"` ; liens vers un nouvel onglet
  annoncés (« nouvel onglet ») ; tableaux avec `<caption>` et `scope`.
- Contenu dynamique (suggestion IA, total /20 pendant la saisie) : `aria-live="polite"`.
- Focus clavier toujours visible (`:focus-visible`, contour 3 px).

## Reproduire l'audit

```
npx lighthouse@12.8.2 http://127.0.0.1:8000/mentor/ --only-categories=accessibility \
  --extra-headers='{"Cookie":"sessionid=<cookie de session mentor>"}' \
  --chrome-flags="--headless=new --blink-settings=preferredColorScheme=1"   # 0 = thème sombre
```

Limite : Lighthouse vérifie automatiquement une partie des critères WCAG. La navigation complète au clavier
(Tab / Entrée sur les formulaires, onglets, `<details>`, boutons « Transférer » / « Marquer résolu ») doit aussi
être montrée manuellement en soutenance.
