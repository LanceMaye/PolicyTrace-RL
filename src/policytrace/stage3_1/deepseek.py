"""Native Fork user simulation, conservative Stage 0 ledger persistence, zero retries."""
import json
import time
from pathlib import Path

import httpx
from litellm import ModelResponse
from tau2.user.user_simulator import UserSimulator

from policytrace.data.manifests import digest
from policytrace.harness.context import HarnessError
from policytrace.stage0.deepseek_client import BudgetedDeepSeek


class DeepSeekProvider(BudgetedDeepSeek):
    """New run ledger. Prices are user-verified conservative bounds, not provider bills."""
    def __init__(self, api_key, ledger_path, *, config, budget, transport=None, mock=False):
        if not api_key or not api_key.strip():
            raise HarnessError('BLOCKED_API_KEY')
        if config['model'] != 'deepseek-v4-pro':
            raise HarnessError('unsupported_simulator_model')
        rates = (config.get('input_cny_per_m'), config.get('output_cny_per_m'))
        if any(type(x) not in (int,float) or x <= 0 for x in rates) or not config.get('price_verified_on'):
            raise HarnessError('BLOCKED_PRICE')
        self.config, self.budget, self.mock = config, budget, mock
        self.config_hash = digest(config)
        self.ledger_path = Path(ledger_path)
        if self.ledger_path.exists():
            raise HarnessError('ledger_already_exists_no_resume')
        self.ledger = {'version':'stage3_1-conservative-ledger-v1','config_sha256':self.config_hash,
            'internal_limit_cny':config['budget_cny'],'requests':[], 'source':'mock' if mock else 'real',
            'cost_kind':'upper_bound_estimate','actual_bill_cny':None}
        self.client = httpx.Client(base_url='https://api.deepseek.com',
            headers={'Authorization':f'Bearer {api_key}'}, timeout=config['timeout_seconds'],
            follow_redirects=False, transport=transport)
        self.save()

    def complete(self, **kwargs):
        if kwargs.get('model') != self.config['model'] or kwargs.get('tools'):
            raise HarnessError('unsupported_user_completion_contract')
        if any(r['status'] != 'completed' for r in self.ledger['requests']):
            raise HarnessError('ambiguous_request_no_retry')
        self.budget.take()
        messages = [{k:v for k,v in m.items() if v is not None} for m in kwargs['messages']]
        body = {'model':self.config['model'],'messages':messages,'temperature':self.config['temperature'],
                'max_tokens':self.config['max_output_tokens'],'stream':False,'thinking':{'type':'disabled'}}
        payload_bytes = len(json.dumps(body,ensure_ascii=False).encode('utf-8'))
        if payload_bytes > self.config['max_payload_bytes']:
            raise HarnessError('user_context_byte_cap_reached')
        input_reserve = payload_bytes+4096
        reserve = (input_reserve*self.config['input_cny_per_m'] +
                   self.config['max_output_tokens']*self.config['output_cny_per_m'])/1e6
        if len(self.ledger['requests']) >= self.config['max_requests'] or self.charged_upper_cny+reserve > self.config['budget_cny']:
            raise HarnessError('user_api_budget_cap_reached')
        entry = {'role':'user','status':'reserved','source':'mock' if self.mock else 'real',
                 'reserved_input_tokens':input_reserve,'accounted_upper_cny':reserve,
                 'usage':None,'request_started':False,'actual_bill_cny':None}
        self.ledger['requests'].append(entry); self.save()
        start = time.perf_counter()
        try:
            entry['request_started'] = True; self.save()
            response = self.client.post('/chat/completions',json=body)
            if response.status_code != 200:
                entry.update(status='http_error',http_status=response.status_code)
                raise HarnessError('deepseek_http_error')
            data = response.json()
            usage = data.get('usage')
            if not isinstance(usage,dict) or not all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('prompt_tokens','completion_tokens')):
                raise HarnessError('deepseek_usage_unavailable')
            entry['usage'] = {k:usage[k] for k in ('prompt_tokens','completion_tokens')}
            if usage['prompt_tokens'] > input_reserve or usage['completion_tokens'] > self.config['max_output_tokens']:
                raise HarnessError('deepseek_reservation_exceeded')
            choice = data['choices'][0]
            if len(data['choices']) != 1 or choice.get('finish_reason') != 'stop' or choice['message'].get('tool_calls'):
                raise HarnessError('deepseek_incomplete_or_tool_response')
            if not isinstance(choice['message'].get('content'),str) or not choice['message']['content'].strip():
                raise HarnessError('deepseek_empty_response')
            result = ModelResponse(**data)
            entry.update(status='completed', response_model=data.get('model'), request_id=data.get('id'),
                system_fingerprint=data.get('system_fingerprint'),
                accounted_upper_cny=(usage['prompt_tokens']*self.config['input_cny_per_m']+
                                     usage['completion_tokens']*self.config['output_cny_per_m'])/1e6)
            return result
        except BaseException as exc:
            if entry['status'] == 'reserved':
                entry['status'] = 'ambiguous_failed'
            entry['error_type'] = type(exc).__name__
            # Even HTTP exception repr/response JSON can carry secrets. Never retain them.
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise HarnessError(getattr(exc,'code','deepseek_transport_or_response_error')) from None
        finally:
            entry['duration_seconds'] = time.perf_counter()-start
            self.save()


class DeepSeekUserSimulator(UserSimulator):
    def __init__(self, instructions, provider):
        self.provider, self.events = provider, []
        super().__init__(instructions=instructions, llm=provider.config['model'],
            llm_args={'temperature':provider.config['temperature'],'max_tokens':provider.config['max_output_tokens'],'num_retries':0},
            completion_fn=provider.complete)

    def set_seed(self, seed):
        # Fork invokes this interface; this provider does not promise a supported seed.
        self.seed = seed

    def _generate_next_message(self, message, state):
        start = time.perf_counter()
        index = len(self.provider.ledger['requests'])
        event = {'source':'mock' if self.provider.mock else 'real','provider_request_index':index,
                 'usage':None,'error_code':None}
        self.events.append(event)
        try:
            response, state = super()._generate_next_message(message,state)
            response.cost = None  # Native LiteLLM fallback 0 is not an observed bill.
            event['usage'] = response.usage
            event['sent'] = response.model_dump(mode='json')
            return response, state
        except BaseException as exc:
            event['error_code'] = getattr(exc,'code','user_simulator_error')
            raise
        finally:
            event['duration_seconds'] = time.perf_counter()-start
