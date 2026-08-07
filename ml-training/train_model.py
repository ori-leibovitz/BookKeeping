"""Train the Isolation Forest used by fraud-detection-service.

Imports features.py directly from the service directory so that training and
serving can never disagree about what a feature vector means.

The model is unsupervised -- it never sees the is_anomaly labels. Those are used
only after the fact, on a held-out split, to measure precision/recall and to
show the threshold trade-off.

Usage:
    python train_model.py --data data/transactions.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import joblib
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

# features.py is the single source of truth and lives with the service.
SERVICE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'fraud-detection-service'
)
sys.path.insert(0, SERVICE_DIR)
from features import FEATURE_NAMES, extract_features  # noqa: E402

# Bump whenever features.py or the training setup changes.
# 1.1.0 - added raw amount_cents alongside log_amount; large-amount recall went
#         from 0.02 to the value recorded in model_meta.json.
MODEL_VERSION = '1.1.0'

DEFAULT_MODEL_DIR = os.path.join(SERVICE_DIR, 'models')
HOLDOUT_FRACTION = 0.30
CONTAMINATION = 0.01
N_ESTIMATORS = 200
SEED = 42


def build_matrix(df):
    """Run every row through the exact function the service will use."""
    return np.array([extract_features(row) for row in df.to_dict('records')])


def normalize(raw, lo, hi):
    """Map raw anomaly scores onto 0..1, where 1 is most suspicious.

    lo/hi are frozen from the training split and stored in the artifact, so a
    given transaction scores identically today and in production. Values beyond
    the training range clip rather than escaping [0, 1].
    """
    return np.clip((raw - lo) / (hi - lo), 0.0, 1.0)


def histogram(scores, bins=20, width=44):
    """Small ASCII histogram so the distribution is visible in the log."""
    counts, edges = np.histogram(scores, bins=bins, range=(0.0, 1.0))
    peak = counts.max() or 1
    lines = []
    for count, left, right in zip(counts, edges[:-1], edges[1:]):
        bar = '#' * int(round(width * count / peak))
        lines.append(f"    {left:.2f}-{right:.2f} |{bar:<{width}} {count:>7,}")
    return '\n'.join(lines)


def describe(name, scores):
    qs = np.percentile(scores, [1, 25, 50, 75, 95, 99])
    return (f"  {name:<12} n={len(scores):>7,}  "
            f"min={scores.min():.4f}  p25={qs[1]:.4f}  p50={qs[2]:.4f}  "
            f"p75={qs[3]:.4f}  p95={qs[4]:.4f}  p99={qs[5]:.4f}  max={scores.max():.4f}")


def tradeoff_table(scores, labels, thresholds):
    """Precision / recall / F1 / flagged-rate at each candidate threshold."""
    rows = []
    total = len(scores)
    for t in thresholds:
        flagged = scores >= t
        n_flagged = int(flagged.sum())
        tp = int((flagged & (labels == 1)).sum())
        fp = n_flagged - tp
        fn = int(((~flagged) & (labels == 1)).sum())
        precision = tp / n_flagged if n_flagged else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        rows.append({
            'threshold': float(t), 'flagged': n_flagged,
            'flagged_rate': n_flagged / total, 'tp': tp, 'fp': fp, 'fn': fn,
            'precision': precision, 'recall': recall, 'f1': f1,
        })
    return rows


def print_tradeoff(rows, chosen=None):
    print(f"  {'thresh':>7} {'flagged':>8} {'rate':>7} {'TP':>5} {'FP':>6} "
          f"{'FN':>5} {'precision':>10} {'recall':>8} {'F1':>7}")
    print("  " + "-" * 74)
    for r in rows:
        mark = ' <-- chosen' if chosen is not None and abs(r['threshold'] - chosen) < 1e-9 else ''
        print(f"  {r['threshold']:>7.2f} {r['flagged']:>8,} {r['flagged_rate']:>6.2%} "
              f"{r['tp']:>5,} {r['fp']:>6,} {r['fn']:>5,} "
              f"{r['precision']:>10.3f} {r['recall']:>8.3f} {r['f1']:>7.3f}{mark}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='data/transactions.csv')
    parser.add_argument('--model-dir', default=DEFAULT_MODEL_DIR)
    parser.add_argument('--threshold', type=float, default=None,
                        help='override the auto-selected (best-F1) threshold')
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    print(f"Loaded {len(df):,} rows from {args.data}")
    print(f"Features ({len(FEATURE_NAMES)}): {', '.join(FEATURE_NAMES)}\n")

    X = build_matrix(df)
    y = df['is_anomaly'].to_numpy()

    rng = np.random.default_rng(SEED)
    idx = rng.permutation(len(X))
    cut = int(len(X) * (1 - HOLDOUT_FRACTION))
    train_idx, hold_idx = idx[:cut], idx[cut:]

    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=SEED,
        n_jobs=-1,
    )
    model.fit(X[train_idx])
    print(f"Fitted IsolationForest on {len(train_idx):,} rows "
          f"(holdout {len(hold_idx):,}, contamination={CONTAMINATION})\n")

    # decision_function is positive for inliers; negate so bigger == more suspicious.
    raw_train = -model.decision_function(X[train_idx])
    lo, hi = float(raw_train.min()), float(raw_train.max())

    scores = normalize(-model.decision_function(X[hold_idx]), lo, hi)
    y_hold = y[hold_idx]
    normal, anomalous = scores[y_hold == 0], scores[y_hold == 1]

    print("=" * 78)
    print("SCORE DISTRIBUTION (holdout)")
    print("=" * 78)
    print(describe('normal', normal))
    print(describe('anomalous', anomalous))
    print("\n  All holdout transactions:")
    print(histogram(scores))
    print("\n  Injected anomalies only:")
    print(histogram(anomalous))

    print("\n" + "=" * 78)
    print("RANKING QUALITY (threshold-independent)")
    print("=" * 78)
    print(f"  ROC AUC           {roc_auc_score(y_hold, scores):.4f}")
    print(f"  Average precision {average_precision_score(y_hold, scores):.4f}"
          f"   (baseline = prevalence = {y_hold.mean():.4f})")

    candidates = np.round(np.arange(0.05, 1.00, 0.05), 2)
    rows = tradeoff_table(scores, y_hold, candidates)
    best = max(rows, key=lambda r: r['f1'])
    threshold = args.threshold if args.threshold is not None else best['threshold']

    print("\n" + "=" * 78)
    print("THRESHOLD TRADE-OFF (holdout)")
    print("=" * 78)
    print_tradeoff(rows, chosen=threshold)
    print(f"\n  Best F1 at threshold {best['threshold']:.2f}: "
          f"precision={best['precision']:.3f} recall={best['recall']:.3f} "
          f"flagging {best['flagged_rate']:.2%} of traffic")
    if args.threshold is not None:
        print(f"  Overridden by --threshold {args.threshold}")

    chosen_row = next(r for r in rows if abs(r['threshold'] - threshold) < 1e-9)

    # Which injected patterns does this feature set actually catch? This is the
    # empirical basis for the "Feature scope" section of README.md.
    print("\n" + "=" * 78)
    print(f"RECALL BY ANOMALY PATTERN (holdout, threshold={threshold:.2f})")
    print("=" * 78)
    kinds = df['anomaly_kind'].fillna('').to_numpy()[hold_idx]
    per_kind = {}
    for kind in sorted(k for k in set(kinds) if k):
        mask = kinds == kind
        caught = int((scores[mask] >= threshold).sum())
        total_kind = int(mask.sum())
        rate = caught / total_kind if total_kind else 0.0
        per_kind[kind] = {'caught': caught, 'total': total_kind, 'recall': rate}
        print(f"  {kind:<24} {caught:>4,}/{total_kind:<5,} caught   recall={rate:.3f}")

    os.makedirs(args.model_dir, exist_ok=True)
    model_path = os.path.join(args.model_dir, 'isolation_forest.joblib')
    meta_path = os.path.join(args.model_dir, 'model_meta.json')

    joblib.dump(model, model_path)
    meta = {
        'model_version': MODEL_VERSION,
        'trained_at': datetime.now().isoformat(timespec='seconds'),
        'sklearn_version': sklearn.__version__,
        'feature_names': FEATURE_NAMES,
        'score_min': lo,
        'score_max': hi,
        'threshold': float(threshold),
        'training': {
            'n_train': len(train_idx),
            'n_holdout': len(hold_idx),
            'contamination': CONTAMINATION,
            'n_estimators': N_ESTIMATORS,
            'seed': SEED,
        },
        'holdout_metrics': {
            'roc_auc': float(roc_auc_score(y_hold, scores)),
            'average_precision': float(average_precision_score(y_hold, scores)),
            'precision': chosen_row['precision'],
            'recall': chosen_row['recall'],
            'f1': chosen_row['f1'],
            'flagged_rate': chosen_row['flagged_rate'],
            'recall_by_anomaly_kind': per_kind,
        },
    }
    with open(meta_path, 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=2)

    print(f"\nSaved model -> {model_path}")
    print(f"Saved meta  -> {meta_path}")
    print(f"  version={MODEL_VERSION} sklearn={sklearn.__version__} threshold={threshold:.2f}")


if __name__ == '__main__':
    main()
