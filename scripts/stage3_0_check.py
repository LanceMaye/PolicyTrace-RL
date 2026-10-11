"""Offline acceptance with real command timings, private logs and immutable hashes."""
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from policytrace.data.manifests import ROOT, file_hash, read_json, write_json
from policytrace.harness.verification import verify_frozen, fork_state


def run_command(argv,name):
    folder = ROOT/'data/private/stage3_0/acceptance'
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/f'{name}.log'
    start = time.perf_counter()
    with path.open('w',encoding='utf-8') as stream:
        result = subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    return {'name':name,'command':argv,'exit_code':result.returncode,
            'seconds':round(time.perf_counter()-start,3),'private_log':path.relative_to(ROOT).as_posix(),
            'log_sha256':file_hash(path)}


def test_summary(private_xml,public_xml):
    root = ET.parse(private_xml).getroot()
    result = {k:sum(int(s.get(k,0)) for s in root) for k in ('tests','failures','errors','skipped')}
    # Tracebacks/assert introspection can contain a customer body; publish only
    # testcase names, durations and status, retaining the full XML privately.
    public = ET.Element('testsuites')
    suite = ET.SubElement(public,'testsuite',{k:str(v) for k,v in result.items()})
    for test in root.iter('testcase'):
        item = ET.SubElement(suite,'testcase',{k:test.get(k,'') for k in ('classname','name','time')})
        for kind in ('failure','error','skipped'):
            if test.find(kind) is not None:
                ET.SubElement(item,kind,{'message':'See private test evidence'})
    ET.ElementTree(public).write(public_xml,encoding='utf-8',xml_declaration=True)
    result['private_xml_sha256'] = file_hash(private_xml)
    return result


def main():
    private = ROOT/'data/private/stage3_0'
    report = ROOT/'reports/stage3_0'
    report.mkdir(parents=True,exist_ok=True)
    baseline = private/'immutable_inputs.json'
    before = verify_frozen(baseline)
    if before['changed']:
        raise ValueError('Immutable inputs changed before acceptance')
    code_paths = list((ROOT/'src/policytrace/harness').glob('*.py'))+list((ROOT/'tests/stage3_0').glob('*.py'))
    code_paths += list((ROOT/'scripts').glob('stage3_0_*.py'))
    code_paths += list((ROOT/'configs/harness').glob('*'))
    hashes = {p.relative_to(ROOT).as_posix():file_hash(p) for p in code_paths}
    commands = []
    specs = [('harness',[sys.executable,'-X','utf8','-m','pytest','tests/stage3_0','-q',
                         '--junitxml=data/private/stage3_0/acceptance/harness.xml']),
             ('regression',[sys.executable,'-X','utf8','-m','pytest','-p','policytrace.harness.regression_scope',
                 'tests/stage0','tests/stage1','tests/stage2','tests/multi_tool_compatibility','-q',
                 '--basetemp=data/private/stage3_0/acceptance/regression_tmp',
                 '--junitxml=data/private/stage3_0/acceptance/regression.xml']),
             ('demo',[sys.executable,'-X','utf8','scripts/stage3_0_offline_demo.py','--mode','offline','--split','dev']),
             ('policy_diff',[sys.executable,'-X','utf8','scripts/stage3_0_policy_diff.py'])]
    for name,argv in specs:
        print(f'Running {name}',flush=True)
        command = run_command(argv,name)
        commands.append(command)
        print({k:command[k] for k in ('name','exit_code','seconds')},flush=True)
        if command['exit_code']:
            write_json(report/'check_results.json',{'status':'PARTIAL','commands':commands})
            raise SystemExit(command['exit_code'])
    harness = test_summary(private/'acceptance/harness.xml',report/'pytest.xml')
    regression = test_summary(private/'acceptance/regression.xml',report/'regression.xml')
    after = verify_frozen(baseline)
    code_changed = [name for name,h in hashes.items() if file_hash(ROOT/name)!=h]
    # Check ignore rules without initializing this workspace or editing Git config.
    ignore_paths = ['.env','data/private/stage3_0/acceptance/harness.xml',
                    'data/private/stage3_0/decision_trace.jsonl','data/raw/tau2_rl_train.jsonl',
                    'data/processed/stage2/policy_main_v1/sft_train_main.tokenized.jsonl.gz']
    ignore = subprocess.run(['git','--git-dir='+str(ROOT/'external/tau2-bench/.git'),
        '--work-tree='+str(ROOT),'-c','core.excludesFile='+str(ROOT/'.gitignore'),
        'check-ignore','--no-index',*ignore_paths],cwd=ROOT,text=True,capture_output=True)
    ignored = set(ignore.stdout.splitlines())
    ignore_ok = all(p in ignored for p in ignore_paths)
    results = {'status':'PASS_OFFLINE' if not after['changed'] and not code_changed and ignore_ok else 'PARTIAL',
        'human_acceptance':'PENDING','executed_at':datetime.now(timezone.utc).isoformat(),
        'environment':{'platform':platform.platform(),'python':platform.python_version(),
                       'executable':sys.executable,'gpu_used':False,'linux_revalidation_this_stage':False},
        'commands':commands,'harness_tests':harness,'regression_tests':regression,
        'regression_scope':read_json(report/'regression_scope.json'),
        'immutable_inputs':after,'tested_code':hashes,'tested_code_changed':code_changed,
        'git_ignore':{'exit_code':ignore.returncode,'all_private_paths_ignored':ignore_ok,'checked_paths':ignore_paths},
        'offline_demo':read_json(report/'offline_demo_results.json'),
        'policy_diff':read_json(report/'policy_diff_results.json'),
        'paid_api_calls':0,'weights_downloaded':False,'real_student_forward':False,
        'gpu_rented':False,'base_baseline_executed':False,'training_started':False,
        'formal_pass1':None,'formal_pass4':None,'stage3_1_started':False,'git_commit_or_push':False}
    write_json(report/'check_results.json',results)
    print({'status':results['status'],'harness_tests':harness['tests'],
           'regression_tests':regression['tests'],'unchanged_files':after['file_count']},flush=True)
    if results['status']!='PASS_OFFLINE':
        raise SystemExit(1)


if __name__=='__main__':
    main()
