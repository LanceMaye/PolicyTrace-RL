from copy import deepcopy
from types import SimpleNamespace
import json
import struct
import zipfile

import httpx
import pytest
from tau2.data_model.message import AssistantMessage

from policytrace.data.manifests import ROOT, canonical, digest, file_hash, read_json
from policytrace.harness.context import HarnessError
from policytrace.harness.model_client import ModelRequest
from policytrace.harness.fixtures import call
from policytrace.stage3_1 import cli
from policytrace.stage3_1.assets import verify_assets, RuntimeTaskPool, private_path, exclusive_json, LOCK
from policytrace.stage3_1.budget import RunBudget, BudgetedStudent
from policytrace.stage3_1.deepseek import DeepSeekProvider, DeepSeekUserSimulator
from policytrace.stage3_1.download import revision, tensor_header, main as download_main
from policytrace.stage3_1.protocol import Settings, settings, preflight, project_cost
from policytrace.stage3_1.student import TransformersQwenModelClient
from policytrace.stage3_1.runner import make_plan, run_episode
from policytrace.stage3_1.summary import summarize
from policytrace.stage3_1.sync import unpack, pack


def config():
    return Settings(local_model_dir='missing-local-model')


def priced():
    # Offline fixture rates, expressly not a quotation of current provider pricing.
    return config().user.model_copy(update={'input_cny_per_m':1.,'output_cny_per_m':2.,'price_verified_on':'fixture-only'}).model_dump()


def response(content='###STOP###'):
    return {'id':'offline-response','model':'deepseek-v4-pro','object':'chat.completion','created':0,
        'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':content}}],
        'usage':{'prompt_tokens':20,'completion_tokens':8,'total_tokens':28}}


def fixture_scripts():
    """Standalone cloud fixtures: only the ten E0 assets, no old private receipts/SFT."""
    _,snapshot=RuntimeTaskPool('dev',['retail_152']).load('retail_152')
    reads=[call('get_product_details',{'product_id':p}) for p in sorted(snapshot.db.products)[:2]]
    order=next(o for _,o in sorted(snapshot.db.orders.items()) if o.status=='pending')
    address=order.address.model_dump();address['zip']='00000'
    write=call('modify_pending_order_address',{'order_id':order.order_id,**address})
    bad=call('cancel_pending_order',{'order_id':order.order_id,'reason':'synthetic invalid reason'})
    read=call('get_order_details',{'order_id':order.order_id})
    return {'multi_read':([reads[0]+'\n'+reads[1],'Both lookups are complete.'],['Synthetic read-only diagnostic.','###STOP###']),
        'mixed':(['Synthetic mixed content '+reads[0]],['Synthetic mixed diagnostic.']),
        'partial_write_error':([write+'\n'+bad+'\n'+read,'The batch returned an error.'],['Synthetic protocol diagnostic; no compliance claim.','###STOP###'])}


class Tensor:
    def __init__(self, value):self.value=value
    def tolist(self):return self.value


class TorchStub:
    long='long'
    def tensor(self,value,**kwargs):return Tensor(value)
    def ones_like(self,value):return Tensor([[1]*len(value.value[0])])
    def manual_seed(self,seed):self.seed=seed


class GeneratorStub:
    def __init__(self, tokenizer, texts, *, corrupt_prefix=False):
        self.completions=[tokenizer.encode(t+'<|im_end|>').ids for t in texts]
        self.corrupt_prefix=corrupt_prefix;self.calls=[]
    def generate(self,**kwargs):
        self.calls.append(kwargs)
        prefix=kwargs['input_ids'].tolist()[0][:]
        if self.corrupt_prefix:prefix[0]+=1
        return SimpleNamespace(sequences=Tensor([prefix+self.completions.pop(0)]))


def student(tokenizer,texts,**kwargs):
    model=GeneratorStub(tokenizer,texts,**kwargs)
    return TransformersQwenModelClient('not-read',tokenizer,weight_revision='0'*40,model=model,torch_module=TorchStub())


def request(tokenizer, client):
    ids=tuple(tokenizer.encode('Synthetic context').ids)
    return ModelRequest('fixture','Synthetic context',ids,'[]','[]','{}',canonical({**client.sampling,'seed':42}),
                        (tokenizer.eos,),512)


