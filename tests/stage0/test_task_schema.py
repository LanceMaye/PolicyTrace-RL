from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from policytrace.stage0.task_loader import load_retail_task, iter_retail_records
from policytrace.stage0.db_adapter import load_retail_db, resolve_db_path


def test_string_and_dict_criteria(data_root):
    index, raw = next(iter_retail_records(data_root))
    original = deepcopy(raw)
    a = load_retail_task(raw, index)
    raw['evaluation_criteria'] = json.loads(raw['evaluation_criteria'])
    b = load_retail_task(raw, index)
    assert a.task == b.task
    assert a.task.id == original['id'] and a.db_path == original['db_path']
    assert a.source_index == index and a.environment_config == {'domain':'retail','solo_mode':False}
    assert isinstance(original['evaluation_criteria'], str)


@pytest.mark.parametrize('criteria', ['{bad', '[]', None, 42])
def test_invalid_criteria(data_root, criteria):
    _, raw = next(iter_retail_records(data_root))
    raw['evaluation_criteria'] = criteria
    with pytest.raises(ValueError, match='evaluation_criteria'):
        load_retail_task(raw)


@pytest.mark.parametrize('path', ['../escape.json','/tmp/a.json','C:/secret.json','C:secret.json',
                                  'folder/../../escape.json','folder\\escape.json','a.json:stream',''])
def test_unsafe_paths(data_root, path):
    with pytest.raises(ValueError):
        resolve_db_path(path, data_root)


def test_missing_and_invalid_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_retail_db('missing.json', tmp_path)
    (tmp_path/'invalid.json').write_text('{}')
    with pytest.raises(ValidationError):
        load_retail_db('invalid.json', tmp_path)
    (tmp_path/'invalid.json').write_text('{bad')
    with pytest.raises(ValidationError):
        load_retail_db('invalid.json', tmp_path)


def test_all_retail_schemas(records):
    assert len(records) == 563
    assert len({r.task.id for r in records}) == len(records)
    assert len({r.db_path for r in records}) == 4

