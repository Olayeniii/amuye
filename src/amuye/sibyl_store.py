from __future__ import annotations

from pathlib import Path
from typing import Any

from sibyl_memory_client import MemoryClient, NotFoundError

from .domain import LearnedLesson


LESSON_CATEGORY = "amuye_operational_lesson"


class SibylStore:
    """The only persistent operational-memory store used by Amúyẹ."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(Path(database_path).resolve())
        self.client = MemoryClient.local(self.database_path)

    def write_execution_history(
        self,
        execution: dict[str, Any],
        *,
        evaluation: dict[str, Any] | None = None,
    ) -> str:
        application_execution_id = execution["executionId"]
        event_ref = self.client.write_event(
            evaluated=evaluation or {
                "outcome": execution["outcome"],
                "finding": "later specialist purchases lacked prerequisite evidence and were unnecessary",
            },
            acted=["commissioned viability, risk synthesis, and security work up front"],
            forward=["purchase viability evidence before deeper specialist work"],
            extra={
                "kind": "amuye_execution",
                "applicationExecutionId": application_execution_id,
                "execution": execution,
            },
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

    def get_lesson(self, lesson_id: str) -> LearnedLesson | None:
        try:
            entity = self.client.get_entity(LESSON_CATEGORY, lesson_id)
        except NotFoundError:
            return None
        return LearnedLesson(**entity["body"])

    def execution_event_exists(self, event_id: str) -> bool:
        return any(event["id"] == event_id for event in self.client.read_events(limit=1000))

    def get_execution_event(self, event_id: str) -> dict[str, Any] | None:
        return next(
            (event for event in self.client.read_events(limit=1000)
             if event["id"] == event_id),
            None,
        )
