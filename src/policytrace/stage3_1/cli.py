"""Explicit user-run entry points. Help/env-check/dry-run never instantiate clients."""
import argparse
import json
import os
from pathlib import Path

from policytrace.data.manifests import ROOT, digest, file_hash, read_json
from .assets import SPLITS, SMOKE_IDS, RuntimeTaskPool, exclusive_json, private_path
from .protocol import settings, preflight, common_protocol, freeze, verify_frozen_protocol
from .summary import summarize


def run(args, config):
    if args.command == 'e0-test' and (args.split != 'test' or not args.confirm_frozen_test):
        return {'status':'BLOCKED_TEST_CONFIRMATION','test_bodies_deserialized':0}
    if args.command == 'dev-smoke' and args.split != 'dev':
        return {'status':'BLOCKED_SPLIT','test_bodies_deserialized':0}
    check = preflight(config,check_gpu=args.execute and not args.dry_run)
    if args.output:
        output_preview = private_path(args.output)
        if output_preview.exists(): check['blockers'].append('BLOCKED_EXISTING_RUN_NO_RESUME')
    protocol = None
    if args.command == 'e0-test':
        if not args.protocol or not Path(args.protocol).is_file():
            check['blockers'].append('BLOCKED_PROTOCOL')
        elif not check['blockers']:
            protocol = verify_frozen_protocol(config,args.protocol)
    if args.dry_run or not args.execute:
        check.update(status='DRY_RUN' if args.dry_run else 'PREVIEW_ONLY',mode=args.command,
            planned_tasks=85 if args.command=='e0-test' else len(SMOKE_IDS),actual_episodes=0,
            clients_instantiated=False,paid_api_calls=0,test_bodies_deserialized=0)
        return check
    if not args.confirm_paid_api:
        check['blockers'].append('BLOCKED_PAID_API_CONFIRMATION')
    if check['blockers']:
        check['status'] = 'BLOCKED'; return check
    if not args.output:
        return {'status':'BLOCKED_OUTPUT'}
    output = private_path(args.output)
    if output.exists():
        return {'status':'BLOCKED_EXISTING_RUN_NO_RESUME'}
    # Read manifest IDs only. Hidden Test body loading begins inside run_episode after all gates.
    ids = tuple(read_json(ROOT/SPLITS[args.split])['task_ids']) if args.command=='e0-test' else SMOKE_IDS
    if len(ids)>config.max_episodes:
        return {'status':'BLOCKED_EPISODE_CAP'}
    protocol = protocol or common_protocol(config)
    from .runner import make_plan, run_episode
    plan = make_plan(config,protocol,ids,args.run_id,mode=args.command)
    output.mkdir(parents=True,exist_ok=False)
    exclusive_json(output/'run_manifest.json',{'mode':args.command,'source':'real','protocol':protocol,
        'protocol_sha256':digest(protocol),'plan':plan.model_dump(mode='json'),'resume':'unsupported; started slots never retried'})
    from loguru import logger
    logger.remove()
    logger.add(output/'native.log',level='DEBUG')  # Task/prompt data never go to terminal.
    from policytrace.data.sft_tokenize import QwenTokenizer
    from .student import TransformersQwenModelClient
    from .deepseek import DeepSeekProvider, DeepSeekUserSimulator
    from .budget import RunBudget, BudgetedStudent
    provider = None
    try:
        budget = RunBudget(config.max_calls,config.max_seconds)
        tokenizer = QwenTokenizer()
        client = BudgetedStudent(TransformersQwenModelClient(config.local_model_dir,tokenizer,
            weight_revision=config.weight_revision,temperature=config.temperature,top_p=config.top_p,top_k=config.top_k),budget)
        provider = DeepSeekProvider(os.environ.get('DEEPSEEK_API_KEY',''),output/'api_ledger.json',
                                    config=config.user.model_dump(),budget=budget)
        pool = RuntimeTaskPool(args.split,ids,confirmed_test=args.confirm_frozen_test)
        for task_id in ids:
            budget.check()
            episode, interrupted = run_episode(pool,task_id,output/'episodes'/task_id,plan,config,tokenizer,client,
                lambda instructions:DeepSeekUserSimulator(instructions,provider))
            if interrupted or episode.execution_status!='completed' or episode.scoring_status!='scored':
                break
        result = summarize(output)
        exclusive_json(output/'summary.json',result)
        return result
    except BaseException as exc:
        exclusive_json(output/'run_failure.json',{'type':type(exc).__name__,'code':getattr(exc,'code','run_failure')})
        result = summarize(output)
        exclusive_json(output/'summary.json',result)
        result['run_failure'] = getattr(exc,'code','run_failure')
        return result
    finally:
        if provider: provider.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Stage 3_1 user-operated preparation and real-run gates')
    sub = parser.add_subparsers(dest='command',required=True)
    env = sub.add_parser('env-check'); env.add_argument('--config',required=True); env.add_argument('--check-gpu',action='store_true')
    for name in ('dev-smoke','e0-test'):
        p = sub.add_parser(name)
        p.add_argument('--config',required=True);p.add_argument('--split',choices=['dev','test'],required=True)
        p.add_argument('--dry-run',action='store_true');p.add_argument('--execute',action='store_true')
        p.add_argument('--confirm-frozen-test',action='store_true');p.add_argument('--confirm-paid-api',action='store_true')
        p.add_argument('--protocol');p.add_argument('--output');p.add_argument('--run-id',default=name)
    p = sub.add_parser('freeze-protocol');p.add_argument('--config',required=True);p.add_argument('--smoke-dir',required=True)
    p.add_argument('--output',required=True);p.add_argument('--confirm-cost',action='store_true')
    p = sub.add_parser('summarize');p.add_argument('--run-dir',required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'summarize': result = summarize(args.run_dir)
        elif args.command == 'env-check': result = preflight(settings(args.config),check_gpu=args.check_gpu)
        elif args.command == 'freeze-protocol': result = freeze(settings(args.config),args.smoke_dir,args.output,confirm_cost=args.confirm_cost)
        else: result = run(args,settings(args.config))
    except (OSError,ValueError,KeyError) as exc:
        # Do not dump provider payloads or settings; report only a recognized gate or type.
        code = str(exc).split(':')[0] if str(exc).startswith('BLOCKED_') else type(exc).__name__
        result = {'status':'BLOCKED','reason':code,'paid_api_calls':0,'weights_loaded':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    status = result.get('status')
    return 0 if status in ('PASS','DRY_RUN','PREVIEW_ONLY','READY_FOR_USER_RUN','PROTOCOL_FROZEN','complete') else 2


if __name__ == '__main__':
    raise SystemExit(main())
