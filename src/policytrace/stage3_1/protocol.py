"""Read-only preflight and immutable Dev-evidenced comparison protocol."""
import importlib.metadata as metadata
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from policytrace.data.manifests import ROOT, digest, file_hash, read_json
from policytrace.data.sft_tokenize import TOKENIZER_REVISION
from policytrace.policy import active_policy, verify_fork
from .assets import LOCK, private_path, exclusive_json, verify_assets, SMOKE_IDS
from .download import MODEL, verify_model


class UserConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model: Literal['deepseek-v4-pro'] = 'deepseek-v4-pro'
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: StrictInt = Field(default=512, gt=0, le=2048)
    max_payload_bytes: StrictInt = Field(default=65536, gt=0)
    max_requests: StrictInt = Field(default=2000, gt=0)
    timeout_seconds: float = Field(default=45, gt=0, le=120)
    budget_cny: float = Field(default=5, gt=0)
    input_cny_per_m: float | None = Field(default=None, gt=0)
    output_cny_per_m: float | None = Field(default=None, gt=0)
    price_verified_on: str | None = None


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    local_model_dir: str
    weight_revision: str | None = Field(default=None, pattern='^[0-9a-f]{40}$')
    seed: StrictInt = 42
    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    top_k: StrictInt = Field(default=0, ge=0)
    max_steps: StrictInt = Field(default=40, gt=0)
    max_errors: StrictInt = Field(default=3, gt=0)
    max_context_tokens: StrictInt = Field(default=16384, gt=0, le=32768)
    reserved_generation_tokens: StrictInt = Field(default=512, gt=0)
    max_episodes: StrictInt = Field(default=85, ge=3)
    max_calls: StrictInt = Field(default=4000, gt=0)
    max_seconds: float = Field(default=10800, gt=0)
    gpu_hourly_cny: float | None = Field(default=None, ge=0)
    user: UserConfig = Field(default_factory=UserConfig)

    @model_validator(mode='after')
    def context_limit(self):
        if self.reserved_generation_tokens >= self.max_context_tokens:
            raise ValueError('Generation reserve must fit inside total context budget')
        return self


def settings(path):
    return Settings.model_validate(read_json(path))


def versions():
    result = {}
    for name in ('torch','transformers','accelerate','huggingface-hub','tokenizers','tau2','litellm','httpx'):
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


def code_hash():
    paths = sorted(p for p in (ROOT/'src/policytrace').rglob('*.py') if '__pycache__' not in p.parts)
    paths += sorted((ROOT/'scripts').glob('stage3_1_*.py'))
    return digest({p.relative_to(ROOT).as_posix():file_hash(p) for p in paths})


def common_protocol(config, *, receipt=None):
    receipt = receipt or verify_model(config.local_model_dir, config.weight_revision)
    values = config.model_dump()
    values.pop('local_model_dir')  # Same bytes can live in different data-disk directories.
    fork = verify_fork()
    return {'version':'policytrace-common-real-v1','settings':values,
        'model_id':MODEL,'weight_receipt_sha256':digest(receipt),'weight_revision':receipt['weight_revision'],
        'tokenizer_revision':TOKENIZER_REVISION,'assets_lock_sha256':file_hash(ROOT/LOCK),
        'policy':active_policy(),'fork':fork,
        'code_sha256':code_hash(),'dependencies':versions(),'projection':'identity-v0',
        'strict_communication':True,'batch_size':1,'dtype':'bfloat16','attention':'sdpa',
        'cross_decision_kv_reuse':False,'student_eos':[151645], 'pass1_trials':1,
        'official_r0':'unchanged Stage 1 adapter; DB+COMM', 'logprobs':'not_requested'}


def preflight(config, *, check_gpu=False):
    blocked = []
    data = verify_assets()
    if data['status'] != 'PASS': blocked.append('BLOCKED_DATA')
    try:
        fork = verify_fork()
    except Exception:
        fork = None; blocked.append('BLOCKED_POLICY')
    receipt = None
    try:
        if config.weight_revision is None: raise ValueError('Weight revision not set')
        receipt = verify_model(config.local_model_dir, config.weight_revision)
    except (OSError, ValueError, KeyError):
        blocked.append('BLOCKED_MODEL')
    key_present = bool(os.environ.get('DEEPSEEK_API_KEY','').strip())
    if not key_present: blocked.append('BLOCKED_API_KEY')
    if not config.user.input_cny_per_m or not config.user.output_cny_per_m or not config.user.price_verified_on:
        blocked.append('BLOCKED_PRICE')
    deps = versions()
    gpu = {'checked':False,'cuda_available':None,'bf16_supported':None}
    if not deps['torch'] or not deps['transformers'] or not deps['accelerate']:
        blocked.append('BLOCKED_ENV')
    elif check_gpu:
        import torch
        gpu = {'checked':True,'cuda_available':torch.cuda.is_available(),
               'bf16_supported':torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False}
        if not gpu['cuda_available'] or not gpu['bf16_supported']: blocked.append('BLOCKED_ENV')
    else:
        blocked.append('BLOCKED_ENV_GPU_UNVERIFIED')
    return {'status':'READY_FOR_USER_RUN' if not blocked else 'BLOCKED', 'blockers':blocked,
            'data':data, 'fork':fork,'dependencies':deps,'gpu':gpu,'api_key_present':key_present,
            'model_verified':receipt is not None,'weights_loaded':False,'paid_api_calls':0,
            'test_bodies_deserialized':0}


