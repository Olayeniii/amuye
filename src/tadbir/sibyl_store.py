from __future__ import annotations

from pathlib import Path
from typing import Any

from sibyl_memory_client import MemoryClient

from .domain import LearnedLesson


LESSON_CATEGORY = "tadbir_operational_lesson"


class SibylStore:
    """The only persistent operational-memory store used by Tadbir."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(Path(database_path).resolve())
        self.client = MemoryClient.local(self.database_path)

    def write_execution_history(self, execution: dict[str, Any]) -> str:
        event_ref = execution["executionId"]
        self.client.write_event(
            evaluated={
                "outcome": execution["outcome"],
                "finding": "later specialist purchases lacked prerequisite evidence and were unnecessary",
            },
            acted=["commissioned viability, risk synthesis, and security work up front"],
            forward=["purchase viability evidence before deeper specialist work"],
            extra={"kind": "tadbir_execution", "executionRef": event_ref, "execution": execution},
        )
        return event_ref

    def write_lesson(self, lesson: LearnedLesson) -> str:
        self.client.set_entity(LESSON_CATEGORY, lesson.id, lesson.to_dict())
        return lesson.id

    def retrieve_lessons(self, request_terms: str) -> list[LearnedLesson]:
        hits = self.client.search_entities(request_terms, limit=20)
        lessons: list[LearnedLesson] = []
        for hit in hits:
            if hit.get("category") != LESSON_CATEGORY:
                continue
            lessons.append(LearnedLesson(**hit["body"]))
        return lessons