def test_asset_inventory_never_loads_hidden_body(monkeypatch):
    import policytrace.stage3_1.assets as assets
    monkeypatch.setattr(assets,'load_retail_task',lambda *a:pytest.fail('Body deserialization in preparation'))
    result=verify_assets()
    assert result['status']=='PASS' and result['required_files']==10
    assert result['test_bodies_deserialized']==0


@pytest.mark.parametrize('split,confirmed',[('test',False),('train',False),('external',True)])
def test_split_body_gates(split,confirmed):
    with pytest.raises(ValueError):RuntimeTaskPool(split,['never-loaded'],confirmed_test=confirmed)


def test_selected_loader_reuses_frozen_snapshot():
    pool=RuntimeTaskPool('dev',['retail_152'])
    task,snapshot=pool.load('retail_152')
    assert snapshot.file_sha256==pool.entries['retail_152']['snapshot_sha256']
    with pytest.raises(ValueError):pool.records['retail_131']


def test_original_generated_ids_no_reencode(tokenizer,monkeypatch):
    client=student(tokenizer,['Hello'])
    req=request(tokenizer,client)
    expected=tuple(client.model.completions[0])
    monkeypatch.setattr(tokenizer,'encode',lambda *a,**kw:pytest.fail('Completion must not be reencoded'))
    actual=client.generate(req)
    assert actual.generated_token_ids==expected
    assert actual.source=='mock' and actual.token_provenance=='mock_encoded'
    assert actual.telemetry['gpu_peak_allocated_bytes'] is None
    assert client.model.calls[0]['logits_to_keep']==1
    assert client.model.calls[0]['generation_config'].eos_token_id==151645


def test_bad_generated_prefix_is_rejected(tokenizer):
    client=student(tokenizer,['Hello'],corrupt_prefix=True)
    with pytest.raises(HarnessError,match='generate_prompt_prefix_mismatch'):client.generate(request(tokenizer,client))


@pytest.mark.parametrize('changes',[{'temperature':1},{'top_p':.8},{'top_k':20}])
def test_sampling_contract(tokenizer,changes):
    from dataclasses import replace
    client=student(tokenizer,['Hello']);req=request(tokenizer,client)
    req=replace(req,sampling_json=canonical({**client.sampling,**changes}))
    with pytest.raises(HarnessError,match='sampling_contract_mismatch'):client.generate(req)


def test_real_client_missing_model_never_imports_torch(tokenizer):
    with pytest.raises(FileNotFoundError):TransformersQwenModelClient('nonexistent',tokenizer,weight_revision='0'*40)


@pytest.mark.parametrize('value',['main','latest','', 'a'*39,'z'*40])
def test_model_revision_immutable(value):
    with pytest.raises(ValueError):revision(value)


def test_download_dry_run_does_not_import_download_sdk(monkeypatch,capsys):
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub,'snapshot_download',lambda *a,**k:pytest.fail('No download allowed'))
    download_main(['--local-dir','data/private/stage3_1/models/unused','--revision','0'*40,'--dry-run'])
    assert json.loads(capsys.readouterr().out)['download_executed'] is False


@pytest.mark.parametrize('damage',['none','truncated','offset','shape'])
def test_safetensors_integrity(tmp_path,damage):
    header={'weight':{'dtype':'BF16','shape':[2],'data_offsets':[0,4]}}
    if damage=='offset':header['weight']['data_offsets']=[1,5]
    if damage=='shape':header['weight']['shape']=[3]
    payload=json.dumps(header).encode();path=tmp_path/'tiny.safetensors'
    path.write_bytes(struct.pack('<Q',len(payload))+payload+(b'\0'*3 if damage=='truncated' else b'\0'*4))
    if damage=='none':assert tensor_header(path)==({'weight'},4)
    else:
        with pytest.raises(ValueError):tensor_header(path)