def freeze(config, smoke_dir, output, *, confirm_cost=False):
    from .summary import summarize
    smoke_dir = private_path(smoke_dir)
    evidence = read_json(smoke_dir/'run_manifest.json')
    summary = summarize(smoke_dir)
    expected = common_protocol(config)
    if evidence['mode'] != 'dev-smoke' or evidence['protocol'] != expected:
        raise ValueError('BLOCKED_SMOKE_PROTOCOL_MISMATCH')
    if tuple(evidence['plan']['task_ids']) != SMOKE_IDS or evidence['source'] != 'real':
        raise ValueError('BLOCKED_REAL_DEV_SMOKE')
    if summary['coverage']['started_trials'] != len(SMOKE_IDS) or summary['coverage']['scored_trials'] != len(SMOKE_IDS):
        raise ValueError('BLOCKED_INCOMPLETE_DEV_SMOKE')
    if not summary['integrity']['all_real_tokens'] or not summary['integrity']['all_real_users'] or not summary['integrity']['native_serialization_verified'] or not summary['integrity']['raw_snapshots_unchanged']:
        raise ValueError('BLOCKED_REAL_TOKEN_EVIDENCE')
    projection = project_cost(summary, config)
    if projection['api_estimate_cny'] is not None and projection['api_estimate_cny'] > config.user.budget_cny:
        raise ValueError('BLOCKED_PROJECTED_API_BUDGET')
    if not confirm_cost:
        raise ValueError('BLOCKED_COST_CONFIRMATION: inspect measured Dev projection, then supply --confirm-cost')
    path = private_path(output)
    exclusive_json(path, {'protocol':expected,'protocol_sha256':digest(expected),
        'smoke_dir':smoke_dir.relative_to(ROOT).as_posix(),'smoke_manifest_sha256':file_hash(smoke_dir/'run_manifest.json'),
        'smoke_evidence_sha256':summary['integrity']['evidence_sha256'],'cost_projection':projection,'cost_confirmed_by_user':True})
    return {'status':'PROTOCOL_FROZEN','sha256':file_hash(path),'cost_projection':projection}


def verify_frozen_protocol(config, path):
    from .summary import summarize
    frozen = read_json(private_path(path))
    expected = common_protocol(config)
    if frozen.get('protocol_sha256') != digest(expected) or frozen.get('protocol') != expected or not frozen.get('cost_confirmed_by_user'):
        raise ValueError('BLOCKED_PROTOCOL_MISMATCH')
    smoke = private_path(ROOT/frozen['smoke_dir'])
    manifest = read_json(smoke/'run_manifest.json')
    summary = summarize(smoke)
    if file_hash(smoke/'run_manifest.json') != frozen['smoke_manifest_sha256'] or summary['integrity']['evidence_sha256'] != frozen['smoke_evidence_sha256']:
        raise ValueError('BLOCKED_SMOKE_EVIDENCE_CHANGED')
    if manifest['mode'] != 'dev-smoke' or manifest['source'] != 'real' or manifest['protocol'] != expected or tuple(manifest['plan']['task_ids']) != SMOKE_IDS:
        raise ValueError('BLOCKED_REAL_DEV_SMOKE')
    if summary['coverage']['scored_trials'] != len(SMOKE_IDS) or not all(summary['integrity'][name] for name in ('all_real_tokens','all_real_users','native_serialization_verified','raw_snapshots_unchanged')):
        raise ValueError('BLOCKED_INCOMPLETE_DEV_SMOKE')
    return expected


def project_cost(summary, config):
    n = summary['coverage']['started_trials']
    costs = summary['api_costs']['groups']
    api = next((x['total'] for x in costs if x['role']=='user' and x['currency']=='CNY'),None)
    duration = summary['duration_seconds']['total']
    return {'basis':'linear projection from real Dev; exclude setup, idle time and long-tail variance',
        'api_estimate_cny':api/n*85 if api is not None and n else None,
        'active_episode_seconds':duration/n*85 if duration is not None and n else None,
        'gpu_active_estimate_cny':duration/n*85/3600*config.gpu_hourly_cny if duration is not None and n and config.gpu_hourly_cny is not None else None,
        'gpu_idle_and_setup_cost_cny':None,'actual_provider_bill_cny':None}
