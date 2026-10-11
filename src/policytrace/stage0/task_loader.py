"""Parse raw RL JSONL without Arrow schema inference."""
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tau2.data_model.tasks import Task


@dataclass(frozen=True)
class RetailTask:
    task: Task
    db_path: str
    source_index: int | None
    environment_config: dict[str, Any]


def load_retail_task(raw_record: dict[str, Any], source_index: int | None = None) -> RetailTask:
    """Preserve task ID and private fields; never turn these into an agent prompt."""
    raw = deepcopy(raw_record)
    if not isinstance(raw.get("id"), str) or not raw["id"].startswith("retail_"):
        raise ValueError("Expected an AReaL retail_ task ID")
    if not isinstance(raw.get("db_path"), str) or not raw["db_path"]:
        raise ValueError(f"{raw['id']}: db_path is required")
    criteria = raw.get("evaluation_criteria")
    if isinstance(criteria, str):
        try:
            criteria = json.loads(criteria)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{raw['id']}: invalid evaluation_criteria JSON") from exc
    if not isinstance(criteria, dict):
        raise ValueError(f"{raw['id']}: evaluation_criteria must be an object or JSON object string")
    raw["evaluation_criteria"] = criteria
    task = Task.model_validate(raw)
    instructions = task.user_scenario.instructions
    if not isinstance(instructions, str) and instructions.domain != "retail":
        raise ValueError(f"{task.id}: domain mismatch")
    return RetailTask(task, raw['db_path'], source_index, {"domain": "retail", "solo_mode": False})


def iter_retail_records(data_root: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with (data_root / "tau2_rl_train.jsonl").open(encoding="utf-8") as stream:
        for index, line in enumerate(stream, start=1):
            record = json.loads(line)
            if record.get("id", "").startswith("retail_"):
                yield index, record