def test_provider_native_user_prompt_stop_and_unknown_bill(private_log):
    sent=[]
    def transport(req):
        sent.append(json.loads(req.content));return httpx.Response(200,json=response())
    provider=DeepSeekProvider('offline-fixture-key',private_log/'native_provider.json',config=priced(),
        budget=RunBudget(5,60),transport=httpx.MockTransport(transport),mock=True)
    try:
        user=DeepSeekUserSimulator('Synthetic private user instruction',provider)
        user.set_seed(42)
        assert 'seed' not in user.llm_args
        result,state=user.generate_next_message(AssistantMessage(role='assistant',content='Hello'),user.get_init_state())
        assert user.is_stop(result) and result.cost is None
        assert '<scenario>' in sent[0]['messages'][0]['content']
        assert 'Synthetic private user instruction' in sent[0]['messages'][0]['content']
        assert 'evaluation_criteria' not in sent[0]['messages'][0]['content']
        assert sent[0]['thinking']=={'type':'disabled'} and provider.ledger['requests'][0]['status']=='completed'
        assert provider.ledger['actual_bill_cny'] is None
    finally:provider.close()


@pytest.mark.parametrize('kind',['http','rate_limit','timeout','usage','truncated','bad_json'])
def test_provider_errors_no_retry_no_secret(private_log,kind):
    secret='offline-fixture-secret-do-not-log';calls=[]
    def transport(req):
        calls.append(1)
        if kind=='timeout':raise httpx.ReadTimeout(secret)
        if kind=='http':return httpx.Response(401,json={'error':secret})
        if kind=='rate_limit':return httpx.Response(429,json={'error':secret})
        if kind=='bad_json':return httpx.Response(200,text=secret)
        data=response()
        if kind=='usage':data.pop('usage')
        if kind=='truncated':data['choices'][0]['finish_reason']='length'
        return httpx.Response(200,json=data)
    provider=DeepSeekProvider(secret,private_log/f'failure_{kind}.json',config=priced(),budget=RunBudget(10,60),
        transport=httpx.MockTransport(transport),mock=True)
    try:
        with pytest.raises(HarnessError) as error:provider.complete(model='deepseek-v4-pro',messages=[{'role':'user','content':'hi'}])
        assert secret not in str(error.value)
        with pytest.raises(HarnessError,match='ambiguous_request_no_retry'):provider.complete(model='deepseek-v4-pro',messages=[])
        assert len(calls)==1 and provider.charged_upper_cny>0
        assert secret not in provider.ledger_path.read_text()
        assert provider.ledger['requests'][0]['status']!='completed'
    finally:provider.close()


def test_budget_blocks_before_request(private_log):
    cfg=priced();cfg['budget_cny']=.000001
    provider=DeepSeekProvider('fixture',private_log/'tiny_budget.json',config=cfg,budget=RunBudget(1,60),
        transport=httpx.MockTransport(lambda r:pytest.fail('Budget must stop before transport')),mock=True)
    try:
        with pytest.raises(HarnessError,match='user_api_budget_cap_reached'):provider.complete(model='deepseek-v4-pro',messages=[])
        assert provider.ledger['requests']==[]
    finally:provider.close()


def test_shared_call_cap():
    budget=RunBudget(1,60);budget.take()
    with pytest.raises(HarnessError,match='total_model_call_cap_reached'):budget.take()


@pytest.mark.parametrize('kind',['dev-smoke','e0-test'])
def test_cli_dry_run_never_constructs_clients(monkeypatch,capsys,kind):
    import policytrace.stage3_1.student as module
    monkeypatch.setattr(module,'TransformersQwenModelClient',lambda *a,**k:pytest.fail('No real client'))
    flags=['--confirm-frozen-test'] if kind=='e0-test' else []
    code=cli.main([kind,'--config','configs/harness/stage3_1.example.json','--split','test' if kind=='e0-test' else 'dev','--dry-run',*flags])
    output=json.loads(capsys.readouterr().out)
    assert code==0 and output['actual_episodes']==0 and not output['clients_instantiated']
    assert output['test_bodies_deserialized']==0
    assert 'BLOCKED_MODEL' in output['blockers']


def test_test_double_confirmation(capsys):
    assert cli.main(['e0-test','--config','configs/harness/stage3_1.example.json','--split','test','--execute'])==2
    assert json.loads(capsys.readouterr().out)['status']=='BLOCKED_TEST_CONFIRMATION'


