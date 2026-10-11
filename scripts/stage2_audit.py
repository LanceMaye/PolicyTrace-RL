from policytrace.data.source_audit import audit
import json

if __name__ == '__main__':
    report = audit()
    print(json.dumps({'retail_sft_turns': report['sft']['retail_turns'],
        'retail_dialogues': report['sft']['source_dialogues'], 'retail_rl_tasks': report['rl']['retail'],
        'overlap': report['overlap'], 'format_errors': report['sft']['format_error_rows']}, ensure_ascii=False))
