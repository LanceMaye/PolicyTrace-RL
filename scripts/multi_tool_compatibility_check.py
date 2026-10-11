"""Full frozen multi-target audit plus bounded offline native execution probes.

Creates new evidence only. Never exports altered SFT examples or split views.
"""
import socket
_local_connect = socket.socket.connect
def local_only_connect(self, address):
    # Windows asyncio constructs a local TCP self-pipe. Permit that local
    # plumbing only; all external sockets remain blocked.
    if isinstance(address, tuple) and address[0] == '127.0.0.1':
        return _local_connect(self, address)
    raise RuntimeError('Multi-tool verification forbids external network access')
def denied(*args, **kwargs):
    raise RuntimeError('Multi-tool verification forbids network access')
socket.socket.connect = local_only_connect
socket.socket.connect_ex = denied
socket.create_connection = denied

import policytrace.stage0
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time
import sys
from loguru import logger
logger.remove()
logger.add(sys.stderr,level='ERROR')

from tau2.data_model.message import AssistantMessage, ToolCall
from tau2.domains.retail.data_model import RetailDB, User, Order, Product
from tau2.domains.retail.environment import get_environment
from tau2.utils import get_pydantic_hash

from policytrace.compatibility.multi_tool import parse_completion, execute_batch, context_batch
from policytrace.compatibility.probes import baseline, native_probe
from policytrace.data.manifests import ROOT, read_json, read_jsonl, write_json, write_jsonl, file_hash, digest
from policytrace.data.sft_format import tool_validators
from policytrace.data.sft_tokenize import QwenTokenizer, parse_serialized_calls
from policytrace.evaluation.schema import ENVIRONMENT_SHA

PRIVATE = ROOT/'data/private/stage2/multi_tool_compatibility'
REPORTS = ROOT/'reports/stage2'
WRITES = {'cancel_pending_order','exchange_delivered_order_items','modify_pending_order_address',
          'modify_pending_order_items','modify_pending_order_payment','modify_user_address','return_delivered_order_items'}
ENTITY_MODELS = {'get_user_details':('users','user_id',User),
                 'get_order_details':('orders','order_id',Order),
                 'get_product_details':('products','product_id',Product)}


def observed_entities(messages):
    """Latest real source tool observations; no invented/default entity fields."""
    entities = {'users':{},'orders':{},'products':{}}
    for m in messages:
        if m['role'] != 'tool': continue
        try: body = json.loads(m['content'])
        except (ValueError, TypeError): continue
        if not isinstance(body,dict): continue
        # Write tools also return complete order/user records; latest visible state.
        for kind, key, model in ENTITY_MODELS.values():
            if key in body:
                try: entities[kind][body[key]] = model.model_validate(body).model_dump(mode='json')
                except ValueError: pass
    return entities


