import socket
import pytest

from policytrace.data.manifests import ROOT, read_json, read_jsonl
from policytrace.data.sft_tokenize import QwenTokenizer


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError('Stage 2 tests must be offline')
    monkeypatch.setattr(socket.socket, 'connect', deny)


@pytest.fixture(scope='session')
def tokenizer(): return QwenTokenizer()


@pytest.fixture(scope='session')
def tools(): return read_json(ROOT/'data/private/stage2/tools.json')


@pytest.fixture(scope='session')
def prepared():
    p = ROOT/'data/private/stage2'
    return {'rl':list(read_jsonl(p/'rl_features.jsonl')), 'dialogs':list(read_jsonl(p/'dialog_features.jsonl')),
            'overlap':list(read_jsonl(p/'overlap_candidates.jsonl')), 'assignments':read_json(p/'assignments.json'),
            'audit':read_json(ROOT/'reports/stage2/source_audit.json'),
            'split':read_json(ROOT/'reports/stage2/split_statistics.json')}
