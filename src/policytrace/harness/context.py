"""Lossless model-visible projection and actual pinned Qwen prompt tokenization."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re

from policytrace.compatibility.multi_tool import validate_observations
from policytrace.data.manifests import canonical, digest
from policytrace.data.sft_tokenize import TOKENIZER_REVISION
from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage


class HarnessError(RuntimeError):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class IdentityProjector:
    version: str = 'identity-v0'
    def project(self, name: str, content: str | None) -> str | None:
        return content


class ContextBuilder:
    """No Task, scenario, evaluator criteria or provider raw_data accepted here."""
    def __init__(self, tokenizer, policy, tools, system_prompt, *, max_tokens=16384,
                 reserved_tokens=512, forbidden_markers=(), projector=None):
        self.tokenizer = tokenizer
        self.policy = policy
        self.tools = deepcopy(tools)
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.reserved_tokens = reserved_tokens
        self.forbidden_markers = tuple(forbidden_markers)
        self.projector = projector or IdentityProjector()
        if self.projector.version != 'identity-v0':
            raise ValueError('Only identity-v0 is accepted in Stage 3_0')
        self.versions = {'context': 'qwen-context-v1', 'projection': self.projector.version,
                         'tokenizer_revision': TOKENIZER_REVISION,
                         'policy_sha256': hashlib.sha256(policy.encode('utf-8')).hexdigest(),
                         'template_sha256': hashlib.sha256(tokenizer.raw_template.encode('utf-8')).hexdigest(),
                         'tools_sha256': digest(self.tools)}

    def build(self, history):
        messages = [{'role': 'system', 'content': self.system_prompt}]
        pending, observations, seen_ids = [], [], set()
        batch = None
        for native in history:
            if isinstance(native, AssistantMessage):
                if pending:
                    raise HarnessError('unanswered_tool_calls')
                item = {'role': 'assistant', 'content': native.content or ''}
                if native.tool_calls:
                    if any(c.id in seen_ids or c.requestor != 'assistant' for c in native.tool_calls):
                        raise HarnessError('invalid_call_identity')
                    ids = [c.id for c in native.tool_calls]
                    if len(ids) != len(set(ids)):
                        raise HarnessError('duplicate_call_identity')
                    seen_ids.update(ids)
                    item['tool_calls'] = [{'id': c.id, 'type': 'function',
                        'function': {'name': c.name, 'arguments': deepcopy(c.arguments)}} for c in native.tool_calls]
                    batch, pending, observations = native, list(native.tool_calls), []
                messages.append(item)
            elif isinstance(native, ToolMessage):
                if not pending or native.requestor != 'assistant' or native.id != pending[0].id:
                    raise HarnessError('observation_routing_mismatch')
                call = pending.pop(0)
                projected = self.projector.project(call.name, native.content)
                if projected != native.content:
                    raise HarnessError('identity_projection_changed_content')
                messages.append({'role': 'tool', 'content': projected, 'name': call.name,
                                 'tool_call_id': native.id})
                observations.append(native)
                if not pending:
                    validate_observations(batch, observations)
            elif isinstance(native, UserMessage) and not native.is_tool_call():
                if pending:
                    raise HarnessError('unanswered_tool_calls')
                messages.append({'role': 'user', 'content': native.content or ''})
            else:
                raise HarnessError('unapproved_context_message')
        if pending:
            raise HarnessError('unanswered_tool_calls')
        serialized = canonical({'messages': messages, 'tools': self.tools})
        # A canary in a visible body fails closed; hidden raw_data is never projected.
        if any(m and m in serialized for m in self.forbidden_markers):
            raise HarnessError('privacy_violation')
        prompt = self.tokenizer.render(messages, self.tools, generation=True)
        encoding = self.tokenizer.encode(prompt)
        ids = encoding.ids
        if self.tokenizer.tokenizer.decode(ids, skip_special_tokens=False) != prompt:
            raise HarnessError('prompt_roundtrip_error')
        roles = []
        starts = list(re.finditer(r'<\|im_start\|>(system|user|assistant)\n', prompt))
        for i, match in enumerate(starts):
            end = starts[i+1].start() if i+1 < len(starts) else len(prompt)
            token_indexes = [j for j, (a,b) in enumerate(encoding.offsets) if a >= match.start() and b <= end]
            roles.append({'rendered_role': match.group(1), 'char_start': match.start(), 'char_end': end,
                          'token_start': min(token_indexes), 'token_end': max(token_indexes)+1,
                          'current_student_action': False})
        tool_counts = []
        for m in messages:
            if m['role'] == 'tool':
                content = m['content'] or ''
                tool_counts.append({'id': m['tool_call_id'], 'name': m['name'],
                    'content_tokens': len(self.tokenizer.encode(content).ids),
                    'raw_sha256': digest(m['content']), 'model_sha256': digest(m['content'])})
        system_end = starts[1].start() if len(starts)>1 else len(prompt)
        system_tokens = sum(1 for a,b in encoding.offsets if b <= system_end)
        policy_tokens = len(self.tokenizer.encode(self.policy).ids)
        schema_tokens = len(self.tokenizer.encode(canonical(self.tools)).ids)
        snapshot = {'context_messages': messages, 'tools': deepcopy(self.tools), 'versions': self.versions,
                    'prompt_text': prompt, 'prompt_token_ids': ids, 'prompt_tokens': len(ids),
                    'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
                    'prompt_ids_sha256': digest(ids), 'context_sha256': digest(messages),
                    'history_messages': len(history), 'history_assistant_messages': sum(isinstance(m,AssistantMessage) for m in history),
                    'condition_token_spans': roles, 'tool_observations': tool_counts,
                    'token_accounting': {'system_rendered_tokens': system_tokens,
                        'policy_standalone_tokens': policy_tokens, 'schema_standalone_tokens': schema_tokens,
                        'system_fraction': system_tokens/len(ids), 'policy_standalone_fraction': policy_tokens/len(ids),
                        'schema_standalone_fraction': schema_tokens/len(ids),
                        'method': 'standalone policy/schema counts are exact encodings, nonadditive because of wrapper and BPE'},
                    'window_budget': {'max_tokens': self.max_tokens, 'reserved_generation_tokens': self.reserved_tokens,
                                      'required_tokens': len(ids)+self.reserved_tokens}}
        if len(ids)+self.reserved_tokens > self.max_tokens:
            raise HarnessError('context_overflow', {'snapshot': snapshot})
        return snapshot
