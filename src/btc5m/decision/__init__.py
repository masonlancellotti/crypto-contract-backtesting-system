"""Decision layer: turn calibrated probabilities + executable prices into
gated trade candidates with reason codes. The model never trades directly — it
produces probabilities; this layer produces decisions; execution is separate.
"""

from .decision_layer import Decision, DecisionConfig, evaluate_candidate, candidate_message

__all__ = ["Decision", "DecisionConfig", "evaluate_candidate", "candidate_message"]
