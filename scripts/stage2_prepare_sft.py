import gzip
import io
import json
from contextlib import ExitStack
from collections import Counter, defaultdict
import yaml

from policytrace.data.manifests import ROOT, canonical, digest, file_hash, quantiles, read_json, read_jsonl, write_json
from policytrace.data.sft_format import visible_projection
from policytrace.data.sft_tokenize import QwenTokenizer, TOKENIZER_REVISION


def main():
    cfg = yaml.safe_load((ROOT/'configs/data/preprocess_config.yaml').read_text(encoding='utf-8'))
    if cfg['tokenizer_revision'] != TOKENIZER_REVISION or cfg['truncate']:
        raise ValueError('Unsupported preprocessing configuration')
    p = ROOT/'data/private/stage2'; out = ROOT/'data/processed/stage2'
    out.mkdir(parents=True, exist_ok=True)
    audit = read_json(ROOT/'reports/stage2/source_audit.json')
    if file_hash(p/'normalized_source.jsonl') != audit['private_artifacts']['normalized_source.jsonl']:
        raise ValueError('Stale normalization')
    assignments = read_json(p/'assignments.json')['sft']
    tools = read_json(p/'tools.json'); tokenizer = QwenTokenizer()
    lengths = defaultdict(list); supervised = defaultdict(list)
    counts, failures, native = Counter(), Counter(), Counter()
    variants = Counter(); receipts = []
    handles = {}; stack = ExitStack()
    for split in ('train','val','heldout_from_sft','quality_excluded'):
        handles[(split,'normalized')] = stack.enter_context((out/f'sft_{split}.jsonl').open('w', encoding='utf-8', newline='\n'))
    for split in ('train','val'):
        for kind,suffix in [('tokens','tokenized'),('oversize','oversize.tokenized')]:
            binary = stack.enter_context((out/f'sft_{split}.{suffix}.jsonl.gz').open('wb'))
            zipped = stack.enter_context(gzip.GzipFile(filename='',mode='wb',fileobj=binary,mtime=0,compresslevel=3))
            handles[(split,kind)] = stack.enter_context(io.TextIOWrapper(zipped,encoding='utf-8',newline='\n'))
    try:
        for row in read_jsonl(p/'normalized_source.jsonl'):
            split = assignments[row['source_dialog_id']]
            view = visible_projection(row)
            handles[(split,'normalized')].write(canonical(view)+'\n')
            counts['normalized_'+split] += 1
            if split not in ('train','val'): continue
            try:
                tokenized = tokenizer.prepare(view['messages'], view['answer'], tools)
            except ValueError as exc:
                code = str(exc); failures[code] += 1
                receipts.append({'sample_id':row['sample_id'], 'reason':'tokenization_error', 'code':code})
                continue
            n = len(tokenized['input_ids'])
            lengths['all'].append(n); lengths[split].append(n)
            supervised['all'].append(tokenized['supervised_tokens']); supervised[split].append(tokenized['supervised_tokens'])
            native[str(tokenized['native_full_encoding_equal'])] += 1
            variants['tool_call' if view['answer'].get('tool_calls') else 'text'] += 1
            tokenized.update(provenance=view['provenance'])
            kind = 'tokens' if n <= cfg['max_length'] else 'oversize'
            handles[(split,kind)].write(canonical(tokenized)+'\n')
            counts[f'{split}_{kind}'] += 1
            if kind == 'oversize': receipts.append({'sample_id':row['sample_id'], 'reason':f'exceeds_{cfg["max_length"]}_no_truncation', 'tokens':n})
            if len(lengths['all']) % 1000 == 0: print(json.dumps({'progress_tokenized':len(lengths['all'])}),flush=True)
    finally:
        stack.close()
    write_json(p/'sft_tokenization_exclusions.json', receipts)
    tm = read_json(ROOT/'data/tokenizers/qwen2.5-3b-instruct/manifest.json')
    report = {'status':'PASS' if not failures else 'FAIL','config':cfg,'config_sha256':digest(cfg),
        'tokenizer':{**tm,'chat_template_sha256':digest(tokenizer.raw_template),
            'special_token_ids':{'im_start':tokenizer.im_start,'eos':tokenizer.eos,'pad':tokenizer.pad,
                'tool_call_start':tokenizer.tokenizer.token_to_id('<tool_call>'),'tool_call_end':tokenizer.tokenizer.token_to_id('</tool_call>')},
            'jinja_generation_mask_supported':False,'implementation':'Rust tokenizers plus unchanged pinned Jinja template and HF-compatible JSON filter'},
        'counts':dict(counts),'tokenization_errors':dict(failures),'native_full_encoding_equal':dict(native),
        'actual_token_lengths':{s:quantiles(ns) for s,ns in lengths.items()},
        'actual_supervised_tokens':{s:quantiles(ns) for s,ns in supervised.items()},
        'context_budget_views':{str(cap):{'retained':sum(n<=cap for n in lengths['all']), 'oversize':sum(n>cap for n in lengths['all'])} for cap in (4096,8192,16384,32768)},
        'mask_validation':{'samples_checked':len(lengths['all']),'target_forms':dict(variants),
            'array_length_mismatches':0 if not failures else None, 'empty_supervision':0 if not failures else None,
            'history_user_tool_system_supervised':0 if not failures else None,
            'target_tool_serialization_roundtrip':'PASS' if not failures else 'FAIL',
            'padding_validation':'separate synthetic collator test; exported real rows are unpadded',
            'target_span':'inference prefill excluded; answer body and EOS included; trailing template newline excluded'},
        'artifacts':{path.name:{'sha256':file_hash(path),'size_bytes':path.stat().st_size} for path in sorted(out.iterdir()) if path.is_file()},
        'training_readiness':{'structural_format_and_mask':'PASS' if not failures else 'FAIL',
            'business_policy_alignment':'REVIEW_REQUIRED_SOURCE_POLICY_DIFFERS_FROM_FIXED_FORK',
            'default_view':'16K preserves all valid expert turns; no 8K reduction is enabled'},
        'training_executed':False,'paid_api_calls':0,'weights_downloaded':False}
    write_json(ROOT/'reports/stage2/quality_report.json', report)
    print(json.dumps({k:report[k] for k in ('status','counts','tokenization_errors','actual_token_lengths','context_budget_views','mask_validation')},ensure_ascii=False))
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
