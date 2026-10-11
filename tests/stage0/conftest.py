from pathlib import Path
import socket

import pytest

from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
from policytrace.stage0.db_adapter import load_retail_db
from policytrace.stage0.reference_check import select_tasks


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Stage 0 tests must not access the network or paid APIs')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.fixture(scope='session')
def data_root():
    return Path(__file__).resolve().parents[2] / 'data/raw'


@pytest.fixture(scope='session')
def records(data_root):
    return [load_retail_task(raw, i) for i, raw in iter_retail_records(data_root)]


@pytest.fixture(scope='session')
def selected(records):
    return select_tasks(records, seed=42, limit=8)


@pytest.fixture(scope='session')
def snapshots(records, data_root):
    return {path:load_retail_db(path, data_root) for path in sorted({r.db_path for r in records})}

