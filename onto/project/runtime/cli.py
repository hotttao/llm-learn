"""OntoOps 命令行入口。

用法（在 project/ 目录下）：
  python -m runtime.cli demo scenarios/payment-incident.json   # Mock 全流程演示
  python -m runtime.cli inspect                                # 本体摘要 + LLM 投影预览
  python -m runtime.cli validate scenarios/payment-incident.json
  python -m runtime.cli chat scenarios/payment-incident.json   # 接真实 LLM（读环境变量）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from runtime.actions import Executor
from runtime.agent import Agent
from runtime.llm import MockLLM, OpenAICompatibleLLM
from runtime.ontology import Ontology
from runtime.validator import Validator
from runtime.world import World


def _reconfigure_stdout():
    """Windows 控制台中文输出保障。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _load_scenario(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_world(ont: Ontology, entities: list) -> World:
    """初始世界也要过一遍全量校验：场景文件本身非法时直接拒绝启动。"""
    world = World.from_entities([dict(e) for e in entities])
    errs = []
    for e in world.entities.values():
        errs.extend(ont.validate_entity(e))
    errs.extend(Validator(ont).validate_world(world))
    if errs:
        raise SystemExit("初始世界状态非法:\n  " + "\n  ".join(errs))
    return world


def cmd_inspect(args):
    ont = Ontology.load(args.ontology)
    print(ont.summary())
    print()
    print(ont.describe_for_llm())
    print("\n# 策略规则（治理层）")
    for r in ont.rules:
        print(f"- {r['id']}: 当 {r.get('when')} → {r.get('require')}")


def cmd_validate(args):
    ont = Ontology.load(args.ontology)
    sc = _load_scenario(args.scenario)
    _build_world(ont, sc["entities"])
    print(f"✓ 场景初始状态通过实体 schema 与领域约束校验（{_count(sc)} 实体）")


def _count(sc):
    return len(sc["entities"])


def cmd_demo(args):
    ont = Ontology.load(args.ontology)
    sc = _load_scenario(args.scenario)
    world = _build_world(ont, sc["entities"])
    print(f"场景: {sc.get('name', '')}")
    print(f"{world.stats()}\n")

    llm = MockLLM(sc.get("script", []))
    executor = Executor(ont, world, Validator(ont), auto_approve=True)
    agent = Agent(ont, world, llm, executor, sc["goal"])
    ok = agent.run()

    print("\n" + "=" * 62)
    print("审计轨迹（每步动作与结局）:")
    for a in agent.audit:
        print(f"  step{a['step']:>2}  {a['action']:<24} {a['outcome']}")
    print(f"\n终态: {world.stats()}")
    for s in sorted(world.query("Service"), key=lambda x: x.get("name", "")):
        print(f"  service {s['name']:<14} [{s['tier']:<12}] {s['status']}")
    for i in sorted(world.query("Incident"), key=lambda x: x.get("id", "")):
        print(f"  incident {i['id']} [{i['status']}] affects={i.get('affected_services')}")
    sys.exit(0 if ok else 1)


def cmd_chat(args):
    ont = Ontology.load(args.ontology)
    if args.scenario:
        sc = _load_scenario(args.scenario)
        world = _build_world(ont, sc["entities"])
        goal = sc["goal"]
        print(f"场景: {sc.get('name', '')} | {world.stats()}")
    else:
        world = World()
        goal = input("请输入任务目标: ").strip()

    llm = OpenAICompatibleLLM()
    if not llm.api_key:
        raise SystemExit("未检测到 OPENAI_API_KEY（另可选 OPENAI_BASE_URL / ONTO_MODEL）")

    def approver(spec, rule, resolved):
        targets = ", ".join(
            (r.get("name") or r.get("id") or "?") for r in resolved.values() if isinstance(r, dict)
        )
        ans = input(
            f"\n[审批请求] {spec.get('risk')} 风险动作 {spec.get('name') or ''} → {targets}"
            f"（规则 {rule.get('id')}）批准? [y/N] "
        )
        return ans.strip().lower() in ("y", "yes")

    executor = Executor(ont, world, Validator(ont), auto_approve=False, approver=approver)
    ok = Agent(ont, world, llm, executor, goal).run()
    sys.exit(0 if ok else 1)


def main(argv=None):
    _reconfigure_stdout()
    p = argparse.ArgumentParser(prog="ontoops", description="本体驱动的运维排障 Agent")
    p.add_argument("--ontology", default=str(BASE / "ontology"), help="本体目录")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("demo", help="Mock 剧本演示（无需 API key）")
    s.add_argument("scenario")
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("chat", help="接真实 LLM 交互排障")
    s.add_argument("scenario", nargs="?", default=None)
    s.set_defaults(fn=cmd_chat)

    s = sub.add_parser("inspect", help="打印本体摘要与 LLM 投影")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("validate", help="校验场景初始状态")
    s.add_argument("scenario")
    s.set_defaults(fn=cmd_validate)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
