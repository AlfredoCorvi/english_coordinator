"""Modelos del almacenamiento relacional, independientes de la interfaz."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LevelDecision:
    student_id: int
    target_period_id: int
    level_id: int
    actor_id: int
    reason: str = ""
