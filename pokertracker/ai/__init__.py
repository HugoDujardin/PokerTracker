"""Assistant d'analyse (coach IA)."""
from .coach import CoachConfig, CoachError, PokerCoach, build_hand_context, build_stats_context

__all__ = ["PokerCoach", "CoachConfig", "CoachError", "build_hand_context", "build_stats_context"]
