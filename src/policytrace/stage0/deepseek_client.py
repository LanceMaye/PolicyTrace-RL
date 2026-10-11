"""Small official-completion adapter with persistent, conservative CNY accounting."""
import json
from pathlib import Path
from typing import Any

import httpx
from litellm import ModelResponse

MODEL = 'deepseek-v4-pro'
PRICE_SOURCE = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing'
# Peak, cache-miss prices verified on 2026-10-09; deliberately no cache discount.
INPUT_CNY_PER_M = 9.0
OUTPUT_CNY_PER_M = 27.0
MAX_OUTPUT = 512
MAX_PAYLOAD_BYTES = 32768
INTERNAL_BUDGET_CNY = 4.0  # Leave 1 CNY below the user's 5 CNY limit.


class BudgetExceeded(RuntimeError):
    pass


class CompletionFailed(RuntimeError):
    pass


class BudgetedDeepSeek:
    """One sequential Stage 0 run; script holds an exclusive run lock.

    Reserve before sending; ambiguous failures retain their reservation. Never retry.
    Usage is priced at peak cache-miss rates, not reported as an exact provider bill.
    """
    def __init__(self, api_key: str, ledger_path: Path, *, transport=None):
        if not api_key.strip():
            raise ValueError('DEEPSEEK_API_KEY is missing; fill the local .env file')
        self.ledger_path = ledger_path
        self.ledger = json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {
            'user_limit_cny':5.0, 'internal_limit_cny':INTERNAL_BUDGET_CNY,
            'price_source':PRICE_SOURCE, 'price_verified_date':'2026-10-09',
            'input_peak_cache_miss_cny_per_m':INPUT_CNY_PER_M,
            'output_peak_cny_per_m':OUTPUT_CNY_PER_M, 'requests':[]}
        if any(r['status'] != 'completed' for r in self.ledger['requests']):
            raise CompletionFailed('Previous ambiguous/failed request exists; inspect ledger before any further paid request')
        self.client = httpx.Client(base_url='https://api.deepseek.com',
            headers={'Authorization':f'Bearer {api_key}'}, timeout=45.0, follow_redirects=False, transport=transport)

    def save(self) -> None:
        self.ledger_path.parent.mkdir(parents=True,exist_ok=True)
        temp = self.ledger_path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.ledger,indent=2),encoding='utf-8')
        temp.replace(self.ledger_path)

    @property
    def charged_upper_cny(self) -> float:
        return sum(r['accounted_upper_cny'] for r in self.ledger['requests'])

    def complete(self, role: str, **kwargs: Any) -> ModelResponse:
        if kwargs.get('model') != MODEL:
            raise ValueError('Only the explicitly authorized DeepSeek model is allowed')
        # Upstream LiteLLM messages contain an extra tool-call name key; normalize
        # to the provider's public OpenAI-compatible schema without changing text.
        messages = []
        for original in kwargs['messages']:
            message = {k:v for k,v in original.items() if v is not None}
            if message.get('tool_calls'):
                message['tool_calls'] = [{k:v for k,v in tc.items() if k in ('id','type','function')} for tc in message['tool_calls']]
            messages.append(message)
        body = {'model':MODEL, 'messages':messages, 'temperature':0,
                'max_tokens':MAX_OUTPUT, 'stream':False, 'thinking':{'type':'disabled'}}
        if kwargs.get('tools'):
            body['tools'] = kwargs['tools']
            body['tool_choice'] = 'auto'
        payload_bytes = len(json.dumps(body,ensure_ascii=False).encode('utf-8'))
        if payload_bytes > MAX_PAYLOAD_BYTES:
            raise BudgetExceeded('Context exceeds the small Stage 0 request limit')
        # UTF-8 bytes plus a generous template allowance bound tokenization for
        # these text-only requests conservatively; also retain 1 CNY global margin.
        token_reserve = payload_bytes + 4096
        reserve = (token_reserve * INPUT_CNY_PER_M + MAX_OUTPUT * OUTPUT_CNY_PER_M) / 1e6
        if len(self.ledger['requests']) >= 24 or self.charged_upper_cny + reserve > INTERNAL_BUDGET_CNY:
            raise BudgetExceeded('Stage 0 cumulative request/cost cap reached')
        entry = {'role':role, 'status':'reserved', 'reserved_input_tokens':token_reserve,
                 'accounted_upper_cny':reserve, 'requested_model':MODEL}
        self.ledger['requests'].append(entry)
        self.save()  # Survives interruption after sending a potentially billable request.
        try:
            response = self.client.post('/chat/completions',json=body)
            if response.status_code != 200:
                entry.update(status='http_error', http_status=response.status_code)
                raise CompletionFailed(f'DeepSeek HTTP {response.status_code}; no retry')
            data = response.json()
            usage = data.get('usage')
            if not isinstance(usage,dict) or not all(isinstance(usage.get(k),int) and usage[k]>=0 for k in ('prompt_tokens','completion_tokens')):
                raise CompletionFailed('Missing/invalid provider usage; retained full reservation')
            cost_upper = (usage['prompt_tokens']*INPUT_CNY_PER_M + usage['completion_tokens']*OUTPUT_CNY_PER_M)/1e6
            entry.update(usage=usage, response_model=data.get('model'), system_fingerprint=data.get('system_fingerprint'),
                         request_id=data.get('id'), accounted_upper_cny=cost_upper)
            if usage['prompt_tokens'] > token_reserve or usage['completion_tokens'] > MAX_OUTPUT:
                raise CompletionFailed('Provider usage exceeded request reservation; stopped')
            if data['choices'][0].get('finish_reason') not in ('stop','tool_calls'):
                raise CompletionFailed('Provider returned an incomplete completion; stopped')
            result = ModelResponse(**data)
            entry['status'] = 'completed'
            return result
        except CompletionFailed:
            if entry['status'] == 'reserved':
                entry['status'] = 'failed'
            raise
        except Exception as exc:
            entry.update(status='failed',exception_type=type(exc).__name__)
            # Do not persist HTTP headers, credentials or provider error payloads.
            raise CompletionFailed(f'DeepSeek {type(exc).__name__}; no retry') from None
        finally:
            self.save()

    def close(self) -> None:
        self.client.close()
