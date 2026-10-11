"""Acceptance for the user-approved SFT policy transition; no real model calls."""
from copy import deepcopy
import json

import pytest

from policytrace.data.manifests import ROOT, read_json, read_jsonl, file_hash
from policytrace.data.sft_policy_view import target_reasons
from policytrace.policy import POLICY_VERSION, POLICY_SHA256, ORIGINAL_FILE_SHA256, verify_fork, active_policy


@pytest.mark.parametrize('answer,expected',[
    ({'role':'assistant','content':'','tool_calls':[{},{}]},[]),
    ({'role':'assistant','content':'  ','tool_calls':[{},{}]},[]),
    ({'role':'assistant','content':'text','tool_calls':[{},{}]},['text_and_tool_calls']),
    ({'role':'assistant','content':'text','tool_calls':[{}]},['text_and_tool_calls']),
])
def test_mixed_only_target_gate(answer,expected):
    assert target_reasons(answer,max_tool_calls=None)==expected


def test_exact_source_policy_installed_and_original_preserved():
    config=active_policy()
    source=next(read_jsonl(ROOT/'data/processed/stage2/sft_train.jsonl'))
    policy=source['messages'][0]['content'].rsplit('<policy>',1)[1].split('</policy>',1)[0]
    assert (ROOT/config['policy_source']).read_bytes()==policy.encode('utf-8')
    assert file_hash(ROOT/config['original_backup'])==ORIGINAL_FILE_SHA256
    state=verify_fork()
    assert state['policy_version']==POLICY_VERSION and state['policy_sha256']==POLICY_SHA256
    assert state['authorized_policy_patch_only'] and not state['upstream_working_tree_clean']
    assert 'at most make one tool' not in policy
    assert "you'd better list the action details" in policy
    assert 'should not respond to the user at the same time' in policy


@pytest.mark.parametrize('drift',['code','extra','staged','commit'])
def test_fork_integrity_rejects_unapproved_changes(monkeypatch,drift):
    from policytrace import policy
    original=policy._git
    def altered(root,*args):
        if drift=='code' and args==('diff','--name-only','HEAD'):
            return (policy.POLICY_REL+'\nsrc/tau2/evaluator/evaluator.py\n').encode()
        if drift=='extra' and args==('ls-files','--others','--exclude-standard'):return b'unapproved.py\n'
        if drift=='staged' and args==('diff','--cached','--name-only'):return (policy.POLICY_REL+'\n').encode()
        if drift=='commit' and args==('rev-parse','HEAD'):return b'wrong_commit\n'
        return original(root,*args)
    monkeypatch.setattr(policy,'_git',altered)
    with pytest.raises(ValueError):policy.verify_fork()


def test_runtime_policy_drift_fails_closed_in_temporary_copy(tmp_path):
    config=active_policy()
    for name in ['configs/policy/custom_retail_v1.json',config['policy_source'],config['original_backup']]:
        dest=tmp_path/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
    runtime=tmp_path/'external/tau2-bench/data/tau2/domains/retail/policy.md'
    runtime.parent.mkdir(parents=True,exist_ok=True)
    runtime.write_bytes((ROOT/config['policy_source']).read_bytes()+b'Unexpected policy change')
    with pytest.raises(ValueError,match='Installed Retail policy'):active_policy(tmp_path)


def test_active_view_recovers_only_pure_multi_and_preserves_frozen_splits():
    config=read_json(ROOT/'configs/data/sft_main_view.json')
    assert config==read_json(ROOT/'configs/data/sft_mixed_only_v2.json')
    assert config['target_gate']['max_tool_calls'] is None
    manifest=read_json(ROOT/config['manifest'])
    assert manifest['source_quality_reincluded']==0 and manifest['source_quality_excluded_count']==108
    assert not manifest['retokenized'] and not manifest['target_or_history_modified']
    for split,expected in [('train',(9707,441,1055)),('val',(1080,59,113))]:
        entries=manifest['splits'][split]
        assert (entries['counts']['main'],entries['counts']['quarantine'],entries['protocol_audit']['counts']['multi_targets_checked'])==expected
        original=read_json(ROOT/f'data/splits/stage2/sft_{split}.json')
        assert set(entries['sample_ids']['main']+entries['sample_ids']['quarantine'])==set(original['sample_ids'])
        old=read_json(ROOT/'data/processed/stage2/policy_main_v1/manifest.json')['splits'][split]
        assert set(old['sample_ids']['main'])<=set(entries['sample_ids']['main'])
        for row in read_jsonl(ROOT/entries['artifacts']['quarantine']['rows']['path']):
            assert target_reasons(row['answer'],max_tool_calls=None)==['text_and_tool_calls']
        for row in read_jsonl(ROOT/entries['artifacts']['main']['rows']['path']):
            assert target_reasons(row['answer'],max_tool_calls=None)==[]


