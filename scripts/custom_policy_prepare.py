"""Create a new mixed-only SFT view, preserving frozen rows and token records."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import time

from policytrace.data.manifests import ROOT, file_hash, read_json, read_jsonl, write_json, write_jsonl, verify_sources
from policytrace.data.sft_policy_view import partition_split
from policytrace.data.sft_tokenize import QwenTokenizer, qwen_messages, validate_labels
from policytrace.data.sft_format import tool_validators
from policytrace.compatibility.multi_tool import parse_completion
from policytrace.harness.verification import offline_guard
from policytrace.harness.runner import DevTaskPool
from policytrace.stage0.db_adapter import make_retail_env
from policytrace.policy import POLICY_VERSION, POLICY_SHA256, active_policy, verify_fork, student_system

RULE_VERSION = 'policytrace-sft-mixed-only-v2'
VIEW = 'policy_sft_v2'


def main():
    start = time.perf_counter()
    out = ROOT/'data/processed/stage2'/VIEW
    private = ROOT/'data/private/policy_transition_v2'
    report = ROOT/'reports/policy_transition_v2'
    config_path = ROOT/'configs/data/sft_mixed_only_v2.json'
    config = read_json(config_path)
    if out.exists():
        raise FileExistsError('Do not overwrite a versioned data view')
    if config['target_gate']['max_tool_calls'] is not None or not config['target_gate']['forbid_text_with_tool_calls']:
        raise ValueError('Expected the approved mixed-only gate')
    policy = active_policy()
    runtime = verify_fork()
    original_manifest = read_json(ROOT/'reports/stage2/source_manifest.json')
    # Verify all immutable Stage 2 assets. The original data/split files are never rebuilt.
    for section, base in [('public_files',ROOT),('processed_artifacts',ROOT/'data/processed/stage2'),
                          ('split_manifests',ROOT/'data/splits/stage2'),('private_audit_artifacts',ROOT/'data/private/stage2')]:
        for name, entry in original_manifest[section].items():
            expected = entry if isinstance(entry,str) else entry['sha256']
            historical = ROOT/'docs/history/README.stage2_original.md' if section=='public_files' and name=='README.md' else base/name
            if file_hash(historical) != expected:
                raise ValueError(f'Frozen Stage 2 asset changed: {name}')
    verify_sources()
    tokenizer = QwenTokenizer()
    record,snapshot = DevTaskPool().load('retail_152')
    env = make_retail_env(record,snapshot)
    tools = [tool.openai_schema for tool in env.get_tools()]
    validators = tool_validators(tools)
    runtime_policy = env.get_policy()
    if hashlib.sha256(runtime_policy.encode('utf-8')).hexdigest() != POLICY_SHA256:
        raise ValueError('Native environment policy mismatch')
    system = student_system(runtime_policy)
    wrapped = qwen_messages([{'role':'system','content':system}])[0]['content']
    policies = Counter()
    for split in ('train','val'):
        for row in read_jsonl(ROOT/f'data/processed/stage2/sft_{split}.jsonl'):
            source = row['messages'][0]['content']
            business = source.rsplit('<policy>',1)[1].split('</policy>',1)[0]
            policies[hashlib.sha256(business.encode('utf-8')).hexdigest()] += 1
            if business != runtime_policy or qwen_messages([row['messages'][0]])[0]['content'] != wrapped:
                raise ValueError('SFT and runtime business policy/wrapper differ')
    if dict(policies) != {POLICY_SHA256:11287}:
        raise ValueError('Unexpected source policy coverage')
    results,decisions = {},[]
    report.mkdir(parents=True,exist_ok=True)
    with offline_guard() as attempts:
        for split,expected in [('train',(9707,441)),('val',(1080,59))]:
            original = ROOT/'data/processed/stage2'
            result,receipt = partition_split(original/f'sft_{split}.jsonl',
                original/f'sft_{split}.tokenized.jsonl.gz',out,split,tokenizer.eos,
                max_tool_calls=None,rule_version=RULE_VERSION)
            for artifacts in result['artifacts'].values():
                for entry in artifacts.values():
                    entry['path']=Path(entry['path']).relative_to(ROOT).as_posix()
            if (result['counts']['main'],result['counts']['quarantine']) != expected:
                raise ValueError('Unexpected partition counts')
            frozen = read_json(ROOT/f'data/splits/stage2/sft_{split}.json')
            emitted = result['sample_ids']['main'] + result['sample_ids']['quarantine']
            if len(emitted)!=len(frozen['sample_ids']) or set(emitted)!=set(frozen['sample_ids']):
                raise ValueError('Frozen split membership changed')
            counts = Counter(); representatives = {}; maximum = 0
            rows = read_jsonl(ROOT/result['artifacts']['main']['rows']['path'])
            with gzip.open(ROOT/result['artifacts']['main']['tokens']['path'],'rt',encoding='utf-8') as stream:
                for row,line in zip(rows,stream,strict=True):
                    token=json.loads(line)
                    if token['provenance']!=row['provenance']:
                        raise ValueError('Main token/row association changed')
                    validate_labels(token,tokenizer.eos)
                    maximum=max(maximum,len(token['input_ids']))
                    if len(token['input_ids'])>config['max_length']:
                        raise ValueError('Oversized sample; no truncation is authorized')
                    target=tokenizer.tokenizer.decode([v for v in token['labels'] if v!=-100],skip_special_tokens=False)
                    parsed=parse_completion(target,validators,'static_'+row['provenance']['sample_id'],reject_mixed=True)
                    expected_calls=[c['function'] for c in row['answer'].get('tool_calls',[])]
                    if [{'name':c.name,'arguments':c.arguments} for c in parsed.tool_calls or []]!=expected_calls:
                        raise ValueError('Target tool structure changed')
                    counts['targets_checked']+=1
                    counts['multi_targets_checked']+=len(expected_calls)>1
                    counts['parser_tool_calls_checked']+=len(expected_calls)
                    kind = 'text' if not expected_calls else ('single' if len(expected_calls)==1 else
                        ('multi_write' if any(c['name'].startswith(('modify_','cancel_','return_','exchange_')) for c in expected_calls) else 'multi_read'))
                    counts[kind]+=1
                    if kind not in representatives:
                        # Encode representative samples afresh to verify reuse and the runtime prefill.
                        rebuilt=tokenizer.prepare(row['messages'],row['answer'],tools)
                        for field,value in rebuilt.items():
                            if token[field]!=value:raise ValueError('Representative reused token differs from fresh encoding')
                        visible=[{'role':'system','content':system}]+row['messages'][1:]
                        runtime_ids=tokenizer.encode(tokenizer.render(visible,tools,generation=True)).ids
                        if runtime_ids!=token['input_ids'][:token['prompt_tokens']]:
                            raise ValueError('Runtime prompt IDs differ from SFT prompt IDs')
                        representatives[kind]={'sample_id':row['provenance']['sample_id'],'prompt_tokens':token['prompt_tokens'],
                            'target_tokens':token['supervised_tokens'],'call_count':len(expected_calls),'prompt_ids_equal':True,'fresh_encoding_equal':True}
            result['protocol_audit']={'counts':dict(counts),'max_input_tokens':maximum,
                'representatives':representatives,'source_database_replay':'unavailable; no source DB or fake observations created'}
            results[split]=result;decisions.extend(receipt)
            write_json(ROOT/f'data/splits/stage2/{VIEW}/sft_{split}.json',result)
            print(f'{split}: main={expected[0]}, mixed quarantine={expected[1]}, parser={counts["targets_checked"]}',flush=True)
    if attempts:raise ValueError('Network was attempted')
    dialogs={split:set(result['source_dialog_ids']['main']+result['source_dialog_ids']['quarantine']) for split,result in results.items()}
    if dialogs['train'] & dialogs['val']:raise ValueError('Source dialog leakage')
    write_jsonl(private/'decisions.jsonl',decisions)
    manifest={'version':RULE_VERSION,'view':VIEW,'config':config_path.relative_to(ROOT).as_posix(),
        'config_sha256':file_hash(config_path),'policy_version':POLICY_VERSION,'policy_sha256':POLICY_SHA256,
        'policy_source':policy['policy_source'],'runtime_policy_path':'external/tau2-bench/data/tau2/domains/retail/policy.md',
        'original_policy_backup':policy['original_backup'],'environment_sha':runtime['commit'],
        'policy_modified':True,'retokenized':False,'target_or_history_modified':False,
        'reason_for_token_reuse':'Existing SFT already contains the exact adopted business policy and shared Qwen template',
        'source_quality_excluded_count':108,'source_quality_reincluded':0,'frozen_split_reassigned':False,
        'complete_business_compliance_claimed':False,'tokenizer_revision':'aa8e72537993ba99e69dfaafa59ed015b17504d1',
        'splits':results,'source_policy_counts':dict(policies),'mask_samples_checked':len(decisions)}
    write_json(out/'manifest.json',manifest)
    # Activate only after successful full processing. The old configuration has a byte-exact backup.
    (ROOT/'configs/data/sft_main_view.json').write_bytes(config_path.read_bytes())
    public={'status':'PASS','policy_version':POLICY_VERSION,'policy_sha256':POLICY_SHA256,'fork':runtime,
        'manifest':(out/'manifest.json').relative_to(ROOT).as_posix(),'active_config':'configs/data/sft_main_view.json',
        'retokenized':False,'sft_rows_or_targets_rewritten':False,'frozen_split_changed':False,
        'counts':{s:r['counts'] for s,r in results.items()},'tool_distributions':{s:r['target_tool_call_counts'] for s,r in results.items()},
        'protocol_audit':{s:r['protocol_audit'] for s,r in results.items()},'policy_systems_checked':sum(policies.values()),
        'mask_samples_checked':len(decisions),'source_quality_excluded':108,'network_attempts':len(attempts),
        'paid_api_calls':0,'gpu_used':False,'training_started':False,'seconds':round(time.perf_counter()-start,3)}
    write_json(report/'data_results.json',public)
    print({'status':'PASS','mask_samples':len(decisions),'retokenized':False},flush=True)


if __name__=='__main__':main()
