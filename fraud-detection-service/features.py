"""Feature extraction for fraud scoring.

SINGLE SOURCE OF TRUTH. ml-training/train_model.py imports this module directly
rather than keeping its own copy, so training and serving can never drift apart.
Changing FEATURE_NAMES or the order of the vector returned by extract_features()
invalidates every previously trained artifact -- bump MODEL_VERSION in
train_model.py and retrain when you do.

DELIBERATE SCOPE LIMIT
----------------------
Every feature here describes a transaction *in isolation*: how big it is, when
it happened, what kind it is. Nothing looks at the account's history, its
balance, its typical behaviour, or how many transactions it made in the last
hour. That was a conscious choice, not an oversight -- see the "Feature scope"
section of ml-training/README.md for the reasoning and for the concrete fraud
patterns this cannot detect.
"""

import math
from datetime import datetime

# Order is load-bearing: the model was fit on exactly this sequence.
#
# Both a raw and a log amount are present on purpose. log_amount keeps ordinary
# spending on a comparable scale, but on its own it compresses the tail so hard
# that a 400x transaction looks only mildly unusual to an isolation tree -- an
# earlier version with log_amount alone caught 2% of large-amount anomalies.
# amount_cents restores the separation that makes them isolate in a few splits.
FEATURE_NAMES = [
    'amount_cents',
    'log_amount',
    'hour_of_day',
    'day_of_week',
    'is_weekend',
    'is_night',
    'type_deposit',
    'type_withdrawal',
    'type_transfer',
]

TRANSACTION_TYPES = ('deposit', 'withdrawal', 'transfer')

# Hours in [NIGHT_START, NIGHT_END) count as "night".
NIGHT_START_HOUR = 0
NIGHT_END_HOUR = 6


def parse_timestamp(value):
    """Accept either an ISO-8601 string (as sent over Kafka) or a datetime."""
    if isinstance(value, datetime):
        return value
    if not value:
        raise ValueError("transaction event is missing 'timestamp'")
    return datetime.fromisoformat(value)


def extract_features(txn):
    """Map a transaction event dict to an ordered feature vector.

    Raises ValueError on malformed input rather than coercing it, so the caller
    can count it as a scoring error instead of silently scoring garbage.
    """
    amount = txn.get('amount')
    if amount is None:
        raise ValueError("transaction event is missing 'amount'")
    amount = float(amount)
    if amount < 0:
        raise ValueError(f"negative amount: {amount}")

    txn_type = txn.get('type')
    if txn_type not in TRANSACTION_TYPES:
        raise ValueError(f"unknown transaction type: {txn_type!r}")

    ts = parse_timestamp(txn.get('timestamp'))
    hour = ts.hour
    day_of_week = ts.weekday()  # Monday=0 .. Sunday=6

    return [
        amount,
        math.log1p(amount),
        float(hour),
        float(day_of_week),
        1.0 if day_of_week >= 5 else 0.0,
        1.0 if NIGHT_START_HOUR <= hour < NIGHT_END_HOUR else 0.0,
        1.0 if txn_type == 'deposit' else 0.0,
        1.0 if txn_type == 'withdrawal' else 0.0,
        1.0 if txn_type == 'transfer' else 0.0,
    ]