def semantic_flags(row):
    """Conservative local guards; absence of evidence is unknown, never invalid."""
    entities = observed_entities(row['messages']); errors = set(); dependency = False
    prior_writes = set(); shared_balances = set(); balance_hazard = False
    for c in row['answer']['tool_calls']:
        name, args = c['function']['name'], c['function']['arguments']
        oid = args.get('order_id'); order = entities['orders'].get(oid)
        if oid in prior_writes: dependency = True
        if name in WRITES and oid:
            prior_writes.add(oid)
        if name == 'cancel_pending_order' and args.get('reason') not in {'no longer needed','ordered by mistake'}:
            errors.add('invalid_cancel_reason')
        if order and name in WRITES:
            status = order['status']
            expected = {'cancel_pending_order':{'pending'},'modify_pending_order_items':{'pending'},
                        'modify_pending_order_address':{'pending','pending (item modified)'},
                        'modify_pending_order_payment':{'pending','pending (item modified)'},
                        'return_delivered_order_items':{'delivered'},'exchange_delivered_order_items':{'delivered'}}
            if name in expected and status not in expected[name]: errors.add('observed_order_status_guard')
            if 'item_ids' in args:
                if Counter(args['item_ids']) - Counter(i['item_id'] for i in order['items']):
                    errors.add('observed_order_item_guard')
            user = entities['users'].get(order['user_id'])
            method = args.get('payment_method_id')
            if user and method and method not in user['payment_methods']: errors.add('observed_payment_method_missing')
            if name == 'return_delivered_order_items' and user and method in user['payment_methods']:
                if user['payment_methods'][method]['source'] != 'gift_card' and method != order['payment_history'][0]['payment_method_id']:
                    errors.add('return_payment_not_original_or_gift_card')
            if name == 'modify_pending_order_payment':
                if len(order['payment_history']) != 1: errors.add('payment_history_guard')
                if order['payment_history'] and method == order['payment_history'][0]['payment_method_id']:
                    errors.add('payment_method_unchanged')
            if 'new_item_ids' in args:
                if len(args['item_ids']) != len(args['new_item_ids']): errors.add('replacement_item_count')
                for old, new in zip(args['item_ids'],args['new_item_ids']):
                    if name == 'modify_pending_order_items' and old == new: errors.add('replacement_item_unchanged')
                    item = next((i for i in order['items'] if i['item_id']==old),None)
                    product = entities['products'].get(item['product_id']) if item else None
                    if product and (new not in product['variants'] or not product['variants'][new]['available']):
                        errors.add('observed_replacement_variant_guard')
            # Conservative balance-sharing hazard: same observed gift card touched
            # by two actions. This is not a proven error or intra-turn data reference.
            touched = set()
            if name == 'cancel_pending_order': touched.update(p['payment_method_id'] for p in order['payment_history'])
            elif name in {'modify_pending_order_payment','modify_pending_order_items'}:
                touched.add(method)
                if name == 'modify_pending_order_payment': touched.update(p['payment_method_id'] for p in order['payment_history'])
            for mid in touched:
                if user and user['payment_methods'].get(mid,{}).get('source') == 'gift_card':
                    key=(order['user_id'],mid)
                    if key in shared_balances: balance_hazard=True
                    shared_balances.add(key)
            if not errors:
                new_status = {'cancel_pending_order':'cancelled','modify_pending_order_items':'pending (item modified)',
                              'return_delivered_order_items':'return requested','exchange_delivered_order_items':'exchange requested'}.get(name)
                if new_status: order['status']=new_status
    # Discovery is separate from DB independence: concrete IDs might have been
    # guessed without seeing the earlier call's result. Do not infer invalidity.
    prefix = json.dumps(row['messages'],ensure_ascii=False)
    not_previsible = sum(1 for c in row['answer']['tool_calls'] if c['function']['name'] in ENTITY_MODELS
        and c['function']['arguments'][ENTITY_MODELS[c['function']['name']][1]] not in prefix)
    return {'semantic_guard_issues':sorted(errors),'same_order_after_write':dependency,
            'shared_gift_card_hazard':balance_hazard,'lookup_id_not_previsible_count':not_previsible}


def following_observations(row, dialog):
    messages = dialog['messages']; n = len(row['messages']); count = len(row['answer']['tool_calls'])
    if n >= len(messages) or messages[n] != row['answer']: return []
    results = messages[n+1:n+1+count]
    return results if len(results)==count and all(m['role']=='tool' for m in results) else []


