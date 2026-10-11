"""Reproduce only the multi-tool audit and focused CPU tests; preserve Stage 2 evidence."""
import importlib.metadata
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from policytrace.data.manifests import ROOT,read_json,write_json,file_hash
from policytrace.evaluation.schema import ENVIRONMENT_SHA


def main():
    private=ROOT/'data/private/stage2/multi_tool_compatibility';private.mkdir(parents=True,exist_ok=True)
    before=read_json(private/'immutable_before.json')
    code_files=[*ROOT.glob('src/policytrace/compatibility/*.py'),*ROOT.glob('tests/multi_tool_compatibility/*.py'),
                *ROOT.glob('scripts/multi_tool_*.py')]
    code_hashes={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(code_files)}
    stages=[]
    jobs=[('full_multi_target_audit',[sys.executable,'-X','utf8','scripts/multi_tool_compatibility_check.py']),
          ('focused_tests',[sys.executable,'-X','utf8','-m','pytest','tests/multi_tool_compatibility',
                            'tests/stage2/test_format_and_mask.py','-q',
                            '--junitxml=reports/stage2/multi_tool_pytest.xml'])]
    for name,command in jobs:
        print(f'Starting {name}',flush=True)
        start=time.perf_counter();log=private/f'{name}.log'
        with log.open('w',encoding='utf-8') as stream:
            result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        entry={'name':name,'command':command,'exit_code':result.returncode,
               'seconds':round(time.perf_counter()-start,3),'private_log':log.relative_to(ROOT).as_posix()}
        if name=='focused_tests' and (ROOT/'reports/stage2/multi_tool_pytest.xml').exists():
            tree=ET.parse(ROOT/'reports/stage2/multi_tool_pytest.xml').getroot()
            entry.update({field:sum(int(s.get(field,0)) for s in tree) for field in ('tests','failures','errors','skipped')})
        stages.append(entry);print(entry,flush=True)
        if result.returncode:break
    changed=[p for p,h in before.items() if file_hash(ROOT/p)!=h]
    code_changed=[p for p,h in code_hashes.items() if file_hash(ROOT/p)!=h]
    sha=subprocess.check_output(['git','-C','external/tau2-bench','rev-parse','HEAD'],text=True).strip()
    clean=not subprocess.check_output(['git','-C','external/tau2-bench','status','--porcelain'],text=True).strip()
    passed=all(s['exit_code']==0 for s in stages) and len(stages)==2 and not changed and not code_changed and sha==ENVIRONMENT_SHA and clean
    output={'status':'PASS' if passed else 'FAIL','stages':stages,'immutable_files_checked':len(before),
            'immutable_failures':changed,'tested_code_changed':code_changed,'tested_code':code_hashes,
            'fork_sha':sha,'fork_clean':clean,'historical_report_sha256':before['reports/stage2/STAGE2_REPORT.md'],
            'model_api_calls':0,'weights_downloaded':False,'training_started':False,
            'packages':{p:importlib.metadata.version(p) for p in ('tau2','pytest','pydantic','tokenizers','jinja2','jsonschema')}}
    write_json(ROOT/'reports/stage2/multi_tool_check_results.json',output)
    print(output['status'],flush=True)
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
