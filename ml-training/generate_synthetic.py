"""Generate synthetic transactions with injected anomalies.

Rows are emitted in exactly the shape of a `transactions` Kafka event, plus two
label columns (is_anomaly, anomaly_kind) that exist only for evaluation. The
Isolation Forest itself never sees the labels -- it is unsupervised. The labels
are used solely to measure precision/recall and to calibrate the threshold in
train_model.py.

Usage:
    python generate_synthetic.py --count 50000 --out data/transactions.csv
"""

import argparse
import csv
import os
import uuid
from datetime import datetime, timedelta

import numpy as np

# Fixed base date so runs are byte-reproducible for a given seed.
BASE_DATE = datetime(2026, 1, 1)
HISTORY_DAYS = 90

TRANSACTION_TYPES = ('deposit', 'withdrawal', 'transfer')
TYPE_WEIGHTS = (0.30, 0.42, 0.28)

# Amounts in cents, log-normal: median ~= $54, long right tail.
AMOUNT_LOG_MEAN = 8.6
AMOUNT_LOG_SIGMA = 1.15

# Business-hours-weighted activity, 24 entries indexed by hour.
HOUR_WEIGHTS = np.array([
    0.20, 0.10, 0.10, 0.10, 0.15, 0.30,   # 00-05 dead of night
    1.00, 2.00, 3.50, 4.50, 5.00, 5.00,   # 06-11 morning ramp
    4.50, 4.50, 5.00, 5.00, 4.50, 4.00,   # 12-17 afternoon
    3.50, 3.00, 2.50, 1.50, 0.80, 0.40,   # 18-23 evening taper
])

# Monday..Sunday; weekends quieter.
DAY_WEIGHTS = np.array([1.00, 1.00, 1.00, 1.00, 1.10, 0.60, 0.50])

# Relative frequency of each injected anomaly pattern.
ANOMALY_KINDS = ('huge_amount', 'odd_hour', 'huge_amount_odd_hour')
ANOMALY_KIND_WEIGHTS = (0.40, 0.35, 0.25)

ODD_HOURS = (1, 2, 3, 4)

FIELDNAMES = [
    'transaction_id', 'initiator_id', 'from_account_id', 'to_account_id',
    'amount', 'type', 'timestamp', 'is_anomaly', 'anomaly_kind',
]


def _normalized(weights):
    return np.asarray(weights, dtype=float) / np.sum(weights)


def _random_uuid(rng):
    """Draw a UUID from the seeded RNG (numpy caps integers at 64 bits)."""
    value = 0
    for part in rng.integers(0, 2 ** 32, size=4, dtype=np.uint32):
        value = (value << 32) | int(part)
    return str(uuid.UUID(int=value))


def _sample_timestamp(rng, hour=None):
    """Pick a timestamp; if `hour` is given, force that hour of the day."""
    day_offset = int(rng.integers(0, HISTORY_DAYS))
    candidate = BASE_DATE + timedelta(days=day_offset)

    # Resample the day until it matches the weekday activity profile.
    while rng.random() > DAY_WEIGHTS[candidate.weekday()] / DAY_WEIGHTS.max():
        day_offset = int(rng.integers(0, HISTORY_DAYS))
        candidate = BASE_DATE + timedelta(days=day_offset)

    if hour is None:
        hour = int(rng.choice(24, p=_normalized(HOUR_WEIGHTS)))

    return candidate.replace(
        hour=hour,
        minute=int(rng.integers(0, 60)),
        second=int(rng.integers(0, 60)),
    )


def _sample_amount(rng):
    """Ordinary transaction amount in whole cents."""
    return int(rng.lognormal(AMOUNT_LOG_MEAN, AMOUNT_LOG_SIGMA))


def _build_row(rng, accounts, is_anomaly):
    """Produce one transaction row, normal or anomalous."""
    txn_type = str(rng.choice(TRANSACTION_TYPES, p=TYPE_WEIGHTS))
    amount = _sample_amount(rng)
    anomaly_kind = ''
    forced_hour = None

    if is_anomaly:
        anomaly_kind = str(rng.choice(ANOMALY_KINDS, p=ANOMALY_KIND_WEIGHTS))
        if anomaly_kind == 'huge_amount':
            amount = int(amount * rng.uniform(40, 400))
        elif anomaly_kind == 'odd_hour':
            forced_hour = int(rng.choice(ODD_HOURS))
            amount = int(amount * rng.uniform(3, 10))
        else:  # huge_amount_odd_hour
            forced_hour = int(rng.choice(ODD_HOURS))
            amount = int(amount * rng.uniform(40, 400))

    ts = _sample_timestamp(rng, hour=forced_hour)

    # Mirror how the real producers populate the account fields per type.
    from_account = to_account = ''
    if txn_type == 'deposit':
        to_account = str(rng.choice(accounts))
    elif txn_type == 'withdrawal':
        from_account = str(rng.choice(accounts))
    else:
        from_account, to_account = (str(a) for a in rng.choice(accounts, size=2, replace=False))

    return {
        'transaction_id': _random_uuid(rng),
        'initiator_id': str(rng.choice(accounts)),
        'from_account_id': from_account,
        'to_account_id': to_account,
        'amount': amount,
        'type': txn_type,
        'timestamp': ts.isoformat(),
        'is_anomaly': int(is_anomaly),
        'anomaly_kind': anomaly_kind,
    }


def generate(count, anomaly_rate, seed):
    rng = np.random.default_rng(seed)
    accounts = [str(uuid.UUID(int=i)) for i in range(1, 201)]

    n_anomalies = int(round(count * anomaly_rate))
    flags = np.zeros(count, dtype=bool)
    flags[:n_anomalies] = True
    rng.shuffle(flags)

    return [_build_row(rng, accounts, bool(f)) for f in flags]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=50000,
                        help='total transactions to generate (default: 50000)')
    parser.add_argument('--anomaly-rate', type=float, default=0.01,
                        help='fraction that are anomalous (default: 0.01)')
    parser.add_argument('--seed', type=int, default=42,
                        help='RNG seed for reproducibility (default: 42)')
    parser.add_argument('--out', default='data/transactions.csv',
                        help='output CSV path (default: data/transactions.csv)')
    args = parser.parse_args()

    rows = generate(args.count, args.anomaly_rate, args.seed)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    with open(args.out, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    n_anom = sum(r['is_anomaly'] for r in rows)
    print(f"Wrote {len(rows):,} transactions to {args.out}")
    print(f"  anomalies: {n_anom:,} ({n_anom / len(rows):.2%})")
    for kind in ANOMALY_KINDS:
        k = sum(1 for r in rows if r['anomaly_kind'] == kind)
        print(f"    {kind:24} {k:>5,}")


if __name__ == '__main__':
    main()
