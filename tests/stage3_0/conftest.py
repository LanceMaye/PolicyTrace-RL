from pathlib import Path
import uuid
import pytest
from loguru import logger

from policytrace.data.manifests import ROOT
from policytrace.data.sft_tokenize import QwenTokenizer
from policytrace.harness.fixtures import fixture_scripts
from policytrace.harness.runner import run_episode, OfflineConfig
from policytrace.harness.verification import offline_guard


@pytest.fixture(scope='session', autouse=True)
def private_logging():
    folder = ROOT/'data/private/stage3_0/tests'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    logger.remove()
    logger.add(str(folder/'execution.log'),level='DEBUG',encoding='utf-8')
    return folder


@pytest.fixture(autouse=True)
def no_network():
    with offline_guard():
        yield


@pytest.fixture(scope='session')
def tokenizer():
    return QwenTokenizer()


@pytest.fixture(scope='session')
def scripts():
    return fixture_scripts()


@pytest.fixture
def run(tokenizer, private_logging):
    def execute(student, user, **kwargs):
        path = private_logging/uuid.uuid4().hex
        return run_episode(kwargs.pop('task_id','retail_152'),student,user,path,tokenizer=tokenizer,**kwargs)
    return execute


@pytest.fixture(scope='module')
def episodes(tokenizer, private_logging, scripts):
    from dataclasses import replace
    config = OfflineConfig()
    result = {}
    for name in ('readonly','write','multi_read','partial_write_error','mixed'):
        for strict in ((True,False) if name=='mixed' else (True,)):
            student,user = scripts[name]
            result[name,strict] = run_episode('retail_152',student,user,
                private_logging/f'fixture_{name}_{strict}',tokenizer=tokenizer,
                config=replace(config,validate_communication=strict),trial_id=f'{name}_{strict}')
    return result
