"""Lossless source pointers plus an explicit Student-visible projection."""
import json

from jsonschema import Draft202012Validator

from policytrace.data.manifests import digest

VISIBLE_MESSAGE_KEYS = {'role', 'content', 'tool_calls', 'tool_call_id', 'name'}


def tool_call(raw, call_id):
    if not isinstance(raw, dict):
        raise ValueError('invalid_tool_call')
    fn = raw.get('function', raw)
    name, args = fn.get('name'), fn.get('arguments')
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            raise ValueError('invalid_tool_arguments_json') from None
    if not isinstance(name, str) or not name or not isinstance(args, dict):
        raise ValueError('invalid_tool_call')
    return {'id': raw.get('id') or call_id, 'type': 'function',
            'function': {'name': name, 'arguments': args}}


def normalize_messages(messages, answer):
    if not isinstance(messages, list) or not messages or not isinstance(answer, dict):
        raise ValueError('invalid_structure')
    if answer.get('role') != 'assistant':
        raise ValueError('not_assistant_target')
    if messages[0].get('role') != 'system':
        raise ValueError('missing_system')
    normalized, excluded, pending = [], [], []
    for i, raw in enumerate(messages + [answer]):
        if not isinstance(raw, dict) or raw.get('role') not in {'system', 'user', 'assistant', 'tool'}:
            raise ValueError('invalid_role')
        role = raw['role']
        content = raw.get('content')
        if content is None:
            content = ''
        if not isinstance(content, str):
            raise ValueError('non_text_content')
        item = {'role': role, 'content': content}
        excluded.append({k: v for k, v in raw.items() if k not in VISIBLE_MESSAGE_KEYS})
        calls = raw.get('tool_calls') or []
        if calls:
            if role != 'assistant' or not isinstance(calls, list):
                raise ValueError('invalid_tool_role')
            if pending:
                raise ValueError('unanswered_tool_call')
            item['tool_calls'] = [tool_call(c, f'call_{i}_{j}') for j, c in enumerate(calls)]
            pending = [(c['function']['name'], c['id']) for c in item['tool_calls']]
        elif role == 'tool':
            name = raw.get('name')
            matching = next((j for j, (n, cid) in enumerate(pending)
                             if (name == n or raw.get('tool_call_id') == cid)), None)
            if matching is None:
                raise ValueError('orphan_tool_response')
            name, cid = pending.pop(matching)
            item.update(name=name, tool_call_id=cid)
        elif pending:
            raise ValueError('unanswered_tool_call')
        elif role == 'system' and i != 0:
            raise ValueError('late_system_message')
        normalized.append(item)
    if not normalized[-1]['content'].strip() and not normalized[-1].get('tool_calls'):
        raise ValueError('empty_target')
    return normalized[:-1], normalized[-1], excluded


def validate_calls(messages, validators, cache):
    errors = set()
    for msg in messages:
        for call in msg.get('tool_calls', []):
            fn = call['function']
            key = digest(fn)
            if key not in cache:
                cache[key] = fn['name'] in validators and validators[fn['name']].is_valid(fn['arguments'])
            if not cache[key]:
                errors.add('tool_schema_error')
    return sorted(errors)


def visible_projection(record):
    """Whitelisted export; privileged metadata/thinking never goes into the prompt."""
    return {'messages': record['messages'], 'answer': record['answer'],
            'provenance': {k: record[k] for k in ('sample_id', 'source_line', 'source_dialog_id',
                                                'turn_index', 'source_row_sha256')}}


def tool_validators(tools):
    return {t['function']['name']: Draft202012Validator(t['function']['parameters']) for t in tools}


def semantic_messages(messages):
    """IDs are routing artefacts; exclude them when checking shared history."""
    result = []
    for m in messages:
        entry = {'role': m['role'], 'content': m['content']}
        if m.get('name'):
            entry['name'] = m['name']
        if m.get('tool_calls'):
            entry['tool_calls'] = [c['function'] for c in m['tool_calls']]
        result.append(entry)
    return result
