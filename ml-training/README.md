# Fraud Model Training

Offline training for the Isolation Forest that `fraud-detection-service` serves.
Nothing here ships in the runtime image.

## Retraining

```bash
pip install -r requirements.txt
python generate_synthetic.py --count 50000 --out data/transactions.csv
python train_model.py --data data/transactions.csv --threshold 0.65
```

This writes `../fraud-detection-service/models/isolation_forest.joblib` and
`model_meta.json`. Both are committed to git — the artifact is versioned with the
code that serves it, and `COPY . .` in the Dockerfile bakes it into the image.

`--threshold` is optional. Without it the script picks the best-F1 point and
prints the full trade-off table so you can choose deliberately instead.

### Version pinning is load-bearing

`scikit-learn`, `numpy`, and `joblib` are pinned to identical versions in
`requirements.txt` here and in `fraud-detection-service/requirements.txt`. A
joblib artifact loaded under a different scikit-learn can deserialize into a
subtly broken estimator that still produces plausible numbers. `scorer.py`
records and asserts the training version at boot and refuses to start on a
mismatch, so this fails loudly rather than silently.

## Feature scope — a deliberate limit

Every feature in `fraud-detection-service/features.py` describes a transaction
**in isolation**: its size, its timing, its type.

| Feature | |
|---|---|
| `amount_cents`, `log_amount` | how big |
| `hour_of_day`, `is_night`, `day_of_week`, `is_weekend` | when |
| `type_deposit`, `type_withdrawal`, `type_transfer` | what kind |

Nothing here looks at the account's history, its balance, its normal behaviour,
or how many transactions it made in the last hour. **That was chosen, not
overlooked.** Stateless scoring means the service has no Redis or historical-read
dependency, latency is constant, and the training data is honest — synthetic
velocity is easy to generate and easy to make unrealistically separable, which
would have produced flattering metrics that do not survive contact with real
traffic.

### What this catches, and what it cannot

Measured on a 15,000-transaction holdout with 156 injected anomalies, at
threshold 0.65 (ROC AUC 0.996, average precision 0.790 against a 0.010 baseline):

| Injected pattern | Recall |
|---|---|
| Large amount at an odd hour | 1.000 |
| Odd-hour activity | 0.875 |
| Large amount alone | 0.769 |

Overall: recall 0.878, precision 0.474, flagging 1.93% of traffic. Roughly half
of all alerts are false positives — acceptable when a flag costs a minute of
review and a miss costs the transaction, but it means these alerts are for
humans, not for automatic blocking.

The following are **structurally invisible** to this feature set, and no amount
of retraining will change that:

- **Card testing / velocity attacks** — 200 small transactions in five minutes.
  Each one looks perfectly ordinary in isolation, because it is.
- **Account takeover with normal-sized transactions** — spending that is typical
  for the population but wildly atypical for *this* account. There is no
  per-account baseline to compare against.
- **Structuring** — one $10,000 transfer split into eleven $900 transfers to stay
  under a threshold. Every part is unremarkable.
- **Drain-the-account** — a withdrawal of exactly the full balance. Balance is
  not an input, so a $500 drain of a $500 account scores like any other $500
  withdrawal.

### Extending it

The natural next step is per-account velocity: transaction count and amount sum
over 1h/24h windows, read from the Redis already wired into the stack. That
covers card testing and structuring. It costs a Redis dependency on the scoring
path, and `generate_synthetic.py` has to grow a per-account temporal model so the
training distribution reflects real burst behaviour.

Anything that needs a per-account baseline (takeover, drain) additionally needs a
historical read from Postgres per event.

If you add features, edit `features.py` — it is the single source of truth,
imported here via `sys.path` rather than copied, so training and serving cannot
drift. Then bump `MODEL_VERSION` in `train_model.py` and retrain. `scorer.py`
compares `feature_names` against the artifact and refuses to boot if you forget.
