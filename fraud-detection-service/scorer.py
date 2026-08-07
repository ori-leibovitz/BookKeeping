"""Load the trained Isolation Forest and score transactions.

The artifact and its metadata are validated at construction time. Any mismatch
between what the model was trained on and what this process would feed it is a
hard failure at boot, never a silently wrong score in production.
"""

import json
import os

import joblib
import sklearn

from features import FEATURE_NAMES, extract_features


class ModelArtifactError(RuntimeError):
    """The artifact on disk does not match this build of the service."""


class FraudScorer:
    def __init__(self, model_path, threshold_override=None):
        meta_path = os.path.join(os.path.dirname(model_path), 'model_meta.json')

        if not os.path.exists(model_path):
            raise ModelArtifactError(
                f"No model at {model_path}. Run ml-training/train_model.py first."
            )
        if not os.path.exists(meta_path):
            raise ModelArtifactError(f"No metadata at {meta_path}")

        with open(meta_path, encoding='utf-8') as fh:
            meta = json.load(fh)

        # joblib pickles are version-sensitive: loading under a different
        # scikit-learn can deserialize a subtly broken estimator that still
        # produces plausible-looking numbers. Refuse rather than risk it.
        trained_with = meta['sklearn_version']
        if trained_with != sklearn.__version__:
            raise ModelArtifactError(
                f"Model was trained with scikit-learn {trained_with} but this "
                f"service runs {sklearn.__version__}. Pin them identically in "
                f"fraud-detection-service/requirements.txt and "
                f"ml-training/requirements.txt, then retrain."
            )

        # Catches the case where features.py was edited without retraining.
        if meta['feature_names'] != FEATURE_NAMES:
            raise ModelArtifactError(
                f"features.py has changed since the model was trained.\n"
                f"  trained on: {meta['feature_names']}\n"
                f"  current:    {FEATURE_NAMES}\n"
                f"Retrain with ml-training/train_model.py."
            )

        self.model = joblib.load(model_path)
        self.model_version = meta['model_version']
        self.trained_at = meta['trained_at']
        self._score_min = meta['score_min']
        self._score_max = meta['score_max']
        self._span = self._score_max - self._score_min
        if self._span <= 0:
            raise ModelArtifactError(
                f"Degenerate score range in {meta_path}: "
                f"[{self._score_min}, {self._score_max}]"
            )

        self.threshold = (
            float(threshold_override)
            if threshold_override is not None
            else float(meta['threshold'])
        )

    def score(self, txn):
        """Return (score, is_flagged, features).

        score is in [0, 1] where 1 is most suspicious. Raises ValueError on a
        malformed event, which the caller counts as a scoring error.
        """
        vector = extract_features(txn)

        # decision_function is positive for inliers; negate so bigger == worse,
        # then rescale using the bounds frozen at training time.
        raw = -float(self.model.decision_function([vector])[0])
        score = (raw - self._score_min) / self._span
        score = min(1.0, max(0.0, score))

        return score, score >= self.threshold, dict(zip(FEATURE_NAMES, vector))
