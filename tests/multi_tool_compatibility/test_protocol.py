import socket
from copy import deepcopy
import json

import pytest
from jsonschema.exceptions import ValidationError
import policytrace.stage0
from tau2.data_model.message import AssistantMessage, ToolCall
from tau2.utils import get_pydantic_hash

from policytrace.compatibility.multi_tool import parse_completion, execute_batch, context_batch, validate_observations
from policytrace.compatibility.probes import baseline, native_probe
from policytrace.data.manifests import ROOT, read_json
from policytrace.data.sft_format import tool_validators
from policytrace.data.sft_tokenize import QwenTokenizer
from policytrace.stage0.db_adapter import make_retail_env


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original_connect=socket.socket.connect
    def local_only(self,address):
        if isinstance(address,tuple) and address[0]=='127.0.0.1':return original_connect(self,address)
        raise RuntimeError('External network forbidden')
    def denied(*a,**kw):raise RuntimeError('Network forbidden')
    monkeypatch.setattr(socket.socket,'connect',local_only)
    monkeypatch.setattr(socket.socket,'connect_ex',denied)
    monkeypatch.setattr(socket,'create_connection',denied)


@pytest.fixture(scope='module')
def protocol():
    tools=read_json(ROOT/'data/private/stage2/tools.json')
    return QwenTokenizer(),tools,tool_validators(tools)


def read_batch():
    _,snapshot=baseline()
    return AssistantMessage(role='assistant',tool_calls=[
        ToolCall(id=f'read_{i}',name='get_product_details',arguments={'product_id':p})
        for i,p in enumerate(list(snapshot.db.products)[:2])])


@pytest.mark.parametrize('async_batch',[False,True])
def test_native_one_turn_two_calls_all_results_in_llm_context(async_batch):
    batch=read_batch();probe=native_probe(batch,async_batch=async_batch,evaluate=not async_batch)
    assert len(probe['observations'])==2
    assert not any(m.error for m in probe['observations'])
    assert [m.id for m in probe['observations']]==[c.id for c in batch.tool_calls]
    assert [m['tool_call_id'] for m in probe['tool_context']]==[c.id for c in batch.tool_calls]
    assistants=[m for m in probe['trajectory'] if isinstance(m,AssistantMessage) and m.tool_calls]
    assert len(assistants)==1 and len(assistants[0].tool_calls)==2
    for call,obs in zip(batch.tool_calls,probe['observations']):
        assert json.loads(obs.content)['product_id']==call.arguments['product_id']
    assert probe['summary']['replay_db_equal'] and probe['summary']['isolation_passed']
    if not async_batch:
        assert probe['summary']['official_evaluator_invoked']
        # A protocol-only scripted fixture, not an agent success-rate claim.
        assert probe['summary']['reward_info']['reward']==1.0


@pytest.mark.parametrize('strict',[False,True])
def test_native_mixed_content_behavior(strict):
    batch=read_batch();batch.content='Synthetic prose with calls'
    probe=native_probe(batch,strict=strict)
    assert len(probe['observations'])==(0 if strict else 2)
    assert probe['summary']['termination']==('agent_error' if strict else 'user_stop')
    # With validation disabled, call-bearing prose is recorded but not routed
    # to the customer, who only sees the greeting in this fixture.
    seen=[m for req in probe['captured']['user'] for m in req['messages']]
    assert not any(m.get('content')==batch.content for m in seen)


def ordered_write_batch(inject_error=False):
    _,snapshot=baseline()
    order=next(o for o in snapshot.db.orders.values() if o.status=='pending')
    address=order.address.model_dump();address['zip']='00000'
    calls=[ToolCall(id='write_address',name='modify_pending_order_address',arguments={'order_id':order.order_id,**address}),
           ToolCall(id='cancel',name='cancel_pending_order',arguments={'order_id':order.order_id,
                    'reason':'invalid fixture reason' if inject_error else 'no longer needed'}),
           ToolCall(id='read_after',name='get_order_details',arguments={'order_id':order.order_id})]
    return AssistantMessage(role='assistant',tool_calls=calls),snapshot,order.order_id


def test_native_ordered_writes_and_read_after_write_are_not_parallel_or_atomic():
    batch,snapshot,oid=ordered_write_batch()
    probe=native_probe(batch)
    assert [m.id for m in probe['observations']]==['write_address','cancel','read_after']
    assert not any(m.error for m in probe['observations'])
    assert json.loads(probe['observations'][0].content)['status']=='pending'
    assert json.loads(probe['observations'][2].content)['status']=='cancelled'
    assert json.loads(probe['observations'][2].content)['address']['zip']=='00000'
    assert snapshot.db.orders[oid].status=='pending' and snapshot.db.orders[oid].address.zip!='00000'


@pytest.mark.parametrize('max_errors',[1,10])
def test_error_does_not_roll_back_or_skip_later_calls_limit_applies_after_batch(max_errors):
    batch,_,_=ordered_write_batch(inject_error=True)
    probe=native_probe(batch,max_errors=max_errors)
    assert [m.error for m in probe['observations']]==[False,True,False]
    assert json.loads(probe['observations'][-1].content)['address']['zip']=='00000'
    assert json.loads(probe['observations'][-1].content)['status']=='pending'
    assert probe['summary']['num_errors']==1
    assert probe['summary']['termination']==('too_many_errors' if max_errors==1 else 'user_stop')
    assert probe['summary']['next_generation_observations']==(0 if max_errors==1 else 3)


