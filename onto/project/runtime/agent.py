"""Agent 循环：感知 → 规划 → 行动。

本体在这个循环里的两个出场：
  - 提示词完全由本体投影生成（describe_for_llm + world.project）——没有手写 prompt；
  - 被拦动作以结构化错误（stage + 规则说明）回喂给 LLM，让它有机会自我修正。
"""
from __future__ import annotations

from typing import Callable

from .actions import ActionError, Executor


class Agent:
    def __init__(self, ontology, world, llm, executor: Executor, goal: str,
                 max_steps: int = 32, emit: Callable = print):
        self.ont = ontology
        self.world = world
        self.llm = llm
        self.executor = executor
        self.goal = goal
        self.max_steps = max_steps
        self.emit = emit
        self.audit: list = []  # 审计轨迹：每步动作与结局

    # ------------------------------------------------------------------
    def _build_prompt(self, history: list) -> str:
        return "\n\n".join([
            "你是 OntoOps 值班排障 Agent。只能在「可用动作」清单中选择动作，"
            "严格输出一个 JSON 对象（不要输出其他文字）：\n"
            '调用动作: {"thought": "简短推理", "action": "动作名", "params": {...}}\n'
            '任务完成: {"action": "finish", "report": "处置报告"}\n'
            "注意前置条件与领域约束；被拦截的动作会收到结构化错误说明，请据此修正。",
            self.ont.describe_for_llm(),
            "## 当前世界状态\n" + self.world.project(),
            "## 任务目标\n" + self.goal,
            "## 已执行动作与结果\n" + ("\n".join(history[-12:]) or "（尚无）"),
        ])

    # ------------------------------------------------------------------
    def run(self) -> bool:
        self.emit(f"目标: {self.goal}")
        history: list = []
        for step in range(1, self.max_steps + 1):
            try:
                decision = self.llm.decide(self._build_prompt(history))
            except Exception as e:
                self.emit(f"✗ LLM 调用失败: {e}")
                return False

            thought = decision.get("thought", "")
            action = decision.get("action", "finish")
            params = decision.get("params") or {}
            self.emit(f"\n===== STEP {step} | {thought}")

            if action == "finish":
                self.emit(f"🏁 任务结束\n{decision.get('report', '')}")
                self.audit.append({"step": step, "action": "finish", "params": {}, "outcome": "ok"})
                return True

            self.emit(f"→ {action}({params})")
            try:
                result = self.executor.execute(action, params)
                obs = result.render()
                self.emit(f"✓ OK\n{obs}")
                history.append(f"{action}({params}) → 成功: {obs}")
                self.audit.append({"step": step, "action": action, "params": params, "outcome": "ok"})
            except ActionError as e:
                self.emit(f"✗ 被拦截 [{e.stage}] {e}")
                history.append(f"{action}({params}) → 被拦截[{e.stage}]: {e}")
                self.audit.append({"step": step, "action": action, "params": params,
                                   "outcome": f"blocked[{e.stage}]"})

        self.emit("⚠ 达到最大步数上限，任务未声明完成")
        return False
