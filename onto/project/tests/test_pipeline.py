# -*- coding: utf-8 -*-
"""端到端测试：不需要 API key，全部确定性。

覆盖三条主线：
  1. 本体可加载，场景初始状态合法（实体 schema + 领域约束）
  2. 护栏三连：无单重启被前置条件拦；未恢复关单被约束拦并回滚；
     critical 缩容低于下限被约束拦并回滚
  3. Mock 剧本全流程跑通，终态健康、无告警、全部关单、留有审计台账
"""
import json
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from runtime.actions import ActionError, Executor
from runtime.agent import Agent
from runtime.llm import MockLLM
from runtime.ontology import Ontology
from runtime.validator import Validator
from runtime.world import World

ONT = Ontology.load(PROJECT / "ontology")
SCENARIO = json.loads(
    (PROJECT / "scenarios" / "payment-incident.json").read_text(encoding="utf-8")
)


def make_world() -> World:
    return World.from_entities([dict(e) for e in SCENARIO["entities"]])


def make_executor(world: World) -> Executor:
    return Executor(ONT, world, Validator(ONT), auto_approve=True, emit=lambda *a, **k: None)


class TestOntologyLoading(unittest.TestCase):
    def test_loads(self):
        self.assertGreaterEqual(len(ONT.entity_types), 6)
        self.assertGreaterEqual(len(ONT.actions), 9)
        self.assertGreaterEqual(len(ONT.constraints), 4)

    def test_every_action_declares_risk_and_class(self):
        for name, spec in ONT.actions.items():
            self.assertIn("risk", spec, f"{name} 缺 risk")
            self.assertIn("effect_class", spec, f"{name} 缺 effect_class")

    def test_scenario_initial_state_valid(self):
        world = make_world()
        errs = []
        for e in world.entities.values():
            errs.extend(ONT.validate_entity(e))
        self.assertEqual(errs, [])
        self.assertEqual(Validator(ONT).validate_world(world), [])

    def test_entity_schema_rejects_unknown_field(self):
        errs = ONT.validate_entity({"type": "Service", "name": "x", "tier": "critical",
                                    "owner_team": "t", "bogus_field": 1})
        self.assertTrue(any("未定义的属性" in m for m in errs))


class TestGuardrails(unittest.TestCase):
    def test_restart_blocked_without_incident(self):
        world, ex = make_world(), None
        ex = make_executor(world)
        with self.assertRaises(ActionError) as ctx:
            ex.execute("restart_service", {"service": "payment-db"})
        self.assertEqual(ctx.exception.stage, "precondition")
        # 状态未被改动
        self.assertEqual(world.get("Service", "payment-db")["status"], "down")

    def test_resolve_blocked_and_rolled_back_when_unhealthy(self):
        world = make_world()
        ex = make_executor(world)
        ex.execute("create_incident", {"service": "payment-db", "severity": "sev1", "summary": "t"})
        with self.assertRaises(ActionError) as ctx:
            ex.execute("resolve_incident", {"incident": "INC-1001"})
        self.assertEqual(ctx.exception.stage, "constraint")
        # 关键断言：效果已应用又被回滚——status 回到 open
        self.assertEqual(world.get("Incident", "INC-1001")["status"], "open")

    def test_scale_below_min_rolls_back(self):
        world = make_world()
        ex = make_executor(world)
        with self.assertRaises(ActionError) as ctx:
            ex.execute("scale_service", {"service": "payment-db", "replicas": 1})
        self.assertEqual(ctx.exception.stage, "constraint")
        self.assertEqual(world.get("Service", "payment-db")["replicas"], 3)

    def test_unknown_entity_ref_param(self):
        ex = make_executor(make_world())
        with self.assertRaises(ActionError) as ctx:
            ex.execute("restart_service", {"service": "no-such-service"})
        self.assertEqual(ctx.exception.stage, "param")

    def test_unknown_action_dispatch(self):
        ex = make_executor(make_world())
        with self.assertRaises(ActionError) as ctx:
            ex.execute("drop_database", {})
        self.assertEqual(ctx.exception.stage, "dispatch")


class TestDemoEndToEnd(unittest.TestCase):
    def test_full_script(self):
        world = make_world()
        executor = make_executor(world)
        agent = Agent(ONT, world, MockLLM(SCENARIO["script"]), executor, SCENARIO["goal"],
                      emit=lambda *a, **k: None)
        self.assertTrue(agent.run())

        # 终态：服务恢复、告警清零、故障单全部 resolved
        self.assertEqual(world.get("Service", "payment-db")["status"], "healthy")
        self.assertEqual(world.get("Service", "payment-api")["status"], "healthy")
        self.assertEqual(world.query("Alert"), [])
        for i in world.query("Incident"):
            self.assertEqual(i["status"], "resolved")

        # 剧本里安排了至少两次拦截（无单重启 + 未恢复关单）
        blocked = [a for a in agent.audit if a["outcome"].startswith("blocked")]
        self.assertGreaterEqual(len(blocked), 2)

        # 审计台账：回滚/重启都留下了 ActionRecord
        self.assertGreaterEqual(len(world.query("ActionRecord")), 3)

        # 回滚动作确实生效
        dep = world.get("Deployment", "DEP-1042")
        self.assertEqual(dep["status"], "rolled_back")


if __name__ == "__main__":
    unittest.main(verbosity=2)
