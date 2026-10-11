"""Offline acceptance only. New private logs and sanitized public test results."""
from datetime import datetime, timezone
import subprocess
import sys
import time
from uuid import uuid4

from policytrace.data.manifests import ROOT, file_hash, read_json, write_json
from policytrace.policy import verify_fork
from stage3_0_check import test_summary


def historical_integrity():
    before = read_json(ROOT/'data/private/stage3_1/before.json')['files']
    allowed = {'src/policytrace/harness/model_client.py','src/policytrace/harness/agent_adapter.py'}
    changed = [name for name,sha in before.items() if not (ROOT/name).is_file() or file_hash(ROOT/name)!=sha]
    return {'before_count':len(before),'changed':changed,'unexpected':sorted(set(changed)-allowed),
        'historical_reports_unchanged':not any(name.startswith('reports/') for name in changed),
        'raw_db_split_tokenizer_unchanged':not any(name.startswith(('data/raw/','data/splits/','data/tokenizers/','data/processed/')) for name in changed),
        'historical_api_ledgers_unchanged':not any('ledger' in name for name in changed)}


def main():
    folder = ROOT/'data/private/stage3_1/acceptance'/uuid4().hex
    folder.mkdir(parents=True)
    report = ROOT/'reports/stage3_1';report.mkdir(parents=True,exist_ok=True)
    suites = [('offline',['tests/stage3_1']),('harness',['tests/stage3_0']),
        ('regression',['-p','policytrace.harness.regression_scope','tests/stage0','tests/stage1','tests/stage2',
                       'tests/multi_tool_compatibility','--policytrace-scope-report=reports/stage3_1/regression_scope.json'])]
    tests, commands = {}, []
    for name, targets in suites:
        argv = [sys.executable,'-X','utf8','-m','pytest',*targets,'-q',f'--basetemp={folder/name}',f'--junitxml={folder/name}.xml']
        start = time.perf_counter()
        with (folder/f'{name}.log').open('w',encoding='utf-8') as log:
            result = subprocess.run(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        command = {'name':name,'command':argv,'exit_code':result.returncode,'seconds':round(time.perf_counter()-start,3),
                   'private_log':(folder/f'{name}.log').relative_to(ROOT).as_posix(),'log_sha256':file_hash(folder/f'{name}.log')}
        commands.append(command)
        tests[name] = test_summary(folder/f'{name}.xml',report/f'{name}.xml')
        print({k:command[k] for k in ('name','exit_code','seconds')},flush=True)
        if result.returncode: break
    integrity = historical_integrity()
    passed = len(commands)==3 and all(c['exit_code']==0 for c in commands) and not integrity['unexpected']
    write_json(report/'check_results.json',{'status':'PASS_OFFLINE' if passed else 'FAIL','executed_at':datetime.now(timezone.utc).isoformat(),
        'commands':commands,'tests':tests,'historical_integrity':integrity,'fork':verify_fork(),
        'paid_api_calls':0,'weights_downloaded':False,'real_student_forward':False,'gpu_used':False,'test_bodies_deserialized':0,
        'git_commit_or_push':False,'ssh_connected':False,'real_e0_executed':False})
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