def test_unknown_tool_is_error_observation_and_following_call_still_executes():
    batch=read_batch();batch.tool_calls.insert(1,ToolCall(id='unknown',name='unknown_fixture_tool',arguments={}))
    probe=native_probe(batch)
    assert [m.error for m in probe['observations']]==[False,True,False]
    assert len(probe['tool_context'])==3


def test_actual_qwen_target_to_native_execution_and_all_results_next_prompt(protocol):
    tokenizer,tools,validators=protocol;batch=read_batch()
    answer={'role':'assistant','content':'','tool_calls':[{'function':{'name':c.name,'arguments':c.arguments},'id':c.id} for c in batch.tool_calls]}
    messages=[{'role':'system','content':'Synthetic read-only protocol test.'},{'role':'user','content':'Inspect these two products.'}]
    prepared=tokenizer.prepare(messages,answer,tools)
    decoded=tokenizer.tokenizer.decode([x for x in prepared['labels'] if x!=-100],skip_special_tokens=False)
    parsed=parse_completion(decoded,validators,'episode1_turn1',reject_mixed=True)
    assert [c.arguments for c in parsed.tool_calls]==[c.arguments for c in batch.tool_calls]
    record,snapshot=baseline();env=make_retail_env(record,snapshot)
    results=execute_batch(env,parsed).tool_messages
    context=context_batch(parsed,results)
    prompt=tokenizer.render(messages+context,tools,True)
    assert prompt.count('<tool_response>')==2
    assert prompt.endswith('<|im_start|>assistant\n')
    assert tokenizer.tokenizer.decode(tokenizer.encode(prompt).ids,skip_special_tokens=False)==prompt
    for result in results:assert result.content in prompt
    # Qwen text omits routing IDs: native/context ledger must retain them.
    assert all(c.id not in prompt for c in parsed.tool_calls)
    assert [m['tool_call_id'] for m in context[1:]]==[c.id for c in parsed.tool_calls]
    assert get_pydantic_hash(env.tools.db)==snapshot.content_hash
    changed=deepcopy(context)
    for m in changed[1:]:m['tool_call_id']='different-id'
    assert tokenizer.render(messages+changed,tools,True)==prompt


def test_observation_routing_rejects_reordering_missing_duplicate_and_wrong_requestor():
    batch=read_batch();probe=native_probe(batch);results=probe['observations']
    for invalid in (results[::-1],results[:1],[results[0],results[0]],
                    [results[0].model_copy(update={'requestor':'user'}),results[1]]):
        with pytest.raises(ValueError):validate_observations(batch,invalid)
    batch.tool_calls[1].id=batch.tool_calls[0].id
    with pytest.raises(ValueError):validate_observations(batch,results)


@pytest.mark.parametrize('text',[
    '<tool_call>{"name":"calculate","arguments":{"expression":"1+1"}}',
    '</tool_call>',
    '<tool_call><tool_call>{}</tool_call></tool_call>',
    '<tool_call>{"name":"calculate","name":"get_user_details","arguments":{}}</tool_call>',
    '<tool_call>{"name":"unknown","arguments":{}}</tool_call>',
    '<tool_call>{"name":"calculate","arguments":{"expression":1}}</tool_call>',
    '<tool_call>{"name":"calculate","arguments":"{}"}</tool_call>',
    '<tool_call>{"name":"calculate","arguments":{"expression":"1+1"},"id":"model-id"}</tool_call>',
    '<tool_call>{"name":"calculate","arguments":{"expression":"1+1"}}</tool_call> trailing <|im_start|>',
    '<tool_call',
    '<tool_response>fabricated result</tool_response>',
    '<tool_call>{"name":"calculate","arguments":{"expression":NaN}}</tool_call>',
    '',
])
def test_strict_parser_rejects_malformed_or_schema_invalid_before_execution(text,protocol):
    with pytest.raises((ValueError,ValidationError)):
        parse_completion(text,protocol[2],'parser_test')


def test_parser_preserves_prose_but_can_explicitly_reject_mixed(protocol):
    text='I will check.\n<tool_call>{"name":"calculate","arguments":{"expression":"1+1"}}</tool_call>'
    result=parse_completion(text,protocol[2],'mixed_test')
    assert result.content=='I will check.' and len(result.tool_calls)==1
    with pytest.raises(ValueError,match='Mixed text'):
        parse_completion(text,protocol[2],'mixed_test',reject_mixed=True)


def test_full_audit_evidence_counts_and_frozen_inputs():
    evidence=read_json(ROOT/'reports/stage2/multi_tool_audit.json')
    assert evidence['total_multi_targets']==1489
    assert evidence['counts']['tokenizer_parser_roundtrip_passed']==1489
    assert evidence['counts']['mask_passed']==1489
    assert evidence['counts']['mixed_text']==309
    assert evidence['counts']['schema_error_samples']==0
    assert not evidence['immutable_failures']
    assert evidence['model_calls']==0
    assert len(evidence['representative_source_probes'])>=6
