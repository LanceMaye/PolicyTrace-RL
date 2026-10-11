"""Offline diagnosis of the saved real run; never changes its official score."""
import json
from pathlib import Path

from deepdiff import DeepDiff
from policytrace.stage0.task_loader import load_retail_task, iter_retail_records
from policytrace.stage0.db_adapter import load_retail_db, make_retail_env
from policytrace.stage0.reference_check import reference_fixture
from policytrace.stage0.evaluator_adapter import evaluate_with_correct_initial_state
from tau2.data_model.simulation import SimulationRun
from tau2.data_model.message import AssistantMessage, ToolMessage


def main() -> None:
    root = Path('data/raw')
    record = next(load_retail_task(raw,i) for i,raw in iter_retail_records(root) if raw['id']=='retail_131')
    snapshot = load_retail_db(record.db_path,root)
    private = Path('data/private/stage0/deepseek')
    real = SimulationRun.model_validate_json((private/'retail_131-episode.json').read_text(encoding='utf-8'))
    expected, _ = reference_fixture(record,snapshot)
    gold, actual = make_retail_env(record,snapshot), make_retail_env(record,snapshot)
    gold.set_state(None,None,expected.messages)
    actual.set_state(None,None,real.messages)
    diff = DeepDiff(gold.tools.db.model_dump(),actual.tools.db.model_dump())
    (private/'retail_131-db-diff.json').write_text(diff.to_json(indent=2),encoding='utf-8')
    # An explicitly labeled counterfactual fixture: update only the country argument,
    # then regenerate tool responses with the real environment and rescore offline.
    diagnostic = real.model_copy(deep=True)
    diagnostic.id = 'offline-country-normalization-counterfactual'
    env = make_retail_env(record,snapshot)
    messages = []
    replacements = 0
    for message in diagnostic.messages:
        if isinstance(message,ToolMessage):
            continue
        if isinstance(message,AssistantMessage) and message.tool_calls:
            for call in message.tool_calls:
                if call.name=='modify_user_address' and call.arguments.get('country')=='United States':
                    call.arguments['country']='USA'
                    replacements += 1
            messages.append(message)
            messages.extend(env.get_response(call) for call in message.tool_calls)
        else:
            messages.append(message)
    diagnostic.messages = messages
    reward = evaluate_with_correct_initial_state(record,snapshot,diagnostic)
    result = {'task_id':'retail_131', 'mode':'offline counterfactual; NOT real episode result',
              'original_official_reward':evaluate_with_correct_initial_state(record,snapshot,real).reward,
              'db_diff_categories':list(diff), 'changed_value_count':len(diff.get('values_changed',{})),
              'country_argument_replacements':replacements, 'counterfactual_official_reward':reward.reward,
              'counterfactual_db_match':reward.db_check.db_match,
              'diagnosis':'Country string USA versus United States; original score remains unchanged'}
    Path('reports/stage0/real_diagnosis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    if replacements != 1 or len(diff.get('values_changed',{})) != 1 or reward.reward != 1:
        raise SystemExit('Country-only explanation not confirmed')


if __name__ == '__main__':
    main()
