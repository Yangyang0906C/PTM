from .q_learner import QLearner
from .q_learner_mt_exp import QLearner as QLearnerMtExp


REGISTRY = {}
REGISTRY["q_learner"] = QLearner
REGISTRY["q_learner_mt_exp"] = QLearnerMtExp
