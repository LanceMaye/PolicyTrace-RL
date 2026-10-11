"""Validated, isolated task snapshots; no fallback to the default database."""
import hashlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable

from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.environment import get_environment
from tau2.environment.environment import Environment
from tau2.utils import get_pydantic_hash

from .task_loader import RetailTask


def resolve_db_path(db_path: str, data_root: Path) -> Path:
    """Reject traversal, Windows drives/ADS, absolute paths and escaping symlinks."""
    if not db_path or '\\' in db_path or ':' in db_path or PureWindowsPath(db_path).drive:
        raise ValueError("db_path must be a dataset-relative POSIX path")
    rel = Path(db_path)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError("db_path must stay inside the dataset directory")
    root = data_root.resolve(strict=True)
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ValueError("db_path escapes the dataset directory")
    if path.suffix != '.json':
        raise ValueError("Retail snapshots must be JSON files")
    if not path.is_file():
        raise FileNotFoundError(f"Snapshot not found: {db_path}")
    return path


@dataclass(frozen=True)
class RetailSnapshot:
    db_path: str
    file_sha256: str
    content_hash: str
    db: RetailDB


def load_retail_db(db_path: str, data_root: Path) -> RetailSnapshot:
    path = resolve_db_path(db_path, data_root)
    payload = path.read_bytes()
    db = RetailDB.model_validate_json(payload)
    return RetailSnapshot(db_path, hashlib.sha256(payload).hexdigest(), get_pydantic_hash(db), db)


def snapshot_constructor(record: RetailTask, initial_db: RetailSnapshot) -> Callable[..., Environment]:
    """Freeze an independent baseline; every call constructs a new mutable database."""
    if record.db_path != initial_db.db_path:
        raise ValueError(f"{record.task.id}: snapshot path does not match task db_path")
    if get_pydantic_hash(initial_db.db) != initial_db.content_hash:
        raise ValueError("Snapshot object has been mutated; reload the original snapshot")
    baseline = initial_db.db.model_copy(deep=True)

    def constructor(solo_mode: bool = False) -> Environment:
        return get_environment(db=baseline.model_copy(deep=True), solo_mode=solo_mode)

    return constructor


def make_retail_env(record: RetailTask, initial_db: RetailSnapshot, *, initialize: bool = True) -> Environment:
    """Use initialize=False when the official Orchestrator will apply initial_state."""
    env = snapshot_constructor(record, initial_db)()
    state = record.task.initial_state
    if initialize:
        env.set_state(
            initialization_data=state.initialization_data if state else None,
            initialization_actions=state.initialization_actions if state else None,
            message_history=(state.message_history or []) if state else [],
        )
    return env

