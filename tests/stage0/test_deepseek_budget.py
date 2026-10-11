import json

import httpx
import pytest

from policytrace.stage0.deepseek_client import BudgetedDeepSeek, BudgetExceeded, CompletionFailed, MODEL


def response(usage=None):
    return {'id':'fixture', 'model':MODEL, 'object':'chat.completion', 'created':0,
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'Hello'}}],
            'usage':usage or {'prompt_tokens':100,'completion_tokens':5,'total_tokens':105}}


def test_usage_budget_and_request_settings(tmp_path):
    seen = []
    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json=response())
    client = BudgetedDeepSeek('dummy-key',tmp_path/'ledger.json',transport=httpx.MockTransport(handle))
    try:
        client.complete('user',model=MODEL,messages=[{'role':'system','content':'fixture'}],seed=42,num_retries=9)
        assert seen[0]['thinking'] == {'type':'disabled'}
        assert seen[0]['max_tokens'] == 512 and seen[0]['temperature'] == 0
        assert 'seed' not in seen[0] and 'num_retries' not in seen[0]
        assert client.charged_upper_cny == pytest.approx((100*9+5*27)/1e6)
        assert 'dummy-key' not in (tmp_path/'ledger.json').read_text()
    finally:
        client.close()


def test_failures_keep_reservation_and_no_retry(tmp_path):
    calls = []
    def handle(request):
        calls.append(1)
        return httpx.Response(429,json={'error':'fixture'})
    path = tmp_path/'ledger.json'
    client = BudgetedDeepSeek('dummy',path,transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CompletionFailed,match='HTTP 429'):
            client.complete('user',model=MODEL,messages=[])
        assert len(calls)==1 and client.charged_upper_cny>0
    finally:
        client.close()
    with pytest.raises(CompletionFailed,match='Previous'):
        BudgetedDeepSeek('dummy',path)


def test_budget_and_context_rejected_before_network(tmp_path):
    def forbidden(request):
        pytest.fail('No network request should be sent')
    client = BudgetedDeepSeek('dummy',tmp_path/'ledger.json',transport=httpx.MockTransport(forbidden))
    try:
        with pytest.raises(BudgetExceeded,match='Context'):
            client.complete('agent',model=MODEL,messages=[{'role':'user','content':'x'*40000}])
        client.ledger['requests'] = [{'status':'completed','accounted_upper_cny':3.99}]
        with pytest.raises(BudgetExceeded,match='cap'):
            client.complete('user',model=MODEL,messages=[])
    finally:
        client.close()


def test_timeout_keeps_cost_reserved(tmp_path):
    def handle(request):
        raise httpx.ReadTimeout('fixture')
    client = BudgetedDeepSeek('dummy',tmp_path/'ledger.json',transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CompletionFailed,match='ReadTimeout'):
            client.complete('user',model=MODEL,messages=[])
        assert client.ledger['requests'][0]['status']=='failed' and client.charged_upper_cny>0
    finally:
        client.close()


def test_usage_above_reservation_stops(tmp_path):
    def handle(request):
        return httpx.Response(200,json=response({'prompt_tokens':100000,'completion_tokens':5,'total_tokens':100005}))
    client = BudgetedDeepSeek('dummy',tmp_path/'ledger.json',transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(CompletionFailed,match='exceeded'):
            client.complete('user',model=MODEL,messages=[])
        assert client.ledger['requests'][0]['status']=='failed'
    finally:
        client.close()
