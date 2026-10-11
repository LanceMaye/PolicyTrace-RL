"""Aggregate declared EpisodeRecords offline; never calls a model or evaluator."""
import argparse
import json
from pathlib import Path

from policytrace.evaluation.metrics import aggregate
from policytrace.evaluation.schema import EpisodeRecord, EvaluationPlan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='JSON bundle {plan, episodes} or EpisodeRecord JSONL')
    parser.add_argument('--plan', type=Path, help='EvaluationPlan JSON required for JSONL')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.plan:
            plan = EvaluationPlan.model_validate_json(args.plan.read_text(encoding='utf-8-sig'))
            episodes = [EpisodeRecord.model_validate_json(line) for line in args.input.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
        else:
            bundle = json.loads(args.input.read_text(encoding='utf-8-sig'))
            plan = EvaluationPlan.model_validate(bundle['plan'])
            episodes = [EpisodeRecord.model_validate(row) for row in bundle['episodes']]
        summary = aggregate(plan, episodes)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # Validation errors can include arbitrary input values; do not echo them.
        parser.exit(2, f'Invalid offline input ({type(exc).__name__}); no summary written.\n')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': summary['status'], 'provenance': summary['provenance'],
                      'coverage': summary['coverage'], 'output': args.output.as_posix()}))
    if summary['status'] == 'incomplete':
        raise SystemExit(3)


if __name__ == '__main__':
    main()
