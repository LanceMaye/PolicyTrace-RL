from collections import Counter
import gzip
import hashlib
import json

import pytest

from policytrace.data.manifests import ROOT,read_json,read_jsonl,file_hash
from policytrace.data.sft_policy_view import target_reasons,partition_split


@pytest.mark.parametrize('answer,expected',[
    ({'role':'assistant','content':'Text only'},[]),
    ({'role':'assistant','content':'  ','tool_calls':[{}]},[]),
    ({'role':'assistant','content':'','tool_calls':[{},{}]},['multiple_tool_calls']),
    ({'role':'assistant','content':'Text','tool_calls':[{}]},['text_and_tool_calls']),
    ({'role':'assistant','content':'Text','tool_calls':[{},{}]},['multiple_tool_calls','text_and_tool_calls']),
])
def test_target_only_policy_rules_and_overlap(answer,expected):
    assert target_reasons(answer)==expected


def fixture_files(tmp_path,tokenizer,tools):
    fn={'id':'fixture_call','type':'function','function':{'name':'calculate','arguments':{'expression':'2+2'}}}
    history=[{'role':'system','content':'SYNTHETIC fixture policy.'},
             {'role':'user','content':'SYNTHETIC request.'},
             {'role':'assistant','content':'Historical mixed text','tool_calls':[fn,dict(fn,id='fixture_call_2')]},
             {'role':'tool','content':'4.0','tool_call_id':'fixture_call'},
             {'role':'tool','content':'4.0','tool_call_id':'fixture_call_2'}]
    answers=[{'role':'assistant','content':'Text target'},
             {'role':'assistant','content':'','tool_calls':[fn]},
             {'role':'assistant','content':'','tool_calls':[fn,dict(fn,id='fixture_second')]},
             {'role':'assistant','content':'Mixed target','tool_calls':[fn]}]
    rows=[];tokens=[]
    for i,answer in enumerate(answers):
        provenance={'sample_id':f'fixture_{i}','source_dialog_id':'fixture_dialog','source_line':i,'source_row_sha256':str(i),'turn_index':i}
        rows.append({'messages':history,'answer':answer,'provenance':provenance})
        tokens.append({**tokenizer.prepare(history,answer,tools),'provenance':provenance})
    row_path=tmp_path/'rows.jsonl';token_path=tmp_path/'tokens.jsonl.gz'
    row_path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    with gzip.open(token_path,'wt',encoding='utf-8') as stream:
        stream.write(''.join(json.dumps(t)+'\n' for t in tokens))
    return row_path,token_path,rows,tokens


def test_partition_preserves_tokens_history_and_exact_target(tmp_path,tokenizer,tools):
    source_rows,source_tokens,rows,tokens=fixture_files(tmp_path,tokenizer,tools)
    manifest,decisions=partition_split(source_rows,source_tokens,tmp_path/'output','train',tokenizer.eos)
    assert manifest['sample_ids']=={'main':['fixture_0','fixture_1'],'quarantine':['fixture_2','fixture_3']}
    assert all(d['history_flags']==['multiple_tool_calls','text_and_tool_calls'] for d in decisions)
    for view,indices in [('main',[0,1]),('quarantine',[2,3])]:
        actual_rows=list(read_jsonl(manifest['artifacts'][view]['rows']['path']))
        with gzip.open(manifest['artifacts'][view]['tokens']['path'],'rt',encoding='utf-8') as stream:
            actual_tokens=[json.loads(line) for line in stream]
        assert actual_rows==[rows[i] for i in indices]
        assert actual_tokens==[tokens[i] for i in indices]


