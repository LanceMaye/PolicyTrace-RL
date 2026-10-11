"""Supplemental read-only metadata/signature checks for the compatibility report."""
from collections import Counter
import inspect
import json
import policytrace.stage0
from loguru import logger
logger.remove()

from policytrace.compatibility.probes import baseline
from policytrace.data.manifests import ROOT,read_json,read_jsonl,write_json
from policytrace.stage0.db_adapter import make_retail_env


def main():
    evidence=read_json(ROOT/'reports/stage2/multi_tool_audit.json')
    rows=[r for r in read_jsonl(ROOT/'data/private/stage2/normalized_source.jsonl') if len(r['answer'].get('tool_calls',[]))>1]
    record,snapshot=baseline();env=make_retail_env(record,snapshot)
    dialogs={d['id']:d for d in read_jsonl(ROOT/'data/private/stage2/dialog_features.jsonl')}
    counts=Counter(signature_error_calls=0,source_observation_payload_mismatches=0)
    for row in rows:
        orders={}
        for message in row['messages']:
            if message['role']!='tool':continue
            try:body=json.loads(message['content'])
            except ValueError:continue
            if isinstance(body,dict) and 'order_id' in body:orders[body['order_id']]=body
        for call in row['answer']['tool_calls']:
            fn=call['function']
            try:inspect.signature(env.tools.tools[fn['name']]).bind(**fn['arguments'])
            except TypeError:counts['signature_error_calls']+=1
            if env.tools.tool_type(fn['name']).value=='write':
                counts['write_calls']+=1
                counts['write_order_preobserved']+=fn['arguments'].get('order_id') in orders
        counts['targets_with_mixed_assistant_in_history']+=any(
            m['role']=='assistant' and m.get('tool_calls') and m['content'].strip() for m in row['messages'])
        full=dialogs[row['source_dialog_id']]['messages'];n=len(row['messages']);calls=row['answer']['tool_calls']
        following=full[n+1:n+1+len(calls)]
        if n<len(full) and full[n]==row['answer'] and len(following)==len(calls) and all(m['role']=='tool' for m in following):
            for call,observation in zip(calls,following):
                assert call['id']==observation['tool_call_id'] and call['function']['name']==observation['name']
                counts['source_observations_id_name_order_checked']+=1
                try:body=json.loads(observation['content'])
                except ValueError:continue
                if not isinstance(body,dict):continue
                for key in ('order_id','user_id','product_id'):
                    if key in call['function']['arguments'] and key in body:
                        counts['source_entity_payload_keys_checked']+=1
                        counts['source_observation_payload_mismatches']+=body[key]!=call['function']['arguments'][key]
    probes=evidence['representative_source_probes']
    counts['source_probe_calls']=sum(p['calls'] for p in probes)
    counts['source_probe_errors']=sum(p['errors'] for p in probes)
    counts['source_probe_response_matches']=sum(p['source_result_comparisons'].count('equal') for p in probes)
    counts['source_probe_response_differences']=sum(p['source_result_comparisons'].count('different') for p in probes)
    counts['source_probe_pre_target_only']=sum(p['fixture_basis']=='pre-target observations only' for p in probes)
    counts['source_probe_future_read_fill']=len(probes)-counts['source_probe_pre_target_only']
    result={'counts':dict(counts),'batch_sizes':dict(Counter(str(len(r['answer']['tool_calls'])) for r in rows)),
        'read_only_tool_patterns':dict(Counter(','.join(c['function']['name'] for c in r['answer']['tool_calls'])
            for r in rows if not any(env.tools.tool_type(c['function']['name']).value=='write' for c in r['answer']['tool_calls']))),
        'missing_recorded_batch_ids':[r['sample_id'] for r in read_jsonl(ROOT/'data/private/stage2/multi_tool_compatibility/target_audit.jsonl')
                                      if not r['recorded_response_batch']]}
    write_json(ROOT/'reports/stage2/multi_tool_static_details.json',result)
    print(json.dumps(result['counts']),flush=True)


if __name__=='__main__':main()