def source_probe(row, dialog, tokenizer, tools, validators):
    """Execute unchanged real target against a labelled observation-backed fixture.

    This is NOT the unavailable original SFT database. Begin with a deep copy of
    an available Retail snapshot and replace only real observed entity records.
    For read-only targets, their recorded later reads may fill missing entities:
    explicitly circular as semantic validation, useful only for protocol replay.
    Writes use pre-target observations only, and only prefixes without any writes.
    """
    record, snapshot = baseline()
    source_obs = following_observations(row,dialog)
    readonly = all(c['function']['name'] not in WRITES for c in row['answer']['tool_calls'])
    previous_writes = any(c['function']['name'] in WRITES for m in row['messages'] for c in m.get('tool_calls',[]))
    if previous_writes: return None
    entities = observed_entities(row['messages'])
    future_filled = []
    if readonly:
        later = observed_entities(source_obs)
        for kind in entities:
            for key, body in later[kind].items():
                if key not in entities[kind]: entities[kind][key]=body; future_filled.append((kind,key))
    # Refuse execution when the target's entity requirements lack source evidence.
    for c in row['answer']['tool_calls']:
        args=c['function']['arguments']; name=c['function']['name']
        if 'order_id' in args and args['order_id'] not in entities['orders']: return None
        if 'user_id' in args and args['user_id'] not in entities['users']: return None
        if 'product_id' in args and args['product_id'] not in entities['products']: return None
        if name in WRITES and 'order_id' in args:
            order=entities['orders'][args['order_id']]
            if order['user_id'] not in entities['users']: return None
            if 'new_item_ids' in args and any(i['product_id'] not in entities['products'] for i in order['items'] if i['item_id'] in args['item_ids']): return None
    db = snapshot.db.model_dump(mode='json')
    for kind, values in entities.items(): db[kind].update(values)
    db = RetailDB.model_validate(db)
    fixture_hash=get_pydantic_hash(db)
    env=get_environment(db=db.model_copy(deep=True))
    prepared=tokenizer.prepare(row['messages'],row['answer'],tools)
    decoded=tokenizer.tokenizer.decode([x for x in prepared['labels'] if x!=-100],skip_special_tokens=False)
    assistant=parse_completion(decoded,validators,row['sample_id'])
    response=execute_batch(env,assistant)
    observations=response.tool_messages
    context=context_batch(assistant,observations)
    next_prompt=tokenizer.render(row['messages']+context,tools,True)
    assert next_prompt.count('<tool_response>') >= len(observations)
    native_history=[assistant,*observations]
    replay=get_environment(db=db.model_copy(deep=True))
    replay.set_state(initialization_data=None, initialization_actions=None, message_history=native_history)
    assert get_pydantic_hash(replay.tools.db)==get_pydantic_hash(env.tools.db)
    assert get_pydantic_hash(db)==fixture_hash and get_pydantic_hash(snapshot.db)==snapshot.content_hash
    expected_by_id={m['tool_call_id']:m for m in source_obs}
    comparisons=[]
    for original, actual in zip(row['answer']['tool_calls'],observations):
        expected=expected_by_id.get(original['id'])
        if expected is None: comparisons.append('source_observation_unavailable');continue
        try: wanted=json.loads(expected['content']);got=json.loads(actual.content)
        except (ValueError,TypeError): wanted=expected['content'];got=actual.content
        comparisons.append('equal' if wanted==got else 'different')
    summary={'sample_id':row['sample_id'],'source_dialog_id':row['source_dialog_id'],
        'tool_names':[c.name for c in assistant.tool_calls],'mixed':bool(assistant.content),
        'calls':len(observations),'errors':sum(m.error for m in observations),
        'source_result_comparisons':comparisons,'fixture_initial_hash':fixture_hash,
        'fixture_basis':'pre-target observations plus future read observations' if future_filled else 'pre-target observations only',
        'future_read_entities_filled':len(future_filled),'native_replay_db_equal':True,
        'full_original_episode_replay':'UNAVAILABLE_ORIGINAL_INITIAL_DB',
        'strict_communication_compatible':not bool(assistant.content)}
    write_json(PRIVATE/'source_probes'/f"{row['sample_id']}.json",{'summary':summary,
        'source_pointer':{k:row[k] for k in ('source_line','source_row_sha256','turn_index')},
        'observed_entities':entities,'native_messages':[m.model_dump(mode='json') for m in native_history],
        'source_observations':source_obs,'context':context,'next_prompt_sha256':digest(next_prompt)})
    return summary


