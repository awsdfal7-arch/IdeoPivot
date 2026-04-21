from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    number: str
    stem: str
    options: str
    answer: str
    analysis: str
    question_type: str = ""
    choice_1: str = ""
    choice_2: str = ""
    choice_3: str = ""
    choice_4: str = ""
