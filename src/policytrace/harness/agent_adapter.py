"""Pinned BaseAgent adapter; all tool execution remains in Orchestrator."""
from dataclasses import dataclass, field
from copy import deepcopy
import hashlib
import re
import time

from jsonschema.exceptions import ValidationError
from tau2.agent.base import LocalAgent, is_valid_agent_history_message
from tau2.data_model.message import MultiToolMessage

from policytrace.compatibility.multi_tool import parse_completion
from policytrace.data.manifests import canonical, digest
from policytrace.data.sft_format import tool_validators
from policytrace.policy import active_policy, student_system
from .context import ContextBuilder, HarnessError
from .model_client import ModelRequest


@dataclass
class AgentState:
    messages: list = field(default_factory=list)
    decision_index: int = 0


class StudentAgentAdapter(LocalAgent):
    def __init__(self, tools, domain_policy, tokenizer, client, episode_id, metadata,
                 *, max_tokens=16384, reserved_tokens=512, forbidden_markers=()):
        super().__init__(tools, domain_policy)
        self.client, self.tokenizer = client, tokenizer
        self.episode_id, self.metadata = episode_id, metadata
        schema = [t.openai_schema for t in tools]
        self.policy_config = active_policy()
        if hashlib.sha256(domain_policy.encode('utf-8')).hexdigest()!=self.policy_config['policy_sha256']:
            raise HarnessError('domain_policy_version_mismatch')
        system = student_system(domain_policy)
        self.builder = ContextBuilder(tokenizer, domain_policy, schema, system,
            max_tokens=max_tokens, reserved_tokens=reserved_tokens, forbidden_markers=forbidden_markers)
        self.validators = tool_validators(schema)
        self.decisions = []
        self.seed = None

    def set_seed(self, seed):
        self.seed = seed  # deterministic script; no provider seed claim
        if hasattr(self.client, 'set_seed'):
            self.client.set_seed(seed)

    def get_init_state(self, message_history=None):
        history = deepcopy(message_history or [])
        if not all(is_valid_agent_history_message(m) for m in history):
            raise HarnessError('invalid_agent_history')
        # Restoration is context-only; arbitrary mid-episode model cursor recovery is deferred.
        previous_indexes = [int(match[1]) for m in history for c in (getattr(m,'tool_calls',None) or [])
            if (match := re.fullmatch(re.escape(self.episode_id)+r'_t(\d+)_\d+',c.id))]
        return AgentState(history,max(previous_indexes,default=-1)+1)

    def generate_next_message(self, message, state):
        incoming = message.tool_messages if isinstance(message, MultiToolMessage) else [message]
        state.messages.extend(deepcopy(incoming))
        index = state.decision_index
        state.decision_index += 1
        decision_id = f'{self.episode_id}_d{index}'
        trace = {**self.metadata, 'episode_id': self.episode_id, 'decision_id': decision_id,
                 'decision_index': index, 'source': self.client.source, 'purpose': self.metadata.get('purpose', 'diagnostic'),
                 'started_at_unix': time.time(), 'parse_status': 'not_run', 'tool_attempts': [],
                 'error_code': None, 'logprobs': None, 'logprobs_missing_reason': 'No model forward in Stage 3_0'}
        self.decisions.append(trace)
        try:
            snapshot = self.builder.build(state.messages)
            trace['context'] = snapshot
            request = ModelRequest(decision_id, snapshot['prompt_text'], tuple(snapshot['prompt_token_ids']),
                canonical(snapshot['context_messages']), canonical(snapshot['tools']), canonical(snapshot['versions']),
                canonical({**getattr(self.client, 'sampling', {'temperature': 0}), 'seed': self.seed,
                           'max_output_tokens': self.builder.reserved_tokens}),
                (self.tokenizer.eos,), self.builder.reserved_tokens)
            trace['model_invocation_started'] = True
            response = self.client.generate(request)
            trace['generation'] = {'text': response.text, 'generated_token_ids': list(response.generated_token_ids),
                'token_provenance': response.token_provenance, 'stop_reason': response.stop_reason,
                'model_id': response.model_id, 'source': response.source, 'duration_seconds': response.duration_seconds,
                'provider_usage': response.provider_usage, 'missing_reason': response.missing_reason,
                'telemetry': response.telemetry}
            trace['logprobs'] = response.logprobs
            trace['logprobs_missing_reason'] = response.missing_reason if response.logprobs is None else None
            if response.source!=self.client.source or response.model_id!=self.client.model_id:
                raise HarnessError('model_response_provenance_mismatch')
            # Validate the provided IDs; do not replace real IDs with re-encoded text.
            if self.tokenizer.tokenizer.decode(response.generated_token_ids, skip_special_tokens=False) != response.text:
                raise HarnessError('completion_token_text_mismatch')
            n, p = len(response.generated_token_ids), snapshot['prompt_tokens']
            trace['student_action_token_spans'] = [{'completion_start': 0, 'completion_end': n,
                                                    'combined_start': p, 'combined_end': p+n}]
            trace['role_mask'] = {'condition_length': p, 'condition_value': 0,
                                 'student_action_length': n, 'student_action_value': 1,
                                 'scope': 'this_decision_only; not an SFT loss mask or assembled RL rollout mask'}
            # Denominator is syntactic call-attempt starts, including truncated starts.
            count = len(re.findall(r'<tool_call\b', response.text))
            ambiguous = ('<tool_call' in response.text and count == 0) or bool(re.search(r'<tool_call>[^<]*<tool_call>', response.text))
            trace['attempt_count_known'] = not ambiguous
            trace['tool_attempts'] = [{'attempt_id': f'{decision_id}_attempt{i}', 'status': 'pending_validation'} for i in range(count)]
            if n > request.reserved_generation_tokens:
                raise HarnessError('generation_overflow')
            try:
                result = parse_completion(response.text, self.validators, f'{self.episode_id}_t{index}', reject_mixed=False)
            except (ValueError, ValidationError) as exc:
                for attempt in trace['tool_attempts']:
                    attempt.update(status='parse_error', error_type=type(exc).__name__,
                                   reason='atomic_batch_validation_rejected; no call executed')
                trace['parse_status'] = 'error'
                trace['parser_error_type'] = type(exc).__name__
                raise HarnessError('parser_error') from exc
            trace['parse_status'] = 'ok'
            trace['native_message'] = result.model_dump(mode='json')
            trace['policy_flags'] = {'multiple_tool_calls': len(result.tool_calls or [])>1,
                'text_and_tool_calls': bool(result.has_text_content() and result.tool_calls),
                'authentication': 'not_evaluated', 'explicit_confirmation': 'not_evaluated',
                'user_simulator_fidelity': self.metadata.get('user_simulator_fidelity', 'unknown_scripted_not_real')}
            trace['protocol_features'] = {'multiple_tool_calls':len(result.tool_calls or [])>1,
                'text_and_tool_calls':bool(result.has_text_content() and result.tool_calls)}
            limit = self.policy_config['max_tool_calls_per_turn']
            trace['policy_flags']['multiple_tool_calls'] = limit is not None and len(result.tool_calls or [])>limit
            trace['policy_version'] = self.policy_config['version']
            for attempt, call in zip(trace['tool_attempts'], result.tool_calls or []):
                attempt.update(status='validated_not_executed', call_id=call.id, name=call.name, requestor=call.requestor)
            state.messages.append(result)
            return result, state
        except HarnessError as exc:
            trace['error_code'] = exc.code
            if 'snapshot' in exc.details:
                trace['context'] = exc.details['snapshot']
            raise
        except Exception as exc:
            trace['error_code'] = 'model_or_adapter_error'
            trace['exception_type'] = type(exc).__name__
            raise HarnessError('model_or_adapter_error') from exc
        finally:
            trace['ended_at_unix'] = time.time()

    async def agenerate_next_message(self, message, state):
        # Offline compatibility only, no asynchronous real inference claim.
        return self.generate_next_message(message, state)