def main():
    start=time.perf_counter(); PRIVATE.mkdir(parents=True,exist_ok=True)
    before=read_json(PRIVATE/'immutable_before.json')
    assert all(file_hash(ROOT/p)==h for p,h in before.items()), 'Frozen evidence changed before this check'
    assert subprocess.check_output(['git','-C','external/tau2-bench','rev-parse','HEAD'],text=True).strip()==ENVIRONMENT_SHA
    assert not subprocess.check_output(['git','-C','external/tau2-bench','status','--porcelain'],text=True).strip()
    tools=read_json(ROOT/'data/private/stage2/tools.json');validators=tool_validators(tools);tokenizer=QwenTokenizer()
    dialogs={d['id']:d for d in read_jsonl(ROOT/'data/private/stage2/dialog_features.jsonl')}
    assignments=read_json(ROOT/'data/private/stage2/assignments.json')['sft']
    rows=[r for r in read_jsonl(ROOT/'data/private/stage2/normalized_source.jsonl') if len(r['answer'].get('tool_calls',[]))>1]
    assert len(rows)==1489
    counts=Counter();patterns=Counter();audit=[]
    for i,row in enumerate(rows):
        functions=[c['function'] for c in row['answer']['tool_calls']]
        nwrite=sum(f['name'] in WRITES for f in functions)
        category='readonly' if nwrite==0 else 'multiple_writes' if nwrite==len(functions) else 'mixed_read_write'
        # multiple_writes covers >=2 writes; all actual mixed batches have one write.
        counts[category]+=1;patterns[tuple(f['name'] for f in functions)]+=1
        mixed=bool(row['answer']['content'].strip());counts['mixed_text']+=mixed
        counts[f'{category}_mixed_text']+=mixed
        counts[f"split_{assignments[row['source_dialog_id']]}"]+=1
        counts[f"split_{assignments[row['source_dialog_id']]}_mixed_text"]+=mixed
        flags=semantic_flags(row)
        for flag in ('same_order_after_write','shared_gift_card_hazard'):counts[flag]+=flags[flag]
        counts['lookup_id_not_previsible_samples']+=bool(flags['lookup_id_not_previsible_count'])
        counts['semantic_guard_samples']+=bool(flags['semantic_guard_issues'])
        for issue in flags['semantic_guard_issues']:counts['semantic_'+issue]+=1
        schema_errors=[]
        for fn in functions:
            if fn['name'] not in validators or not validators[fn['name']].is_valid(fn['arguments']):schema_errors.append(fn['name'])
        counts['schema_error_samples']+=bool(schema_errors)
        # Real pinned tokenizer, full training projection, actual supervised target.
        prepared=tokenizer.prepare(row['messages'],row['answer'],tools)
        decoded=tokenizer.tokenizer.decode([x for x in prepared['labels'] if x!=-100],skip_special_tokens=False)
        assert parse_serialized_calls(decoded)==functions
        native=parse_completion(decoded,validators,row['sample_id'])
        assert [{'name':c.name,'arguments':c.arguments} for c in native.tool_calls]==functions
        assert (native.content or '')==row['answer']['content'].strip()
        counts['tokenizer_parser_roundtrip_passed']+=1
        counts['mask_passed']+=1
        counts['strict_native_protocol_compatible']+=not mixed
        counts['known_protocol_or_semantic_issue_samples']+=mixed or bool(flags['semantic_guard_issues'])
        counts['protocol_and_checked_guards_clear']+=not mixed and not flags['semantic_guard_issues']
        counts['protocol_or_ordering_balance_risk_samples']+=mixed or flags['same_order_after_write'] or flags['shared_gift_card_hazard']
        source_obs=following_observations(row,dialogs[row['source_dialog_id']])
        counts['complete_recorded_response_batch']+=bool(source_obs)
        source_error=False;association_error=False
        for call,obs in zip(row['answer']['tool_calls'],source_obs):
            assert call['id']==obs['tool_call_id']
            if obs['content'].startswith('Error:'):source_error=True
            try: body=json.loads(obs['content'])
            except (ValueError,TypeError):continue
            fn=call['function']
            if fn['name'] in ENTITY_MODELS and isinstance(body,dict):
                key=ENTITY_MODELS[fn['name']][1]
                if body.get(key)!=fn['arguments'][key]:association_error=True
        counts['source_error_response_samples']+=source_error
        counts['source_payload_association_mismatch_samples']+=association_error
        counts['full_original_replay_unavailable']+=not bool(dialogs[row['source_dialog_id']]['compatible_snapshots'])
        audit.append({'sample_id':row['sample_id'],'source_line':row['source_line'],'source_row_sha256':row['source_row_sha256'],
            'source_dialog_id':row['source_dialog_id'],'turn_index':row['turn_index'],'split':assignments[row['source_dialog_id']],
            'category':category,'call_count':len(functions),'tool_names':[f['name'] for f in functions],
            'mixed_text':mixed,'strict_protocol_compatible':not mixed,'schema_errors':schema_errors,**flags,
            'recorded_response_batch':len(source_obs),'source_error_response':source_error,
            'source_payload_association_mismatch':association_error,'full_original_replay':'UNAVAILABLE_ORIGINAL_INITIAL_DB',
            'tokenizer_parser_and_loss_mask':'PASS'})
        if (i+1)%300==0: print(json.dumps({'audited':i+1}),flush=True)
    write_jsonl(PRIVATE/'target_audit.jsonl',audit)
    # Representative real batches, not complete source episodes. Choose the first
    # reconstructable instance per pattern/mixed flag, plus every semantic issue.
    selected=[];seen=set()
    for row,entry in zip(rows,audit):
        key=(tuple(entry['tool_names']),entry['mixed_text'])
        if key in seen or len(selected)>=18:continue
        result=source_probe(row,dialogs[row['source_dialog_id']],tokenizer,tools,validators)
        if result is not None:selected.append(result);seen.add(key)
    # Ensure coverage that a first-N list of common patterns would miss.
    seen_categories=set()
    for row,entry in zip(rows,audit):
        keys=[]
        if entry['call_count']==5:keys.append('five_calls')
        if entry['tool_names']==['get_product_details']*3:keys.append('three_product_reads')
        if entry['tool_names']==['calculate']*2:keys.append('two_calculations')
        if entry['mixed_text'] and entry['category']=='multiple_writes':keys.append('mixed_text_writes')
        if entry['same_order_after_write']:keys.append('same_order_after_write')
        if entry['shared_gift_card_hazard']:keys.append('shared_gift_card_hazard')
        needed=[k for k in keys if k not in seen_categories]
        if not needed:continue
        existing=next((p for p in selected if p['sample_id']==row['sample_id']),None)
        result=existing or source_probe(row,dialogs[row['source_dialog_id']],tokenizer,tools,validators)
        if result:
            result['coverage']=keys
            if not existing:selected.append(result)
            seen_categories.update(keys)
    semantic_probes=[]
    for row,entry in zip(rows,audit):
        if entry['semantic_guard_issues']:
            result=source_probe(row,dialogs[row['source_dialog_id']],tokenizer,tools,validators)
            if result is not None:semantic_probes.append(result)
    record,snapshot=baseline();pids=list(snapshot.db.products)[:2]
    readonly=AssistantMessage(role='assistant',tool_calls=[ToolCall(id=f'native_read_{i}',name='get_product_details',arguments={'product_id':p}) for i,p in enumerate(pids)])
    native=[]
    for name,options in [('sync',{'evaluate':True}),('async_batch',{'async_batch':True})]:
        probe=native_probe(readonly,**options)
        assert len(probe['observations'])==2 and not any(m.error for m in probe['observations'])
        assert [m['tool_call_id'] for m in probe['tool_context']]==[c.id for c in readonly.tool_calls]
        write_json(PRIVATE/f'native_{name}.json',{'summary':probe['summary'],
            'native_messages':[m.model_dump(mode='json') for m in probe['trajectory']], 'captured':probe['captured']})
        public_summary={k:v for k,v in probe['summary'].items() if k!='reward_info'}
        if probe['summary']['reward_info'] is not None:
            public_summary['official_reward_diagnostic']=probe['summary']['reward_info']['reward']
        native.append({'name':name,**public_summary})
    mixed=readonly.model_copy(update={'content':'Synthetic mixed-content fixture.'},deep=True)
    for strict in (True,False):
        probe=native_probe(mixed,strict=strict)
        assert len(probe['observations'])==(0 if strict else 2)
        native.append({'name':f'mixed_strict_{strict}',**probe['summary']})
    invariant_failures=[p for p,h in before.items() if file_hash(ROOT/p)!=h]
    assert not invariant_failures
    output={'status':'PASS_WITH_PROTOCOL_AND_POLICY_RISKS','environment_sha':ENVIRONMENT_SHA,
        'model_calls':0,'network_guard':'external sockets denied; Windows asyncio local self-pipe permitted','total_multi_targets':len(rows),
        'distinct_source_dialogs':len({r['source_dialog_id'] for r in rows}),
        'counts':dict(counts),'patterns':[{'tools':list(k),'samples':v} for k,v in patterns.most_common()],
        'representative_source_probes':selected,'semantic_guard_probes':semantic_probes,'native_probes':native,
        'immutable_files_checked':len(before),'immutable_failures':invariant_failures,
        'original_stage2_report_sha256':before['reports/stage2/STAGE2_REPORT.md'],
        'seconds':round(time.perf_counter()-start,3),'private_evidence':'data/private/stage2/multi_tool_compatibility/target_audit.jsonl'}
    write_json(REPORTS/'multi_tool_audit.json',output)
    print(json.dumps({'completed':True,'counts':dict(counts),'source_probes':len(selected),'seconds':output['seconds']}),flush=True)


if __name__=='__main__':main()