@pytest.mark.parametrize('failure',['wrong_provenance','bad_mask','missing_token','duplicate_id'])
def test_bad_source_pairing_or_mask_is_rejected(tmp_path,tokenizer,tools,failure):
    source_rows,source_tokens,rows,tokens=fixture_files(tmp_path,tokenizer,tools)
    if failure=='wrong_provenance':tokens[0]['provenance']={**tokens[0]['provenance'],'sample_id':'wrong'}
    elif failure=='bad_mask':tokens[0]['labels'][0]=tokens[0]['input_ids'][0]
    elif failure=='missing_token':tokens.pop()
    else:
        rows[1]['provenance']=rows[0]['provenance'];tokens[1]['provenance']=tokens[0]['provenance']
    source_rows.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    with gzip.open(source_tokens,'wt',encoding='utf-8') as stream:stream.write(''.join(json.dumps(t)+'\n' for t in tokens))
    with pytest.raises(ValueError):partition_split(source_rows,source_tokens,tmp_path/'bad-output','train',tokenizer.eos)


def test_real_policy_view_partition_history_and_frozen_dialog_split():
    root=ROOT/'data/processed/stage2/policy_main_v1';manifest=read_json(root/'manifest.json')
    all_ids=set();dids={}
    for split,expected in [('train',(8652,1496)),('val',(967,172))]:
        entries=manifest['splits'][split]
        assert (entries['counts']['main'],entries['counts']['quarantine'])==expected
        original=read_json(ROOT/f'data/splits/stage2/sft_{split}.json')
        ids=set(entries['sample_ids']['main'])|set(entries['sample_ids']['quarantine'])
        assert ids==set(original['sample_ids']) and not all_ids & ids
        all_ids.update(ids);dids[split]=set()
        for view in ('main','quarantine'):
            for row in read_jsonl(ROOT/entries['artifacts'][view]['rows']['path']):
                assert bool(target_reasons(row['answer']))==(view=='quarantine')
                dids[split].add(row['provenance']['source_dialog_id'])
    assert not dids['train'] & dids['val']
    assert not manifest['retokenized'] and not manifest['policy_modified']
    # This is the preserved v1 historical view, whose policy now lives in its backup.
    assert file_hash(ROOT/'configs/policy/backups/retail.e33e9511.original.md')==manifest['policy_sha256']


def test_all_emitted_row_and_token_lines_equal_source_receipts_and_no_loss():
    manifest=read_json(ROOT/'data/processed/stage2/policy_main_v1/manifest.json')
    receipts=list(read_jsonl(ROOT/'data/private/stage2/policy_main_v1/decisions.jsonl'))
    expected={(r['source_split'],r['view'],r['provenance']['sample_id']):r for r in receipts}
    actual=set()
    for split,entries in manifest['splits'].items():
        for view,artifacts in entries['artifacts'].items():
            with (ROOT/artifacts['rows']['path']).open('rb') as rows,gzip.open(ROOT/artifacts['tokens']['path'],'rb') as tokens:
                for sid in entries['sample_ids'][view]:
                    key=(split,view,sid);receipt=expected[key]
                    row_line=next(rows);token_line=next(tokens)
                    assert json.loads(row_line)['provenance']['sample_id']==sid
                    assert hashlib.sha256(row_line).hexdigest()==receipt['row_line_sha256']
                    assert hashlib.sha256(token_line).hexdigest()==receipt['token_line_sha256']
                    assert key not in actual;actual.add(key)
                assert next(rows,None) is None and next(tokens,None) is None
    assert actual==set(expected) and len(actual)==11287


def test_historical_input_files_unchanged_and_active_config_points_to_main():
    before=read_json(ROOT/'data/private/stage2/policy_main_v1/immutable_inputs.json')
    policy_path='external/tau2-bench/data/tau2/domains/retail/policy.md'
    archived={policy_path:'configs/policy/backups/retail.e33e9511.original.md',
              'README.md':'docs/history/README.stage2_original.md'}
    assert all(file_hash(ROOT/archived.get(path,path))==sha for path,sha in before.items())
    config=read_json(ROOT/'configs/data/sft_main_view.json')
    manifest=read_json(ROOT/config['manifest'])
    for split in ('train','val'):
        assert config[f'{split}_tokens']==manifest['splits'][split]['artifacts']['main']['tokens']['path']
        assert file_hash(ROOT/config[f'{split}_tokens'])==manifest['splits'][split]['artifacts']['main']['tokens']['sha256']
