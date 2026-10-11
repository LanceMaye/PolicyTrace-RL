"""Focused Stage 2 regression of the approved policy view; no training or APIs."""
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from policytrace.data.manifests import ROOT,read_json,write_json,file_hash


def main():
    result=read_json(ROOT/'reports/stage2/policy_view_results.json')
    if result['status']!='PASS':raise ValueError('Build the policy view successfully first')
    private=ROOT/'data/private/stage2/policy_main_v1'
    code_paths=[ROOT/'src/policytrace/data/sft_policy_view.py',ROOT/'tests/stage2/test_policy_view.py',
                ROOT/'scripts/stage2_policy_view.py',ROOT/'scripts/stage2_policy_verify.py',ROOT/'configs/data/sft_main_view.json']
    hashes={p.relative_to(ROOT).as_posix():file_hash(p) for p in code_paths}
    argv=[sys.executable,'-X','utf8','-m','pytest','tests/stage2','-q',
          '--junitxml=reports/stage2/policy_view_pytest.xml']
    start=time.perf_counter()
    with (private/'pytest.log').open('w',encoding='utf-8') as stream:
        process=subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    tree=ET.parse(ROOT/'reports/stage2/policy_view_pytest.xml').getroot()
    counts={k:sum(int(s.get(k,0)) for s in tree) for k in ('tests','failures','errors','skipped')}
    changed=[p for p,h in hashes.items() if file_hash(ROOT/p)!=h]
    output={'status':'PASS' if process.returncode==0 and not changed else 'FAIL',
            'command':argv,'exit_code':process.returncode,'seconds':round(time.perf_counter()-start,3),
            **counts,'tested_code':hashes,'tested_code_changed':changed,
            'policy_view_build_command':[sys.executable,'-X','utf8','scripts/stage2_policy_view.py'],
            'policy_view_build_results_sha256':file_hash(ROOT/'reports/stage2/policy_view_results.json'),
            'source_results':result,'paid_api_calls':0,'training_started':False,'stage3_started':False}
    write_json(ROOT/'reports/stage2/policy_view_check_results.json',output)
    print({k:v for k,v in output.items() if k not in ('tested_code','source_results')},flush=True)
    if output['status']!='PASS':raise SystemExit(1)


if __name__=='__main__':main()
