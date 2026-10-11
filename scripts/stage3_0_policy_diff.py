"""Compare every frozen SFT Main system prompt against native runtime policy."""
from collections import Counter
import difflib
import hashlib
import time

from policytrace.data.manifests import ROOT, file_hash, read_jsonl, write_json
from policytrace.data.sft_tokenize import qwen_messages, QwenTokenizer
from policytrace.harness.runner import DevTaskPool
from policytrace.stage0.db_adapter import make_retail_env
from tau2.agent.llm_agent import SYSTEM_PROMPT, AGENT_INSTRUCTION


def text_hash(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()


def main():
    start = time.perf_counter()
    record,snapshot = DevTaskPool().load('retail_152')
    runtime_policy = make_retail_env(record,snapshot).get_policy()
    runtime_system = SYSTEM_PROMPT.format(agent_instruction=AGENT_INSTRUCTION,domain_policy=runtime_policy)
    runtime_wrapped = qwen_messages([{'role':'system','content':runtime_system}])[0]['content']
    tokenizer = QwenTokenizer()
    counts,systems,policies = Counter(),{},{}
    for split in ('train','val'):
        path = ROOT/f'data/processed/stage2/policy_main_v1/sft_{split}_main.jsonl'
        for row in read_jsonl(path):
            system = row['messages'][0]['content']
            policy = system.rsplit('<policy>',1)[1].split('</policy>',1)[0]
            key = text_hash(system)
            systems[key] = system
            policies[key] = policy
            counts[split,key] += 1
    private = ROOT/'data/private/stage3_0/policy_diff'
    private.mkdir(parents=True,exist_ok=True)
    evidence = []
    for key,system in sorted(systems.items()):
        wrapped = qwen_messages([{'role':'system','content':system}])[0]['content']
        diff = '\n'.join(difflib.unified_diff(policies[key].splitlines(),runtime_policy.splitlines(),
                    fromfile='frozen_SFT_source_business_policy',tofile='fixed_Fork_runtime_business_policy',lineterm=''))+'\n'
        path = private/f'{key}.policy.diff'
        path.write_text(diff,encoding='utf8')
        source_wrapper = system.split('<policy>',1)[0]
        runtime_wrapper = runtime_system.split('<policy>',1)[0]
        wrapper_diff = '\n'.join(difflib.unified_diff(source_wrapper.splitlines(),runtime_wrapper.splitlines(),
                    fromfile='frozen_SFT_wrapper',tofile='native_LLMAgent_wrapper',lineterm=''))+'\n'
        wrapper_path = private/f'{key}.wrapper.diff'
        wrapper_path.write_text(wrapper_diff,encoding='utf8')
        evidence.append({'source_system_sha256':key,'source_policy_sha256':text_hash(policies[key]),
            'source_train_count':counts['train',key],'source_val_count':counts['val',key],
            'raw_wrapper_equal':source_wrapper==runtime_wrapper,
            'qwen_wrapper_equal_excluding_policy':wrapped.split('<policy>',1)[0]==runtime_wrapped.split('<policy>',1)[0],
            'policy_exact_equal':policies[key]==runtime_policy,
            'policy_equal_after_outer_whitespace':policies[key].strip()==runtime_policy.strip(),
            'diff_artifact':path.relative_to(ROOT).as_posix(),'diff_sha256':file_hash(path),
            'wrapper_diff_artifact':wrapper_path.relative_to(ROOT).as_posix(),'wrapper_diff_sha256':file_hash(wrapper_path),
            'policy_diff_added_lines':sum(line.startswith('+') and not line.startswith('+++') for line in diff.splitlines()),
            'policy_diff_removed_lines':sum(line.startswith('-') and not line.startswith('---') for line in diff.splitlines()),
            'source_mentions_single_call':'at most make one tool' in policies[key].lower(),
            'runtime_mentions_single_call':'at most make one tool' in runtime_policy.lower()})
    report = {'status':'PASS_AUDIT_DIFF_RECORDED','seconds':round(time.perf_counter()-start,3),
        'main_train_scanned':sum(n for (s,k),n in counts.items() if s=='train'),
        'main_val_scanned':sum(n for (s,k),n in counts.items() if s=='val'),
        'unique_source_systems':len(systems),'runtime_policy_sha256':text_hash(runtime_policy),
        'runtime_policy_file_sha256':file_hash(ROOT/'external/tau2-bench/data/tau2/domains/retail/policy.md'),
        'runtime_system_sha256':text_hash(runtime_system),
        'runtime_qwen_wrapped_system_sha256':text_hash(runtime_wrapped),
        'template_sha256':text_hash(tokenizer.raw_template),'variants':evidence,
        'sft_changed':False,'runtime_policy_changed':False,
        'attribution':'qwen_messages standardizes protocol wrapper only; source business policy is preserved verbatim and remains different'}
    write_json(ROOT/'reports/stage3_0/policy_diff_results.json',report)
    print({k:report[k] for k in ('status','main_train_scanned','main_val_scanned','unique_source_systems','seconds')})


if __name__=='__main__':
    main()
