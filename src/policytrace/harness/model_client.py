"""A token-first model contract; this stage supplies only an encoded script."""
from dataclasses import dataclass
import time
from typing import Protocol

from policytrace.data.manifests import digest
from policytrace.data.sft_tokenize import QwenTokenizer


@dataclass(frozen=True)
class ModelRequest:
    decision_id: str
    prompt_text: str
    prompt_token_ids: tuple[int, ...]
    context_json: str
    tools_json: str
    versions_json: str
    sampling_json: str
    stop_token_ids: tuple[int, ...]
    reserved_generation_tokens: int


@dataclass(frozen=True)
class ModelResponse:
    text: str
    generated_token_ids: tuple[int, ...]
    token_provenance: str
    stop_reason: str
    source: str
    model_id: str
    duration_seconds: float
    provider_usage: dict | None = None
    logprobs: tuple[float, ...] | None = None
    missing_reason: str = 'Mock encoded script; no model forward, logits or provider usage'
    telemetry: dict | None = None


class ModelClient(Protocol):
    model_id: str
    config_hash: str
    source: str
    def generate(self, request: ModelRequest) -> ModelResponse: ...


class DeterministicMock:
    model_id = 'mock:scripted-student-v1'
    source = 'mock'

    def __init__(self, tokenizer: QwenTokenizer, responses):
        self.tokenizer = tokenizer
        self.responses = tuple(responses)
        self.config_hash = digest({'model': self.model_id, 'responses': self.responses})
        self.requests = []
        self.cursor = 0

    def generate(self, request):
        start = time.perf_counter()
        self.requests.append(request)
        if self.cursor >= len(self.responses):
            raise RuntimeError('Mock Student script exhausted')
        text = self.responses[self.cursor]
        self.cursor += 1
        # The mock deliberately supplies the same EOS accepted by the SFT parser.
        if not text.rstrip().endswith('<|im_end|>'):
            text += '<|im_end|>'
        ids = tuple(self.tokenizer.encode(text).ids)
        return ModelResponse(text, ids, 'mock_encoded', 'script_eos', 'mock',
                             self.model_id, time.perf_counter()-start)
