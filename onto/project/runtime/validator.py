"""SHACL-lite 约束验证器。

约 140 行实现 SHACL 的四要素思想：
  target（作用对象）→ scope + where
  condition（条件）  → where 过滤
  constraint（约束）→ require（数值/枚举/引用）与 require_refs（引用完整性）
  message（报错）    → message 模板 + 实体字段插值

能力本体里的动作效果应用后，executor 会调用 validate_world 做全量复验，
违反则回滚——这是「本体是状态机」的执行保障。
"""
from __future__ import annotations

from typing import List

from .world import World


class Validator:
    def __init__(self, ontology):
        self.ont = ontology

    def validate_world(self, world: World) -> List[str]:
        violations: List[str] = []
        for c in self.ont.constraints:
            violations.extend(self._check_constraint(c, world))
        return violations

    def _check_constraint(self, c: dict, world: World) -> List[str]:
        scope = c.get("scope")
        targets = world.query(scope, c.get("where") or None)
        out: List[str] = []
        for e in targets:
            out.extend(self._check_entity(c, e, world))
        return out

    def _check_entity(self, c: dict, e: dict, world: World) -> List[str]:
        cid = c.get("id", "?")
        errs: List[str] = []

        # 引用完整性：字段值必须指向已存在的某类型实体
        for field, rtype in (c.get("require_refs") or {}).items():
            ref = e.get(field)
            if ref is None or world.get(rtype, ref) is None:
                errs.append(self._fmt(c, e, f"字段 {field}={ref!r} 未引用到已存在的 {rtype}"))

        require = c.get("require") or {}
        for field, spec in require.items():
            if field == "refs_all":
                continue
            value = e.get(field)
            if value is None:
                errs.append(self._fmt(c, e, f"字段 {field} 缺失，约束要求非空"))
                continue
            if "min" in spec and (isinstance(value, bool) or not isinstance(value, int) or value < spec["min"]):
                errs.append(self._fmt(c, e, f"字段 {field}={value} 低于最小值 {spec['min']}"))
            if "min_items" in spec and (not isinstance(value, list) or len(value) < spec["min_items"]):
                errs.append(self._fmt(c, e, f"字段 {field} 至少需要 {spec['min_items']} 项"))
            if "eq" in spec and value != spec["eq"]:
                errs.append(self._fmt(c, e, f"字段 {field}={value!r}，要求 {spec['eq']!r}"))

        # 跨实体引用约束：refs_all —— 引用的实体必须全部满足 check
        ra = require.get("refs_all")
        if ra:
            for ref in e.get(ra["field"]) or []:
                target = world.get(ra["of"], ref)
                if target is None:
                    errs.append(self._fmt(c, e, f"{ra['field']} 引用的 {ra['of']} {ref!r} 不存在"))
                    continue
                for k, want in (ra.get("check") or {}).items():
                    if target.get(k) != want:
                        errs.append(
                            self._fmt(c, e, f"{ra['of']} {ref} 的 {k}={target.get(k)!r}，要求 {want!r}")
                        )
        return [f"[{cid}] {m}" for m in errs]

    @staticmethod
    def _fmt(c: dict, e: dict, detail: str) -> str:
        tpl = c.get("message") or "{type} {id}"
        try:
            head = tpl.format(**e)
        except Exception:
            head = tpl
        return f"{head}（{detail}）"