def test_every_new_row_and_token_line_matches_original_frozen_receipts():
    import gzip
    import hashlib
    original={r['provenance']['sample_id']:r for r in read_jsonl(ROOT/'data/private/stage2/policy_main_v1/decisions.jsonl')}
    manifest=read_json(ROOT/read_json(ROOT/'configs/data/sft_main_view.json')['manifest'])
    seen=set()
    for split,entries in manifest['splits'].items():
        for artifacts in entries['artifacts'].values():
            with (ROOT/artifacts['rows']['path']).open('rb') as rows,gzip.open(ROOT/artifacts['tokens']['path'],'rb') as tokens:
                for row_line,token_line in zip(rows,tokens,strict=True):
                    sid=json.loads(row_line)['provenance']['sample_id'];receipt=original[sid]
                    assert receipt['source_split']==split and sid not in seen
                    assert hashlib.sha256(row_line).hexdigest()==receipt['row_line_sha256']
                    assert hashlib.sha256(token_line).hexdigest()==receipt['token_line_sha256']
                    seen.add(sid)
    assert seen==set(original) and len(seen)==11287


@pytest.mark.parametrize('split',['train','val'])
def test_real_runtime_context_matches_reused_tokens_for_each_target_class(tokenizer,split):
    import gzip
    from policytrace.harness.context import ContextBuilder
    from policytrace.harness.agent_adapter import StudentAgentAdapter
    from policytrace.harness.model_client import DeterministicMock
    from policytrace.harness.runner import DevTaskPool
    from policytrace.stage0.db_adapter import make_retail_env
    from tau2.data_model.message import AssistantMessage,ToolCall,ToolMessage,UserMessage
    manifest=read_json(ROOT/read_json(ROOT/'configs/data/sft_main_view.json')['manifest'])
    entries=manifest['splits'][split]
    wanted={v['sample_id'] for v in entries['protocol_audit']['representatives'].values()}
    tokens={}
    with gzip.open(ROOT/entries['artifacts']['main']['tokens']['path'],'rt',encoding='utf-8') as f:
        for line in f:
            record=json.loads(line)
            if record['provenance']['sample_id'] in wanted:tokens[record['provenance']['sample_id']]=record
    record,snapshot=DevTaskPool().load('retail_152')
    env=make_retail_env(record,snapshot)
    baseline=StudentAgentAdapter(env.get_tools(),env.get_policy(),tokenizer,
        DeterministicMock(tokenizer,[]),'custom_context_acceptance',{})
    checked=set()
    for row in read_jsonl(ROOT/entries['artifacts']['main']['rows']['path']):
        sid=row['provenance']['sample_id']
        if sid not in wanted:continue
        history=[]
        for m in row['messages'][1:]:
            if m['role']=='assistant':
                calls=[ToolCall(id=c['id'],name=c['function']['name'],arguments=c['function']['arguments']) for c in m.get('tool_calls',[])]
                history.append(AssistantMessage(role='assistant',content=m['content'],tool_calls=calls or None))
            elif m['role']=='tool':history.append(ToolMessage(role='tool',id=m['tool_call_id'],content=m['content']))
            else:history.append(UserMessage(role='user',content=m['content']))
        builder=ContextBuilder(tokenizer,baseline.domain_policy,baseline.builder.tools,baseline.builder.system_prompt)
        visible=builder.build(history)
        token=tokens[sid]
        assert visible['prompt_token_ids']==token['input_ids'][:token['prompt_tokens']]
        assert visible['versions']['policy_sha256']==POLICY_SHA256
        assert all(label==-100 for label in token['labels'][:token['prompt_tokens']])
        checked.add(sid)
    assert checked==wanted and len(checked)==4
