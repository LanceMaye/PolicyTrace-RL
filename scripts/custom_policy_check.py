"""Offline re-acceptance for the custom policy, preserving every historical report."""
from datetime import datetime, timezone
import platform
import subprocess
import sys
import time

from policytrace.data.manifests import ROOT, file_hash, read_json, write_json
from policytrace.policy import verify_fork
from stage3_0_check import test_summary

AUTHORIZED_CHANGES = {
    'external/tau2-bench/data/tau2/domains/retail/policy.md', 'configs/data/sft_main_view.json',
    'src/policytrace/data/sft_policy_view.py', 'src/policytrace/harness/verification.py',
    'src/policytrace/harness/agent_adapter.py', 'src/policytrace/harness/runner.py',
    'src/policytrace/harness/regression_scope.py', 'src/policytrace/harness/__init__.py',
    'tests/stage2/test_policy_view.py', 'tests/stage3_0/test_harness.py',
    'docs/stage3_1_handoff.md', 'docs/harness_protocol.md', 'docs/sft_policy_main_view.md',
    'README.md', 'scripts/stage0_bootstrap.py',
}


def verify_transition():
    private=ROOT/'data/private/policy_transition_v2'
    before=read_json(private/'before.json')['files']
    changed=[name for name,sha in before.items() if not (ROOT/name).is_file() or file_hash(ROOT/name)!=sha]
    unexpected=sorted(set(changed)-AUTHORIZED_CHANGES)
    backups={
        'external/tau2-bench/data/tau2/domains/retail/policy.md':'configs/policy/backups/retail.e33e9511.original.md',
        'configs/data/sft_main_view.json':'configs/data/backups/sft_main_view.policy_main_v1.json',
    }
    for name in changed:
        if name in AUTHORIZED_CHANGES:
            backup=ROOT/backups[name] if name in backups else private/'original_files'/name
            if not backup.is_file() or file_hash(backup)!=before[name]:
                unexpected.append('missing_or_changed_original_backup:'+name)
    return {'before_file_count':len(before),'authorized_changed_files':sorted(set(changed)&AUTHORIZED_CHANGES),
        'unexpected_changes':unexpected,'unchanged_original_files':len(before)-len(changed),
        'historical_reports_unchanged':all(name not in changed for name in before if name.startswith('reports/')),
        'historical_report_count':sum(name.startswith('reports/') for name in before),
        'baseline_sha256':file_hash(private/'before.json')}


def main():
    private=ROOT/'data/private/policy_transition_v2/acceptance'
    report=ROOT/'reports/policy_transition_v2'
    private.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True)
    initial=verify_transition()
    if initial['unexpected_changes']:raise ValueError('Unexpected historical file change')
    fork=verify_fork()
    config=read_json(ROOT/'configs/data/sft_main_view.json')
    manifest=read_json(ROOT/config['manifest'])
    if config!=read_json(ROOT/'configs/data/sft_mixed_only_v2.json'):
        raise ValueError('Wrong active SFT configuration')
    commands=[];tests={}
    specs=[('harness',[sys.executable,'-X','utf8','-m','pytest','tests/stage3_0','-q',
                         '--basetemp=data/private/policy_transition_v2/acceptance/harness_tmp',
                         '--junitxml=data/private/policy_transition_v2/acceptance/harness.xml']),
           ('regression',[sys.executable,'-X','utf8','-m','pytest','-p','policytrace.harness.regression_scope',
                         'tests/stage0','tests/stage1','tests/stage2','tests/multi_tool_compatibility','-q',
                         '--policytrace-scope-report=reports/policy_transition_v2/regression_scope.json',
                         '--basetemp=data/private/policy_transition_v2/acceptance/regression_tmp',
                         '--junitxml=data/private/policy_transition_v2/acceptance/regression.xml'])]
    code_paths=list((ROOT/'src/policytrace').rglob('*.py'))+list((ROOT/'tests').rglob('*.py'))
    code_paths+=list((ROOT/'scripts').glob('*.py'))+list((ROOT/'configs').rglob('*'))
    hashes={p.relative_to(ROOT).as_posix():file_hash(p) for p in code_paths if p.is_file() and '__pycache__' not in p.parts}
    for name,argv in specs:
        start=time.perf_counter();log=private/f'{name}.log'
        print('Running '+name,flush=True)
        with log.open('w',encoding='utf-8') as stream:
            result=subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        command={'name':name,'command':argv,'exit_code':result.returncode,'seconds':round(time.perf_counter()-start,3),
                 'private_log':log.relative_to(ROOT).as_posix(),'log_sha256':file_hash(log)}
        commands.append(command)
        tests[name]=test_summary(private/f'{name}.xml',report/f'{name}.xml')
        print({k:command[k] for k in ('name','exit_code','seconds')},flush=True)
        if result.returncode:
            write_json(report/'check_results.json',{'status':'PARTIAL','commands':commands,'tests':tests})
            raise SystemExit(result.returncode)
    immutable=verify_transition()
    changed=[name for name,sha in hashes.items() if file_hash(ROOT/name)!=sha]
    status='PASS_OFFLINE' if not immutable['unexpected_changes'] and not changed else 'FAIL'
    output={'status':status,'executed_at':datetime.now(timezone.utc).isoformat(),
        'environment':{'platform':platform.platform(),'python':platform.python_version(),'gpu_used':False},
        'commands':commands,'tests':tests,'fork':verify_fork(),'historical_integrity':immutable,
        'tested_code':hashes,'tested_code_changed':changed,'scope':read_json(report/'regression_scope.json'),
        'data_results':read_json(report/'data_results.json'),'manifest_sha256':file_hash(ROOT/config['manifest']),
        'active_config_sha256':file_hash(ROOT/'configs/data/sft_main_view.json'),
        'policy_version':manifest['policy_version'],'policy_sha256':manifest['policy_sha256'],
        'paid_api_calls':0,'real_student_forward':False,'weights_downloaded':False,'gpu_rented':False,
        'base_baseline_executed':False,'training_started':False,'stage3_1_started':False}
    write_json(report/'check_results.json',output)
    print({'status':status,'tests':{k:v['tests'] for k,v in tests.items()},'historical_reports_unchanged':immutable['historical_reports_unchanged']},flush=True)
    if status!='PASS_OFFLINE':raise SystemExit(1)


if __name__=='__main__':main()
