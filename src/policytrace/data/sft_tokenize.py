"""Pinned Qwen Jinja template + Rust tokenizer, without Transformers or Torch."""
import json
import re
from pathlib import Path

from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer

from policytrace.data.manifests import ROOT, file_hash, read_json, digest

TOKENIZER_REVISION = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
EXPECTED_FILES = {'tokenizer.json': 'c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539',
                  'tokenizer_config.json': '5b5d4f65d0acd3b2d56a35b56d374a36cbc1c8fa5cf3b3febbbfabf22f359583'}


def qwen_messages(messages):
    """Adapt the agent protocol wrapper, preserve the source business policy verbatim.

    The source wrapper says 'valid JSON only', although its assistant text is
    plain natural language. Qwen's template specifies XML-wrapped tool JSON.
    The same wrapper function must be used by the later inference harness.
    """
    result = [dict(m) for m in messages]
    system = result[0]['content']
    if '<policy>' in system and '</policy>' in system:
        policy = system.rsplit('<policy>', 1)[1].split('</policy>', 1)[0]
        result[0]['content'] = ('You are a customer service agent. Follow the business policy below. '
            'Respond to the customer in natural language, or call the provided tools using their specified protocol. '
            'Follow the policy rules on authentication, confirmation and allowed operations.\n<policy>' + policy + '</policy>')
    return result


def parse_serialized_calls(text):
    """Data round-trip validation, not an agent harness or permissive parser."""
    calls = []
    for chunk in re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>', text, re.S):
        fn = json.loads(chunk)
        if set(fn) != {'name', 'arguments'} or not isinstance(fn['arguments'], dict):
            raise ValueError('Invalid Qwen serialized function')
        calls.append(fn)
    return calls


class QwenTokenizer:
    def __init__(self, root=None):
        root = Path(root or ROOT/'data/tokenizers/qwen2.5-3b-instruct')
        manifest = read_json(root/'manifest.json')
        if manifest['revision'] != TOKENIZER_REVISION or manifest['model'] != 'Qwen/Qwen2.5-3B-Instruct':
            raise ValueError('Unpinned tokenizer')
        for name, expected in EXPECTED_FILES.items():
            if file_hash(root/name) != expected: raise ValueError('Tokenizer content mismatch')
        self.config = read_json(root/'tokenizer_config.json')
        self.tokenizer = Tokenizer.from_file(str(root/'tokenizer.json'))
        self.raw_template = self.config['chat_template']
        env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        # Hugging Face's tojson uses JSON rather than Jinja HTML-safe escaping.
        env.filters['tojson'] = lambda value, **kwargs: json.dumps(value, ensure_ascii=False, **kwargs)
        self.template = env.from_string(self.raw_template)
        self.eos = self.tokenizer.token_to_id(self.config['eos_token'])
        self.pad = self.tokenizer.token_to_id(self.config['pad_token'])
        self.im_start = self.tokenizer.token_to_id('<|im_start|>')
        if (self.im_start, self.eos, self.pad) != (151644, 151645, 151643):
            raise ValueError('Unexpected special tokens')

    def render(self, messages, tools, generation=False):
        return self.template.render(messages=qwen_messages(messages), tools=tools, add_generation_prompt=generation)

    def encode(self, text):
        return self.tokenizer.encode(text, add_special_tokens=False)

    def prepare(self, messages, answer, tools):
        prompt = self.render(messages, tools, True)
        full = self.render(messages + [answer], tools, False)
        if not full.startswith(prompt): raise ValueError('Template target is not a suffix of the inference prefill')
        target = full[len(prompt):]
        # Encode at the inference boundary. This also handles a BPE merge that
        # would otherwise straddle masked prompt and supervised target chars.
        prefix = self.encode(prompt)
        completion = self.encode(target)
        ids = prefix.ids + completion.ids
        try: eos_index = completion.ids.index(self.eos)
        except ValueError: raise ValueError('Target EOS missing') from None
        if eos_index == 0: raise ValueError('Empty supervised target')
        if any(x in completion.ids[:eos_index] for x in (self.im_start, self.eos, self.pad)):
            raise ValueError('Control token in target body')
        if target[completion.offsets[eos_index][1]:].strip(): raise ValueError('Content after target EOS')
        labels = [-100]*len(prefix.ids) + completion.ids[:eos_index+1] + [-100]*(len(completion.ids)-eos_index-1)
        if self.tokenizer.decode(ids, skip_special_tokens=False) != full:
            raise ValueError('Token round-trip mismatch')
        expected_calls = [c['function'] for c in answer.get('tool_calls', [])]
        if parse_serialized_calls(target) != expected_calls: raise ValueError('Tool serialization mismatch')
        record = {'input_ids': ids, 'attention_mask': [1]*len(ids), 'labels': labels,
            'prompt_tokens': len(prefix.ids), 'supervised_tokens': eos_index+1,
            'serialized_sha256': digest(full), 'native_full_encoding_equal': self.encode(full).ids == ids}
        validate_labels(record, self.eos)
        return record


def validate_labels(record, eos):
    ids, mask, labels = record['input_ids'], record['attention_mask'], record['labels']
    if not len(ids) == len(mask) == len(labels): raise ValueError('Array length mismatch')
    start = record['prompt_tokens']; size = record['supervised_tokens']
    if start < 1 or size < 2 or start+size > len(ids): raise ValueError('Invalid target span')
    for i, (token, attend, label) in enumerate(zip(ids, mask, labels)):
        should_learn = start <= i < start+size
        if label != (token if should_learn else -100): raise ValueError('Loss mask mismatch')
        if attend not in (0,1) or (not attend and label != -100): raise ValueError('Padding supervised')
    if labels[start+size-1] != eos: raise ValueError('Target EOS is not supervised')


def pad_records(records, pad_id):
    n = max(len(r['input_ids']) for r in records)
    padded = []
    for r in records:
        p = n-len(r['input_ids'])
        padded.append({**r, 'input_ids': r['input_ids']+[pad_id]*p,
            'attention_mask': r['attention_mask']+[0]*p, 'labels': r['labels']+[-100]*p})
    return padded
