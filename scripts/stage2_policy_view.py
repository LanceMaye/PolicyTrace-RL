"""Build approved policy-filtered views from frozen SFT rows and existing tokens."""
import socket
def denied(*args,**kwargs):raise RuntimeError('Policy view processing must remain offline')
socket.socket.connect=denied
socket.socket.connect_ex=denied
socket.create_connection=denied

from pathlib import Path
import subprocess
import time

from policytrace.data.manifests import ROOT,read_json,write_json,write_jsonl,file_hash,verify_sources
from policytrace.data.sft_policy_view import RULE_VERSION,partition_split
from policytrace.data.sft_tokenize import QwenTokenizer
from policytrace.evaluation.schema import ENVIRONMENT_SHA


def main():
    start=time.perf_counter()
    private=ROOT/'data/private/stage2/policy_main_v1';private.mkdir(parents=True,exist_ok=True)
    out=ROOT/'data/processed/stage2/policy_main_v1'
    splits=ROOT/'data/splits/stage2/policy_main_v1'
    config=read_json(ROOT/'configs/data/sft_main_view.json')
    if config['version']!=RULE_VERSION or config['policy_modified'] or config['retokenize'] or config['truncate']:
        raise ValueError('Unexpected policy-view configuration')
    if config['target_gate']!={'max_tool_calls':1,'forbid_text_with_tool_calls':True,'history_handling':'preserve_and_annotate_masked_history'}:
        raise ValueError('Unsupported target gate')
    frozen=read_json(ROOT/'reports/stage2/source_manifest.json');inputs={}
    for section,base in [('public_files',ROOT),('processed_artifacts',ROOT/'data/processed/stage2'),
                          ('split_manifests',ROOT/'data/splits/stage2'),('private_audit_artifacts',ROOT/'data/private/stage2')]:
        for name,entry in frozen[section].items():
            p=base/name;expected=entry if isinstance(entry,str) else entry['sha256']
            if file_hash(p)!=expected:raise ValueError(f'Frozen Stage 2 mismatch: {name}')
            inputs[p.relative_to(ROOT).as_posix()]=expected
    verify_sources()
    sha=subprocess.check_output(['git','-C','external/tau2-bench','rev-parse','HEAD'],text=True).strip()
    if sha!=ENVIRONMENT_SHA:raise ValueError('Wrong Fork commit')
    clean=lambda:not subprocess.check_output(['git','-C','external/tau2-bench','status','--porcelain'],text=True).strip()
    if not clean():raise ValueError('Fork is not clean')
    for p in [ROOT/config['policy_source'],ROOT/'data/private/stage0/deepseek/cost_ledger.json',
              ROOT/'reports/stage2/source_manifest.json',*sorted((ROOT/'reports/stage2').glob('multi_tool*.json')),
              ROOT/'reports/stage2/STAGE2_REPORT.md',ROOT/'reports/stage2/MULTI_TOOL_COMPATIBILITY_REPORT.md',
              ROOT/'reports/stage2/MULTI_TOOL_COMPATIBILITY_ERRATUM.md']:
        inputs[p.relative_to(ROOT).as_posix()]=file_hash(p)
    write_json(private/'immutable_inputs.json',inputs)
    tokenizer=QwenTokenizer()  # Verify pinned tokenizer and obtain EOS; do not encode.
    results={};decisions=[]
    for split in ('train','val'):
        original=ROOT/'data/processed/stage2'
        result,rows=partition_split(original/f'sft_{split}.jsonl',original/f'sft_{split}.tokenized.jsonl.gz',out,split,tokenizer.eos)
        for view,artifacts in result['artifacts'].items():
            for entry in artifacts.values():entry['path']=Path(entry['path']).relative_to(ROOT).as_posix()
        # Compare to the exact frozen split ID set; no reassignment is permitted.
        expected=read_json(ROOT/f'data/splits/stage2/sft_{split}.json')['sample_ids']
        actual=result['sample_ids']['main']+result['sample_ids']['quarantine']
        if len(actual)!=len(expected) or set(actual)!=set(expected):raise ValueError('Frozen split membership changed')
        results[split]=result;decisions.extend(rows)
        write_json(splits/f'sft_{split}.json',result)
        print(f"{split}: main={result['counts']['main']}, quarantine={result['counts']['quarantine']}",flush=True)
    if set(results['train']['source_dialog_ids']['main']+results['train']['source_dialog_ids']['quarantine']) & set(results['val']['source_dialog_ids']['main']+results['val']['source_dialog_ids']['quarantine']):
        raise ValueError('Dialog leakage between splits')
    for p,h in inputs.items():
        if file_hash(ROOT/p)!=h:raise ValueError(f'Frozen input changed: {p}')
    if not clean():raise ValueError('Fork changed during processing')
    write_jsonl(private/'decisions.jsonl',decisions)
    manifest={'version':RULE_VERSION,'view':'policy_main_v1','config':'configs/data/sft_main_view.json',
        'config_sha256':file_hash(ROOT/'configs/data/sft_main_view.json'),
        'policy_path':config['policy_source'],'policy_sha256':inputs[config['policy_source']],
        'policy_modified':False,'environment_sha':ENVIRONMENT_SHA,'splits':results,
        'source_manifest_sha256':inputs['reports/stage2/source_manifest.json'],
        'tokenizer_revision':tokenizer.config.get('_commit_hash', 'aa8e72537993ba99e69dfaafa59ed015b17504d1'),
        'retokenized':False,'target_or_history_modified':False,'complete_business_compliance_claimed':False}
    write_json(out/'manifest.json',manifest)
    public={'status':'PASS','rule_version':RULE_VERSION,'active_config':'configs/data/sft_main_view.json',
        'policy_sha256':manifest['policy_sha256'],'policy_modified':False,'retokenized':False,
        'counts':{split:results[split]['counts'] for split in results},
        'reason_counts':{split:results[split]['reason_counts'] for split in results},
        'tool_distributions':{split:results[split]['target_tool_call_counts'] for split in results},
        'source_dialog_counts':{split:{v:len(d) for v,d in results[split]['source_dialog_ids'].items()} for split in results},
        'mask_samples_checked':sum(r['mask_samples_checked'] for r in results.values()),
        'immutable_inputs_checked':len(inputs),'immutable_changes':[],'fork_clean':True,
        'seconds':round(time.perf_counter()-start,3),'manifest':out.relative_to(ROOT).as_posix()+'/manifest.json',
        'private_decisions':private.relative_to(ROOT).as_posix()+'/decisions.jsonl',
        'paid_api_calls':0,'training_started':False,'stage3_started':False}
    write_json(ROOT/'reports/stage2/policy_view_results.json',public)
    print(f"PASS: {public['mask_samples_checked']} existing masks validated, no retokenization",flush=True)


if __name__=='__main__':main()
