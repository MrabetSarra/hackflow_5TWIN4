"""Évalue le tri IA des demandes d'aide sur un jeu de tickets étiquetés.

Exemples :
    python manage.py evaluate_triage
    python manage.py evaluate_triage --limit 12
    python manage.py evaluate_triage --include-corrections
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from mentor.ai import CATEGORIES, URGENCIES, TriageError, classify, model_name
from mentor.metrics import classification_report, latency_stats
from mentor.models import RequestTriage

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / 'ai_dataset' / 'triage_dataset.json'
REPORT_JSON = Path(settings.BASE_DIR) / 'reports' / 'mentor_triage_metrics.json'
REPORT_MD = Path(settings.BASE_DIR) / 'reports' / 'mentor_triage_metrics.md'


class Command(BaseCommand):
    help = "Mesure la qualité (précision, rappel, F1, matrice de confusion) et la latence du tri IA."

    def add_arguments(self, parser):
        parser.add_argument('--dataset', default=str(DEFAULT_DATASET), help='Fichier JSON de tickets étiquetés.')
        parser.add_argument('--limit', type=int, default=0, help="Nombre maximum d'exemples (0 = tous).")
        parser.add_argument('--include-corrections', action='store_true',
                            help='Ajoute les tickets réels corrigés par les mentors au jeu de test.')

    def handle(self, *args, **options):
        samples = self._load_samples(options['dataset'], options['include_corrections'])
        if options['limit']:
            samples = samples[:options['limit']]
        if not samples:
            raise CommandError('Aucun exemple à évaluer.')

        self.stdout.write(f'Évaluation de {len(samples)} tickets avec le modèle « {model_name()} »…')
        true_cat, pred_cat, true_urg, pred_urg, latencies, errors = [], [], [], [], [], []
        for number, sample in enumerate(samples, 1):
            try:
                result, latency = classify(sample['subject'], sample['description'])
            except TriageError as exc:
                errors.append({'subject': sample['subject'], 'error': str(exc)})
                self.stderr.write(f'  [{number}] échec : {exc}')
                if len(errors) == 3 and not latencies:
                    raise CommandError('Trois échecs consécutifs : Ollama est-il lancé ?') from exc
                continue
            true_cat.append(sample['category'])
            pred_cat.append(result['category'])
            true_urg.append(sample['urgency'])
            pred_urg.append(result['urgency'])
            latencies.append(latency)
            mark = 'OK ' if result['category'] == sample['category'] else 'KO '
            self.stdout.write(f'  [{number}] {mark}{latency:>6} ms  {sample["subject"][:60]}')

        report = {
            'generated_at': timezone.now().isoformat(),
            'model': model_name(),
            'samples': len(samples),
            'answered': len(latencies),
            'errors': errors,
            'category': classification_report(true_cat, pred_cat, CATEGORIES),
            'urgency': classification_report(true_urg, pred_urg, URGENCIES),
            # Le 1er appel inclut le chargement du modèle en mémoire : on le sépare des appels « à chaud ».
            'latency': latency_stats(latencies[1:] or latencies),
            'cold_start_ms': latencies[0] if latencies else None,
        }
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        REPORT_MD.write_text(self._markdown(report), encoding='utf-8')

        cat, urg, lat = report['category'], report['urgency'], report['latency']
        self.stdout.write(self.style.SUCCESS(
            f"Catégorie : accuracy {cat['accuracy']:.3f}, F1 macro {cat['macro_f1']:.3f} | "
            f"Urgence : accuracy {urg['accuracy']:.3f}, F1 macro {urg['macro_f1']:.3f} | "
            f"Latence p50 {lat['p50_ms']} ms, p95 {lat['p95_ms']} ms"))
        self.stdout.write(f'Rapport : {REPORT_MD}')

    def _load_samples(self, path, include_corrections):
        try:
            samples = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(f'Jeu de données illisible : {exc}') from exc
        for sample in samples:
            if sample.get('category') not in CATEGORIES or sample.get('urgency') not in URGENCIES:
                raise CommandError(f"Étiquette invalide dans l'exemple « {sample.get('subject')} ».")
        if include_corrections:
            corrected = (RequestTriage.objects.exclude(corrected_category='').exclude(corrected_urgency='')
                         .select_related('help_request'))
            samples += [{'subject': t.help_request.subject, 'description': t.help_request.description,
                         'category': t.corrected_category, 'urgency': t.corrected_urgency} for t in corrected]
        return samples

    @staticmethod
    def _markdown(report):
        lines = [
            '# Métriques du tri IA des demandes d\'aide (module Mentor)', '',
            f"Généré le : {report['generated_at']}  ",
            f"Modèle : `{report['model']}` (Ollama local)  ",
            f"Exemples : {report['answered']} analysés / {report['samples']} ({len(report['errors'])} échecs)", '',
        ]
        for key, title in (('category', 'Catégorie'), ('urgency', 'Urgence')):
            section = report[key]
            lines += [f'## {title}', '',
                      f"Accuracy : **{section['accuracy']:.3f}** — Précision macro : {section['macro_precision']:.3f} — "
                      f"Rappel macro : {section['macro_recall']:.3f} — F1 macro : **{section['macro_f1']:.3f}**", '',
                      '| Classe | Précision | Rappel | F1 | Support |', '|---|---:|---:|---:|---:|']
            for label, values in section['per_class'].items():
                lines.append(f"| {label} | {values['precision']:.3f} | {values['recall']:.3f} | "
                             f"{values['f1']:.3f} | {values['support']} |")
            labels = section['labels']
            lines += ['', 'Matrice de confusion (lignes = réel, colonnes = prédit) :', '',
                      '| | ' + ' | '.join(f'P{i + 1}' for i in range(len(labels))) + ' |',
                      '|---|' + '---:|' * len(labels)]
            for i, (label, row) in enumerate(zip(labels, section['confusion_matrix'])):
                lines.append(f'| R{i + 1} {label} | ' + ' | '.join(str(v) for v in row) + ' |')
            lines.append('')
        lat = report['latency']
        lines += ['## Performance', '',
                  f"Démarrage à froid (1er appel, chargement du modèle) : {report['cold_start_ms']} ms  ",
                  f"Appels à chaud : moyenne {lat['mean_ms']} ms — p50 {lat['p50_ms']} ms — p95 {lat['p95_ms']} ms — "
                  f"max {lat['max_ms']} ms", '',
                  "L'analyse s'exécute en arrière-plan (Celery/Redis, ou thread en développement) : "
                  "la page du mentor ne bloque jamais pendant l'appel au modèle.", '']
        return '\n'.join(lines)
