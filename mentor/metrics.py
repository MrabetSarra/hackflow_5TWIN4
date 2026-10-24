"""Métriques de classification (sans dépendance externe) pour évaluer le tri IA."""


def confusion_matrix(y_true, y_pred, labels):
    """matrix[i][j] = nombre d'exemples de classe réelle labels[i] prédits labels[j]."""
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for true, pred in zip(y_true, y_pred):
        if true in index and pred in index:
            matrix[index[true]][index[pred]] += 1
    return matrix


def classification_report(y_true, y_pred, labels):
    """Précision, rappel, F1 et support par classe, plus accuracy et moyennes macro."""
    per_class = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {'precision': round(precision, 3), 'recall': round(recall, 3), 'f1': round(f1, 3),
                            'support': tp + fn}

    present = [label for label in labels if per_class[label]['support']]
    total = len(y_true)
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)

    def macro(key):
        return round(sum(per_class[label][key] for label in present) / len(present), 3) if present else 0.0

    return {
        'accuracy': round(correct / total, 3) if total else 0.0,
        'macro_precision': macro('precision'),
        'macro_recall': macro('recall'),
        'macro_f1': macro('f1'),
        'per_class': per_class,
        'labels': labels,
        'confusion_matrix': confusion_matrix(y_true, y_pred, labels),
        'total': total,
    }


def percentile(values, pct):
    """Percentile par interpolation linéaire (pct entre 0 et 100)."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def latency_stats(latencies_ms):
    if not latencies_ms:
        return {'count': 0, 'mean_ms': None, 'p50_ms': None, 'p95_ms': None, 'max_ms': None}
    return {
        'count': len(latencies_ms),
        'mean_ms': round(sum(latencies_ms) / len(latencies_ms)),
        'p50_ms': percentile(latencies_ms, 50),
        'p95_ms': percentile(latencies_ms, 95),
        'max_ms': max(latencies_ms),
    }
