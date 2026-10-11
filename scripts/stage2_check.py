"""Run the full CPU pipeline, offline tests and bounded Stage 0/1 regression."""
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from policytrace.data.manifests import ROOT, file_hash, read_json, write_json, verify_sources
from policytrace.evaluation.schema import ENVIRONMENT_SHA

OFFLINE_BOOTSTRAP = '''import socket,runpy,sys
def denied(*args,**kwargs):
    raise RuntimeError("Stage 2 verification forbids network requests")
socket.socket.connect=denied
socket.socket.connect_ex=denied
socket.create_connection=denied
path=sys.argv.pop(1)
sys.argv[0]=path
runpy.run_path(path,run_name="__main__")
'''


def main():
    private=ROOT/'data/private/stage2'; private.mkdir(parents=True,exist_ok=True)
    reports=ROOT/'reports/stage2'; reports.mkdir(parents=True,exist_ok=True)
    before=verify_sources()
    ledger=ROOT/'data/private/stage0/deepseek/cost_ledger.json'; ledger_before=file_hash(ledger)
    code_paths=sorted([*ROOT.glob('src/policytrace/data/*.py'),*ROOT.glob('scripts/stage2_*.py'),*ROOT.glob('tests/stage2/*.py'),
                       *ROOT.glob('configs/data/*.yaml'),ROOT/'pyproject.toml',ROOT/'.gitignore'])
    code_before={p.relative_to(ROOT).as_posix():file_hash(p) for p in code_paths}
    stages=[]
    env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8';env['LITELLM_LOCAL_MODEL_COST_MAP']='True'
    commands=[('full_audit','scripts/stage2_audit.py'),('global_split','scripts/stage2_split.py'),
              ('sft_preprocess','scripts/stage2_prepare_sft.py'),('external_audit','scripts/stage2_external_audit.py')]
    for name,script in commands:
        print(json.dumps({'started':name}),flush=True)
        start=time.perf_counter()
        log=private/f'{name}.log'
        with log.open('w',encoding='utf-8') as f:
            done=subprocess.run([sys.executable,'-X','utf8','-c',OFFLINE_BOOTSTRAP,script],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
        record={'name':name,'command':[sys.executable,'-X','utf8',script],'network_guard':'socket connect/create_connection denied in bootstrap',
                'exit_code':done.returncode,'seconds':round(time.perf_counter()-start,3),'private_log':log.relative_to(ROOT).as_posix()}
        stages.append(record);print(json.dumps(record),flush=True)
        if done.returncode:
            write_json(reports/'check_results.json',{'status':'FAIL','stages':stages,'failure':name})
            raise SystemExit(done.returncode)
    test_jobs=[('stage2_tests',['tests/stage2'],'pytest.xml'),
               ('stage0_stage1_regression',['tests/stage0/test_task_schema.py','tests/stage0/test_db_isolation.py',
                    'tests/stage0/test_evaluator_integration.py','tests/stage1'],'regression.xml')]
    for name,paths,xml in test_jobs:
        print(json.dumps({'started':name}),flush=True)
        cmd=[sys.executable,'-X','utf8','-m','pytest',*paths,'-q',f'--junitxml={reports/xml}']
        start=time.perf_counter();log=private/f'{name}.log'
        with log.open('w',encoding='utf-8') as f:
            done=subprocess.run(cmd,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
        data=ET.parse(reports/xml).getroot()
        suites=[data] if data.tag=='testsuite' else list(data)
        result={'name':name,'command':cmd,'exit_code':done.returncode,'seconds':round(time.perf_counter()-start,3),
                'private_log':log.relative_to(ROOT).as_posix(),
                'tests':sum(int(s.get('tests',0)) for s in suites),'failures':sum(int(s.get('failures',0)) for s in suites),
                'errors':sum(int(s.get('errors',0)) for s in suites),'skipped':sum(int(s.get('skipped',0)) for s in suites)}
        stages.append(result); print(json.dumps(result),flush=True)
        if done.returncode:
            write_json(reports/'check_results.json',{'status':'FAIL','stages':stages,'failure':name})
            raise SystemExit(done.returncode)
    after=verify_sources(); ledger_after=file_hash(ledger)
    fork_sha=subprocess.check_output(['git','-C','external/tau2-bench','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    fork_clean=not subprocess.check_output(['git','-C','external/tau2-bench','status','--porcelain'],cwd=ROOT,text=True).strip()
    code_after={p.relative_to(ROOT).as_posix():file_hash(p) for p in code_paths}
    if before!=after or ledger_before!=ledger_after or code_before!=code_after or not fork_clean or fork_sha!=ENVIRONMENT_SHA:
        raise RuntimeError('Immutable input or tested code changed during verification')
    packages={p:importlib.metadata.version(p) for p in ('tau2','pytest','pydantic','tokenizers','jinja2','jsonschema','PyYAML')}
    ignored=['.env','data/raw/tau2_rl_train.jsonl','data/raw/tau2_sft_train.jsonl','data/private/stage2/dialog_features.jsonl',
             'data/processed/stage2/sft_train.jsonl','data/tokenizers/qwen2.5-3b-instruct/tokenizer.json',
             'data/splits/stage2/rl_test_frozen.json']
    # Root is not a Git repository. An isolated empty Git DB validates the real
    # root .gitignore without initializing/modifying .git or staging any files.
    gitdir=private/'ignore-check.git'
    if not gitdir.exists(): subprocess.run(['git','init','--bare','--quiet',str(gitdir)],check=True,cwd=ROOT)
    result=subprocess.run(['git','--git-dir',str(gitdir),'--work-tree',str(ROOT),'check-ignore','--no-index',*ignored],
                          cwd=ROOT,text=True,capture_output=True,check=True)
    ignored_actual=result.stdout.splitlines()
    if set(ignored_actual)!=set(ignored):raise ValueError('Sensitive artifact is not ignored')
    report={'status':'PASS','stages':stages,'python':sys.version,'platform':sys.platform,'packages':packages,
            'raw_sources_before_equal_after':before==after,'sources':after,
            'ledger_before_sha256':ledger_before,'ledger_after_sha256':ledger_after,'new_paid_api_calls':0,
            'environment_sha':fork_sha,'fork_clean':fork_clean,'tested_code_sha256':code_after,
            'code_unchanged_during_checks':True,'git_ignore':{'method':'isolated private git-dir, actual workspace .gitignore',
                'checked_paths':ignored_actual,'passed':True,'workspace_git_initialized':False},
            'training_run':False,'new_real_episodes':0,'weights_downloaded':False,
            'development_corrections':['Customer ID extraction excludes payment identifiers.',
                'Missing source turn indices are warnings; valid expert turns retained.',
                'Audit set/list TypeError fixed before final full run.',
                'Round-trip test restricted to target output, avoiding system instructional examples.']}
    write_json(reports/'check_results.json',report)
    print(json.dumps({'status':'PASS','tests':sum(x.get('tests',0) for x in stages),'new_paid_api_calls':0,'raw_unchanged':True}),flush=True)


if __name__=='__main__': main()
