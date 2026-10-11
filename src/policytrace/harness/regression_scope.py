"""Pytest-only Dev boundary for historical regression, without changing old files.

Historical conftest eagerly builds all 563 Tasks. Under the Stage 3_0 boundary,
its iterator is restricted to already exposed Dev bodies; tests needing the
full audit/features or Train integration are explicitly deselected, not passed.
"""
import json
import re
from pathlib import Path

import pytest

from policytrace.data.manifests import ROOT, read_json

OMIT = {
    'test_all_retail_schemas': 'full raw Task body audit includes frozen Test',
    'test_train_dev_initialization_isolation_and_official_scoring': 'historical pool selects arbitrary Train/Dev reference fixture',
    'test_out_of_pool_and_changed_snapshot_are_rejected': 'historical corrupted pool selects Train Task',
    'test_pinned_sources_full_counts_and_no_schema_error': 'prepared fixture loads full frozen Test features',
    'test_actual_overlap_claims_are_conservative': 'prepared fixture loads full frozen Test features',
    'test_full_group_isolation_and_exposed_tasks': 'prepared fixture loads full frozen Test features',
    'test_seeded_global_assignment_reproduces_manifests': 'regroups Test using full features; hashes checked separately',
    'test_sft_quality_filter_does_not_reduce_experts_for_rl_effect': 'shared prepared fixture also loads Test features; SFT hashes and mask tests remain',
    'test_actual_external_candidate_count_and_honest_status': 'external Test audit artifact inspection deferred'}


def pytest_addoption(parser):
    parser.addoption('--policytrace-scope-report',default='reports/stage3_0/regression_scope.json',
                     help='Save scope evidence separately for a versioned acceptance run')


def pytest_configure(config):
    from policytrace.stage0 import task_loader, reference_check
    # ID-only manifests and already published IDs; no Test entry payloads opened.
    exposed = set(read_json(ROOT/'data/private/stage2/known_exposed.json'))
    dev = set(read_json(ROOT/'data/splits/stage2/rl_dev.json')['task_ids'])
    if not exposed <= dev:
        raise ValueError('Historical fixtures must all belong to frozen Dev')
    ordered = [r['task_id'] for r in read_json(ROOT/'reports/stage0/smoke_results.json')['results']]
    def selected_iterator(data_root):
        with (Path(data_root)/'tau2_rl_train.jsonl').open('rb') as stream:
            for index,line in enumerate(stream,1):
                match = re.match(rb'\s*\{\s*"id"\s*:\s*"([^"]+)"',line)
                if match is None:
                    raise ValueError('Unexpected raw ID envelope')
                if match[1].decode('utf8') in exposed:
                    yield index,json.loads(line)
    def original_selection(records,seed=42,limit=8):
        by_id = {r.task.id:r for r in records}
        return [by_id[tid] for tid in ordered[:limit]]
    task_loader.iter_retail_records = selected_iterator
    reference_check.select_tasks = original_selection
    config._policytrace_deselected = []


def pytest_collection_modifyitems(config,items):
    selected,omitted = [],[]
    for item in items:
        name = item.originalname or item.name
        if name in OMIT:
            omitted.append(item)
            config._policytrace_deselected.append({'nodeid':item.nodeid,'reason':OMIT[name]})
        else:
            selected.append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=omitted)


def pytest_sessionfinish(session,exitstatus):
    from policytrace.data.manifests import write_json
    write_json(ROOT/session.config.getoption('--policytrace-scope-report'),{
        'test_only_fixture_boundary':'raw iterator limited to existing exposed Dev; original Stage 0 selection order restored',
        'deselected':session.config._policytrace_deselected,'exit_code':int(exitstatus)})
