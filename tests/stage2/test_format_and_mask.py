from copy import deepcopy
import pytest

from policytrace.data.sft_format import normalize_messages, visible_projection
from policytrace.data.sft_tokenize import parse_serialized_calls, validate_labels, pad_records
from policytrace.data.manifests import ROOT, read_jsonl


def conversation():
    # SYNTHETIC routing and privacy fixture.
    return [{'role':'system','content':'Follow the synthetic customer service policy.'},
        {'role':'user','content':'I need assistance.'},
        {'role':'assistant','content':'HISTORY_ASSISTANT_SENTINEL','reasoning':'HIDDEN_REASONING_SENTINEL'},
        {'role':'assistant','content':'','tool_calls':[{'name':'get_order_details','arguments':{'order_id':'synthetic'}}]},
        {'role':'tool','name':'get_order_details','content':'TOOL_OBSERVATION_SENTINEL'},
        {'role':'user','content':'USER_HISTORY_SENTINEL'}]


@pytest.mark.parametrize('form', ['text','flat','openai_json','multi'])
def test_qwen_real_tokens_only_target_body_and_eos(form,tokenizer,tools):
    a={'role':'assistant','content':'TARGET_ANSWER_SENTINEL','thinking':'PRIVATE_THINKING_SENTINEL'}
    if form in ('flat','multi'):
        a.update(content='',tool_calls=[{'name':'get_order_details','arguments':{'order_id':'synthetic'}}])
        if form=='multi': a['tool_calls'].append({'name':'get_user_details','arguments':{'user_id':'synthetic'}})
    elif form=='openai_json':
        a.update(content='',tool_calls=[{'id':'synthetic_id','type':'function','function':{'name':'get_order_details','arguments':'{"order_id":"synthetic"}'}}])
    history,answer,excluded=normalize_messages(conversation(),a)
    record=tokenizer.prepare(history,answer,tools)
    validate_labels(record,tokenizer.eos)
    assert record['native_full_encoding_equal']
    text=tokenizer.tokenizer.decode([x for x in record['labels'] if x!=-100],skip_special_tokens=False)
    for sentinel in ('HISTORY_ASSISTANT_SENTINEL','HIDDEN_REASONING_SENTINEL','PRIVATE_THINKING_SENTINEL','TOOL_OBSERVATION_SENTINEL','USER_HISTORY_SENTINEL'):
        assert sentinel not in text
    assert text.endswith('<|im_end|>')
    assert parse_serialized_calls(text)==[c['function'] for c in answer.get('tool_calls',[])]
    assert all(x==-100 for x in record['labels'][:record['prompt_tokens']])
    assert 'PRIVATE_THINKING_SENTINEL' not in tokenizer.render(history+[answer],tools)


def test_real_retail_tool_target_mask(tokenizer,tools):
    row=next(read_jsonl(ROOT/'data/private/stage2/normalized_source.jsonl'))
    view=visible_projection(row); tokens=tokenizer.prepare(view['messages'],view['answer'],tools)
    assert tokens['supervised_tokens']>1 and len(tokens['input_ids'])>tokens['supervised_tokens']
    assert 'source_metadata' not in view and 'excluded_nonstudent_fields' not in view
    # Parse the generated target, not instructional examples in the system tools section.
    target_text=tokenizer.tokenizer.decode([x for x in tokens['labels'] if x!=-100],skip_special_tokens=False)
    assert parse_serialized_calls(target_text)==[c['function'] for c in view['answer'].get('tool_calls',[])]


def test_padding_is_not_supervised(tokenizer,tools):
    a=tokenizer.prepare([{'role':'system','content':'synthetic policy'}],{'role':'assistant','content':'A'},tools)
    b=tokenizer.prepare([{'role':'system','content':'synthetic policy'}],{'role':'assistant','content':'A longer synthetic answer.'},tools)
    padded=pad_records([a,b],tokenizer.pad)
    assert len(padded[0]['input_ids'])==len(padded[1]['input_ids'])
    assert 0 in padded[0]['attention_mask']
    for r in padded: validate_labels(r,tokenizer.eos)


@pytest.mark.parametrize('kind',['wrong_length','history_supervised','all_masked','padding_supervised'])
def test_bad_masks_rejected(kind,tokenizer,tools):
    r=tokenizer.prepare([{'role':'system','content':'synthetic'}],{'role':'assistant','content':'answer'},tools)
    r=deepcopy(r)
    if kind=='wrong_length':r['labels'].pop()
    if kind=='history_supervised':r['labels'][0]=r['input_ids'][0]
    if kind=='all_masked':r['labels']=[-100]*len(r['labels'])
    if kind=='padding_supervised':r['attention_mask'][r['prompt_tokens']]=0
    with pytest.raises(ValueError):validate_labels(r,tokenizer.eos)


@pytest.mark.parametrize('answer',[{'role':'assistant','content':''},{'role':'user','content':'x'},
    {'role':'assistant','content':'','tool_calls':[{'name':'x','arguments':'invalid JSON'}]}])
def test_invalid_targets_are_not_training_examples(answer):
    with pytest.raises(ValueError): normalize_messages([{'role':'system','content':'synthetic'}],answer)


def test_orphan_tool_response_rejected():
    with pytest.raises(ValueError,match='orphan_tool_response'):
        normalize_messages([{'role':'system','content':'synthetic'},{'role':'tool','name':'calculate','content':'4'}],{'role':'assistant','content':'answer'})


def test_source_policy_protocol_only_adaptation(tokenizer,tools):
    policy='SYNTHETIC_BUSINESS_POLICY_SENTINEL'
    prompt=tokenizer.render([{'role':'system','content':'valid JSON only\n<policy>'+policy+'</policy>'}],tools,True)
    assert policy in prompt and 'valid JSON only' not in prompt
    assert '<tools>' in prompt and prompt.endswith('<|im_start|>assistant\n')