def test_env_no_false_ready(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    result=preflight(config())
    assert result['status']=='BLOCKED' and not result['api_key_present']
    assert set(result['blockers']) >= {'BLOCKED_MODEL','BLOCKED_API_KEY','BLOCKED_PRICE'}
    assert not result['weights_loaded'] and result['test_bodies_deserialized']==0


@pytest.mark.parametrize('name',['env-check','dev-smoke','e0-test','freeze-protocol','summarize'])
def test_help_exits_without_side_effects(name):
    with pytest.raises(SystemExit) as error:cli.main([name,'--help'])
    assert error.value.code==0


@pytest.fixture(scope='module')
def episodes(private_log,tokenizer):
    result={}
    for kind in ('multi_read','mixed','partial_write_error'):
        texts,user_texts=fixture_scripts()[kind]
        client=student(tokenizer,texts)
        cfg=config()
        proto={'model_id':'mock:qwen-generation-stub','weight_receipt_sha256':'0'*64,'weight_revision':'0'*40,'code_sha256':'0'*64}
        plan=make_plan(cfg,proto,['retail_152'],f'offline_{kind}',mode='dev-smoke',source='mock')
        output=private_log/kind;output.mkdir()
        exclusive_json(output/'run_manifest.json',{'mode':'dev-smoke','source':'mock','protocol':proto,'plan':plan.model_dump(mode='json')})
        replies=iter(user_texts)
        provider=DeepSeekProvider('fixture',output/'api_ledger.json',config=priced(),budget=RunBudget(20,120),
            transport=httpx.MockTransport(lambda req:httpx.Response(200,json=response(next(replies)))),mock=True)
        try:
            episode,interrupted=run_episode(RuntimeTaskPool('dev',['retail_152']),'retail_152',output/'episodes/retail_152',
                plan,cfg,tokenizer,client,lambda instructions:DeepSeekUserSimulator(instructions,provider))
            result[kind]=(episode,output,client,summarize(output))
        finally:provider.close()
    return result


def test_native_multitool_full_loop_and_mask(episodes):
    episode,output,client,summary=episodes['multi_read']
    assert episode.execution_status=='completed' and episode.scoring_status=='scored'
    assert episode.tools.attempted==2 and episode.tools.execution_errors==0
    from policytrace.data.manifests import read_jsonl
    trace=list(read_jsonl(output/'episodes/retail_152/decision_trace.jsonl'))
    assert len(trace[0]['tool_events'])==2
    assert len({e['observation']['id'] for e in trace[0]['tool_events']})==2
    assert sum(m['role']=='tool' for m in trace[1]['context']['context_messages'])==2
    for row in trace:
        assert row['role_mask']['condition_value']==0 and row['role_mask']['student_action_value']==1
        assert row['role_mask']['student_action_length']==len(row['generation']['generated_token_ids'])
        assert row['generation']['source']=='mock'
    assert summary['pass1']['value'] is None and summary['actual_student_completion_tokens']==0
    assert summary['integrity']['raw_snapshots_unchanged']


def test_mixed_rejected_by_native_policy(episodes):
    episode,_,_,summary=episodes['mixed']
    assert episode.termination_reason=='agent_error' and episode.tools.attempted==1
    assert episode.tools.framework_errors==1 and summary['protocol_features']['text_and_tool_calls']==1


def test_partial_write_error_still_associated(episodes):
    episode,_,_,summary=episodes['partial_write_error']
    assert episode.tools.attempted==3 and episode.tools.execution_errors==1
    assert summary['integrity']['raw_snapshots_unchanged']


def test_append_only_no_retry(episodes,tokenizer):
    episode,output,client,_=episodes['multi_read']
    plan=make_plan(config(),{'model_id':'stub','weight_receipt_sha256':'0'*64,'weight_revision':'0'*40,'code_sha256':'0'*64},
                   ['retail_152'],'other',mode='dev-smoke',source='mock')
    with pytest.raises(FileExistsError):run_episode(RuntimeTaskPool('dev',['retail_152']),'retail_152',output/'episodes/retail_152',
        plan,config(),tokenizer,client,lambda x:pytest.fail('Must stop before clients/task loading'))


def test_interrupted_attempt_and_missing_slots_keep_denominator(private_log):
    cfg=config();proto={'model_id':'stub','weight_receipt_sha256':'0'*64,'weight_revision':'0'*40,'code_sha256':'0'*64}
    ids=[f'synthetic_{i}' for i in range(85)]
    plan=make_plan(cfg,proto,ids,'partial',mode='dev-smoke',source='mock')
    output=private_log/'partial';output.mkdir()
    exclusive_json(output/'run_manifest.json',{'mode':'dev-smoke','source':'mock','protocol':proto,'plan':plan.model_dump(mode='json')})
    exclusive_json(output/'episodes/slot0/started.json',{'episode_id':'interrupted','task_id':ids[0],'trial_id':'trial_0',
        'snapshot_id':'synthetic-db','snapshot_sha256':'0'*64})
    summary=summarize(output)
    assert summary['status']=='incomplete' and summary['coverage']['started_trials']==1
    assert summary['diagnostic_pass1']['denominator']==85 and summary['diagnostic_pass1']['value'] is None
    assert summary['outcomes']['reward_null']==1


def test_duplicate_task_trial_rejected(episodes):
    episode,_,_,_=episodes['multi_read']
    from policytrace.evaluation.schema import EvaluationPlan
    from policytrace.evaluation.metrics import aggregate
    plan=EvaluationPlan(context=episode.context,task_ids=(episode.task_id,),trial_ids=('trial_0',),trials_per_task=1,provenance='mock')
    with pytest.raises(ValueError,match='Duplicate task/trial'):aggregate(plan,[episode,episode])


def test_mock_cannot_enter_test_plan():
    with pytest.raises(ValueError,match='Mock cannot'):make_plan(config(),{},['synthetic'],'mock',mode='e0-test',source='mock')


def test_unknown_cost_never_zero():
    projection=project_cost({'coverage':{'started_trials':3},'api_costs':{'groups':[]},'duration_seconds':{'total':None}},config())
    assert projection['api_estimate_cny'] is None and projection['gpu_active_estimate_cny'] is None


@pytest.mark.parametrize('path',['reports/stage3_1/unsafe.json','data/private/stage3_1/../../raw/unsafe.json'])
def test_output_path_restricted(path):
    with pytest.raises(ValueError):private_path(path)


def test_archive_path_traversal_rejected(tmp_path):
    lock=read_json(ROOT/LOCK)
    (tmp_path/'configs/harness').mkdir(parents=True)
    exclusive_json(tmp_path/LOCK,lock)
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape',b'invalid')
    with pytest.raises(ValueError,match='allowlist'):unpack(archive,tmp_path)
    assert not (tmp_path/'data').exists()


@pytest.mark.parametrize('gate',['data','policy'])
def test_preflight_data_policy_fail_closed(monkeypatch,gate):
    import policytrace.stage3_1.protocol as protocol
    if gate=='data':monkeypatch.setattr(protocol,'verify_assets',lambda:{'status':'BLOCKED_DATA'})
    else:
        def wrong_policy():raise ValueError('Policy SHA mismatch fixture')
        monkeypatch.setattr(protocol,'verify_fork',wrong_policy)
    assert 'BLOCKED_'+gate.upper() in protocol.preflight(config())['blockers']


@pytest.mark.parametrize('mutation',['source','protocol','ids','coverage','tokens','users','snapshot','cost'])
def test_freeze_rejects_invalid_dev_evidence(private_log,monkeypatch,mutation):
    import policytrace.stage3_1.protocol as protocol
    import policytrace.stage3_1.summary as module
    from policytrace.stage3_1.assets import SMOKE_IDS
    expected={'fixture':'synthetic_protocol'}
    evidence={'mode':'dev-smoke','source':'real','protocol':expected,'plan':{'task_ids':list(SMOKE_IDS)}}
    summary={'coverage':{'started_trials':3,'scored_trials':3},'integrity':{
        'all_real_tokens':True,'all_real_users':True,'native_serialization_verified':True,
        'raw_snapshots_unchanged':True,'evidence_sha256':'0'*64}}
    if mutation=='source':evidence['source']='mock'
    if mutation=='protocol':evidence['protocol']={'different':True}
    if mutation=='ids':evidence['plan']['task_ids']=['synthetic']
    if mutation=='coverage':summary['coverage']['scored_trials']=2
    if mutation=='tokens':summary['integrity']['all_real_tokens']=False
    if mutation=='users':summary['integrity']['all_real_users']=False
    if mutation=='snapshot':summary['integrity']['raw_snapshots_unchanged']=False
    smoke=private_log/('synthetic_freeze_'+mutation);smoke.mkdir()
    exclusive_json(smoke/'run_manifest.json',evidence)
    monkeypatch.setattr(protocol,'common_protocol',lambda cfg:expected)
    monkeypatch.setattr(module,'summarize',lambda path:summary)
    monkeypatch.setattr(protocol,'project_cost',lambda *a:{'api_estimate_cny':100 if mutation=='cost' else None})
    out=smoke/'should_not_exist.json'
    with pytest.raises(ValueError,match='BLOCKED_'):protocol.freeze(config(),smoke,out,confirm_cost=True)
    assert not out.exists()


def test_test_rejects_frozen_protocol_changes(private_log,monkeypatch):
    import policytrace.stage3_1.protocol as protocol
    path=private_log/'changed_protocol.json'
    exclusive_json(path,{'protocol':{'fixture':'old'},'protocol_sha256':digest({'fixture':'old'}),'cost_confirmed_by_user':True})
    monkeypatch.setattr(protocol,'common_protocol',lambda cfg:{'fixture':'changed_policy_or_decoder'})
    with pytest.raises(ValueError,match='BLOCKED_PROTOCOL_MISMATCH'):protocol.verify_frozen_protocol(config(),path)


def test_config_strict_validation():
    with pytest.raises(ValueError):Settings(local_model_dir='fixture',max_calls=True)
    with pytest.raises(ValueError):Settings(local_model_dir='fixture',unknown='bad')
    with pytest.raises(ValueError):Settings(local_model_dir='fixture',reserved_generation_tokens=20000)


def test_missing_asset_blocks_without_body_parse(tmp_path,monkeypatch):
    import policytrace.stage3_1.assets as module
    exclusive_json(tmp_path/LOCK,read_json(ROOT/LOCK))
    monkeypatch.setattr(module,'load_retail_task',lambda *a:pytest.fail('No body load'))
    result=verify_assets(tmp_path)
    assert result['status']=='BLOCKED_DATA' and len(result['issues'])==10


def test_archive_unequal_existing_file_never_overwritten(tmp_path):
    from policytrace.data.manifests import task_manifest
    from policytrace.evaluation.schema import DATASET_REVISION,ENVIRONMENT_SHA,task_set_hash
    from policytrace.stage3_1.assets import SMOKE_IDS,SPLITS
    source=tmp_path/'source';destination=tmp_path/'destination'
    names=['data/raw/task-fixture.txt',*SPLITS.values()]
    bodies={'data/raw/task-fixture.txt':b'synthetic fixture only'}
    for split,path in SPLITS.items():
        ids=list(SMOKE_IDS) if split=='dev' else ['synthetic_test_metadata_only']
        bodies[path]=json.dumps({'dataset_revision':DATASET_REVISION,'environment_sha':ENVIRONMENT_SHA,
            'task_ids':ids,'task_set_sha256':task_set_hash(ids),'entries':[{'id':t} for t in ids]}).encode()
    import hashlib
    lock={'files':[{'path':n,'bytes':len(bodies[n]),'sha256':hashlib.sha256(bodies[n]).hexdigest()} for n in names],
        'splits':{s:{'count':3 if s=='dev' else 1,'task_set_sha256':json.loads(bodies[p])['task_set_sha256']} for s,p in SPLITS.items()}}
    for root in (source,destination):exclusive_json(root/LOCK,lock)
    for n,v in bodies.items():
        target=source/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(v)
    archive=tmp_path/'fixture.zip';pack(archive,source)
    damaged=destination/names[0];damaged.parent.mkdir(parents=True,exist_ok=True);damaged.write_bytes(b'preserve this')
    with pytest.raises(ValueError,match='refusing overwrite'):unpack(archive,destination)
    assert damaged.read_bytes()==b'preserve this' and not (destination/SPLITS['test']).exists()


def test_publication_allowlist_excludes_ignored_build_and_secrets(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('local_git_audit',ROOT/'scripts/stage3_1_git_audit.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in ('src/package/ok.py','src/package.egg-info/SOURCES.txt','src/package/__pycache__/cache.py',
                 'docs/.env.local','docs/id.key','docs/session.log'):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
    assert module.candidates(tmp_path)==['src/package/ok.py']
