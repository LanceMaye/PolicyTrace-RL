"""Unexecuted plan templates. Resolve all run settings before schema validation."""
from policytrace.evaluation.schema import EvaluationPlan, DATASET_REVISION, ENVIRONMENT_SHA

REQUIRED = ('run_id', 'model_id', 'model_checkpoint', 'model_version', 'model_sampling',
            'simulator_model', 'simulator_version', 'simulator_config_id', 'simulator_sampling',
            'harness_version', 'max_steps', 'max_errors', 'max_context_tokens')


def plan_template(manifest, trials):
    return {'status': 'NOT_RUN_UNRESOLVED', 'required_configuration': list(REQUIRED),
            'plan': {'context': {'protocol_version': 'policytrace-eval-v1', 'purpose': 'benchmark',
                'task_set_id': manifest['name'], 'task_set_sha256': manifest['task_set_sha256'],
                'domain': 'retail', 'environment_sha': ENVIRONMENT_SHA, 'dataset_revision': DATASET_REVISION,
                **{k: None for k in REQUIRED}, 'unrecorded_fields': []},
                'task_ids': manifest['task_ids'], 'trial_ids': [f'trial_{i}' for i in range(trials)],
                'trials_per_task': trials, 'provenance': 'saved_real_episode'}}


def resolve_plan(template, configuration):
    missing = [k for k in REQUIRED if k not in configuration]
    if missing: raise ValueError('Unresolved run configuration: ' + ','.join(missing))
    plan = template['plan']
    context = dict(plan['context'])
    context.update(configuration)
    required_nonnull = {'run_id','model_id','model_sampling','simulator_model','simulator_config_id',
                        'simulator_sampling','harness_version','max_steps','max_errors'}
    if any(context[k] is None for k in required_nonnull): raise ValueError('Required run configuration is null')
    return EvaluationPlan.model_validate({**plan, 'context': context})
