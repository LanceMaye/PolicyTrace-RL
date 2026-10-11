"""Local-only Qwen ModelClient. Actual completion IDs are sliced, never reencoded."""
import json
import time

from policytrace.data.manifests import digest
from policytrace.harness.context import HarnessError
from policytrace.harness.model_client import ModelResponse
from .download import MODEL, verify_model


class TransformersQwenModelClient:
    source = 'real'
    model_id = MODEL

    def __init__(self, local_dir, tokenizer, *, weight_revision, device='cuda:0', dtype='bfloat16',
                 temperature=0.0, top_p=1.0, top_k=0, model=None, torch_module=None):
        if device != 'cuda:0' or dtype != 'bfloat16':
            raise ValueError('E0 v1 supports single CUDA GPU with BF16 only')
        self.tokenizer = tokenizer
        self.sampling = {'temperature':temperature,'top_p':top_p,'top_k':top_k}
        self.device, self.dtype = device, dtype
        self.stub = model is not None
        if self.stub:
            # Explicitly injected offline fake; cannot produce benchmark provenance.
            self.source, self.model_id = 'mock', 'mock:qwen-generation-stub'
            self.receipt = {'weight_revision':weight_revision,'stub':True}
        else:
            self.receipt = verify_model(local_dir, weight_revision)
        self.config_hash = digest({'model':self.model_id,'receipt':self.receipt,'sampling':self.sampling,
                                   'dtype':dtype,'device':device,'attention':'sdpa','kv_reuse':False})
        if torch_module is None:
            import torch as torch_module
        self.torch = torch_module
        if not self.stub:
            if not self.torch.cuda.is_available() or not self.torch.cuda.is_bf16_supported():
                raise HarnessError('BLOCKED_ENV')
            from transformers import AutoModelForCausalLM
            model = AutoModelForCausalLM.from_pretrained(str(local_dir), local_files_only=True,
                trust_remote_code=False, dtype=self.torch.bfloat16, attn_implementation='sdpa')
            model = model.to(device)
            model.eval()
        self.model = model
        self.hardware = None if self.stub else {'device_name':self.torch.cuda.get_device_name(0),
            'total_memory_bytes':self.torch.cuda.get_device_properties(0).total_memory,
            'cuda_version':self.torch.version.cuda}

    def set_seed(self, seed):
        self.torch.manual_seed(seed)
        if not self.stub:
            self.torch.cuda.manual_seed_all(seed)

    def generate(self, request):
        start = time.perf_counter()
        sampling = json.loads(request.sampling_json)
        if any(sampling.get(k) != v for k,v in self.sampling.items()):
            raise HarnessError('sampling_contract_mismatch')
        if request.stop_token_ids != (self.tokenizer.eos,):
            raise HarnessError('stop_token_contract_mismatch')
        ids = self.torch.tensor([list(request.prompt_token_ids)], dtype=self.torch.long, device=self.device)
        if not self.stub:
            self.torch.cuda.synchronize(); self.torch.cuda.reset_peak_memory_stats()
        from contextlib import nullcontext
        with (nullcontext() if self.stub else self.torch.inference_mode()):
            if self.stub:
                from types import SimpleNamespace as GenerationConfig
            else:
                from transformers import GenerationConfig
            generation = GenerationConfig(do_sample=self.sampling['temperature'] > 0,
                max_new_tokens=request.reserved_generation_tokens, eos_token_id=self.tokenizer.eos,
                pad_token_id=self.tokenizer.pad, use_cache=True, num_beams=1,
                **(self.sampling if self.sampling['temperature'] > 0 else {}))
            result = self.model.generate(input_ids=ids, attention_mask=self.torch.ones_like(ids),
                generation_config=generation, return_dict_in_generate=True,
                output_scores=False, output_logits=False, logits_to_keep=1)
        sequences = result.sequences.tolist()
        if len(sequences) != 1 or sequences[0][:len(request.prompt_token_ids)] != list(request.prompt_token_ids):
            raise HarnessError('generate_prompt_prefix_mismatch')
        completion = tuple(sequences[0][len(request.prompt_token_ids):])
        if not completion or len(completion) > request.reserved_generation_tokens:
            raise HarnessError('invalid_generated_length')
        if self.tokenizer.eos in completion[:-1]:
            raise HarnessError('tokens_after_generated_eos')
        if not self.stub:
            self.torch.cuda.synchronize()
        telemetry = {'gpu_peak_allocated_bytes':None if self.stub else self.torch.cuda.max_memory_allocated(),
                     'gpu_peak_reserved_bytes':None if self.stub else self.torch.cuda.max_memory_reserved(),
                     'gpu_generation_seconds':None if self.stub else time.perf_counter()-start,
                     'input_token_count':len(request.prompt_token_ids),'completion_token_count':len(completion),
                     'completion_eos_index':len(completion)-1 if completion[-1]==self.tokenizer.eos else None,
                     'hardware':self.hardware}
        return ModelResponse(self.tokenizer.tokenizer.decode(completion,skip_special_tokens=False), completion,
            'mock_encoded' if self.stub else 'model_generated', 'eos' if completion[-1] == self.tokenizer.eos else 'length',
            self.source, self.model_id, time.perf_counter()-start,
            missing_reason='Stub; no forward' if self.stub else 'Logprobs not requested; local IDs are instrumented, no provider bill',
            telemetry=telemetry)
