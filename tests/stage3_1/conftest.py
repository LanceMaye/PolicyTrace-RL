from uuid import uuid4
import pytest
from loguru import logger
from policytrace.data.manifests import ROOT
from policytrace.data.sft_tokenize import QwenTokenizer
from policytrace.harness.verification import offline_guard


@pytest.fixture(scope='session', autouse=True)
def private_log():
    folder=ROOT/'data/private/stage3_1/tests'/uuid4().hex;folder.mkdir(parents=True)
    logger.remove();logger.add(folder/'native.log',level='DEBUG')
    return folder


@pytest.fixture(autouse=True)
def no_network():
    with offline_guard() as attempts:
        yield attempts


@pytest.fixture(scope='session')
def tokenizer():
    return QwenTokenizer()
