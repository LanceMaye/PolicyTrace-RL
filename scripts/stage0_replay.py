"""Display a saved real episode; optionally rescore it offline, with zero model calls."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = {'assistant':'Agent（DeepSeek / 客服）','user':'User Simulator（DeepSeek / 客户）','tool':'Environment（Python 工具）'}


def tool_summary(content: str) -> str:
    try:
        obj = json.loads(content)
    except (ValueError,TypeError):
        return content
    if isinstance(obj,dict):
        fields = ('user_id','order_id','status','address','name','orders')
        filtered = {k:obj[k] for k in fields if k in obj}
        return json.dumps(filtered or obj,ensure_ascii=False,indent=2)
    return json.dumps(obj,ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id',choices=['retail_131','retail_152'],default='retail_131')
    parser.add_argument('--full-tools',action='store_true')
    parser.add_argument('--validate',action='store_true',help='Call official evaluator offline; no API requests')
    args = parser.parse_args()
    folder = ROOT/'data/private/stage0/deepseek'
    raw = (folder/f'{args.task_id}-episode.json').read_text(encoding='utf-8')
    simulation = json.loads(raw)
    reward = json.loads((folder/f'{args.task_id}-reward.json').read_text(encoding='utf-8'))
    print(f"已保存真实 Episode 回放：{args.task_id}。本命令不调用模型，不产生 API 费用。")
    print('问候由 Orchestrator 提供；后续 Agent / User 回答由不同上下文的 DeepSeek 请求生成。')
    for index,message in enumerate(simulation['messages']):
        print(f"\n[{index:02d}] {LABELS.get(message['role'],message['role'])}")
        if message.get('tool_calls'):
            for call in message['tool_calls']:
                print('请求工具：'+call['name'])
                print(json.dumps(call['arguments'],ensure_ascii=False,indent=2))
        if message.get('content'):
            content = message['content']
            if message['role']=='tool' and not args.full_tools:
                content = tool_summary(content)
            print(content)
        if message['role']=='tool':
            print(f"工具响应 error={message.get('error')}")
    print(f"\n终止：{simulation['termination_reason']}；保存的官方 reward：{reward['reward']}")
    print('工具成功、用户停止、官方评分是三个分别记录的结果。')
    if args.validate:
        from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
        from policytrace.stage0.db_adapter import load_retail_db
        from policytrace.stage0.evaluator_adapter import evaluate_with_correct_initial_state
        from tau2.data_model.simulation import SimulationRun
        record = next(load_retail_task(r,i) for i,r in iter_retail_records(ROOT/'data/raw') if r['id']==args.task_id)
        snapshot = load_retail_db(record.db_path,ROOT/'data/raw')
        checked = evaluate_with_correct_initial_state(record,snapshot,SimulationRun.model_validate_json(raw))
        print(f"离线重新调用官方评分器：reward={checked.reward}；db_match={checked.db_check.db_match if checked.db_check else None}")
        if checked.model_dump(mode='json') != reward:
            raise SystemExit('FAIL: offline score differs from saved official result')
        print('PASS：重新评分与保存结果完全一致。')


if __name__=='__main__':
    main()
