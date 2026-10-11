"""Privileged loader with a whitelisted Student context; no rollout code."""
from functools import cached_property
from pathlib import Path

from policytrace.data.manifests import ROOT, read_json, digest
from policytrace.evaluation.schema import task_set_hash, DATASET_REVISION, ENVIRONMENT_SHA
from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
from policytrace.stage0.db_adapter import load_retail_db, make_retail_env


class RLTaskPool:
    def __init__(self, manifest_path, root=ROOT):
        self.root = Path(root)
        self.manifest = read_json(manifest_path)
        if self.manifest['dataset_revision'] != DATASET_REVISION or self.manifest['environment_sha'] != ENVIRONMENT_SHA:
            raise ValueError('Pool provenance version mismatch')
        if task_set_hash(self.manifest['task_ids']) != self.manifest['task_set_sha256']:
            raise ValueError('Manifest Task hash mismatch')
        self.entries = {e['id']: e for e in self.manifest['entries']}
        if set(self.entries) != set(self.manifest['task_ids']): raise ValueError('Manifest entry mismatch')

    @cached_property
    def records(self):
        return {raw['id']: load_retail_task(raw, i) for i, raw in iter_retail_records(self.root/'data/raw')}

    def load(self, task_id):
        if task_id not in self.entries: raise ValueError('Task is outside selected pool')
        r = self.records[task_id]
        e = self.entries[task_id]
        if digest(r.task.model_dump(mode='json')) != e['task_payload_sha256']: raise ValueError('Task payload mismatch')
        s = load_retail_db(r.db_path, self.root/'data/raw')
        if s.file_sha256 != e['snapshot_sha256'] or r.db_path != e['db_path']: raise ValueError('Snapshot mismatch')
        return r, s

    def new_environment(self, task_id):
        r, s = self.load(task_id)
        return make_retail_env(r, s)

    def student_context(self, task_id):
        env = self.new_environment(task_id)
        return {'policy': env.get_policy(), 'tools': [t.openai_schema for t in env.get_tools()]}
