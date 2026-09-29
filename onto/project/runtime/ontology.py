"""本体加载、校验与投影。

「一份定义，四处执行」里的定义端：本模块把 ontology/*.yaml 加载成对象，
向三个方向输出：
  - 验证器：entity schema（validate_entity）
  - 执行器：actions / policies（通过属性暴露）
  - LLM：describe_for_llm() —— 本体投影成提示词（军规 9）
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml


class OntologyError(Exception):
    """本体文件自身的错误（加载失败、结构非法）。"""


def _load_yaml(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise OntologyError(f"本体文件不存在: {path}")
    except yaml.YAMLError as e:
        raise OntologyError(f"YAML 解析失败: {path}\n{e}")
    if not isinstance(data, dict):
        raise OntologyError(f"本体文件顶层必须是映射: {path}")
    return data


def _render_inline(fragment) -> str:
    """把 DSL 片段渲染成单行 YAML，用于日志与提示词。"""
    return yaml.safe_dump(
        fragment, allow_unicode=True, default_flow_style=True, sort_keys=False
    ).strip()


class Ontology:
    """领域本体(core) + 能力本体(capabilities) + 策略本体(policies) 的统一入口。"""

    def __init__(self, core: dict, capabilities: dict, policies: dict):
        self.core = core
        self.capabilities = capabilities
        self.policies = policies

        self.name = core.get("ontology", "unknown")
        self.version = core.get("version", "0.0.0")
        self.entity_types: Dict[str, dict] = core.get("entity_types", {})
        self.constraints: List[dict] = core.get("constraints", [])
        self.actions: Dict[str, dict] = capabilities.get("actions", {})
        self.rules: List[dict] = policies.get("rules", [])
        self.demo_auto_approve: bool = policies.get("demo_auto_approve", False)

    @classmethod
    def load(cls, ontology_dir) -> "Ontology":
        d = Path(ontology_dir)
        return cls(
            _load_yaml(d / "core.yaml"),
            _load_yaml(d / "capabilities.yaml"),
            _load_yaml(d / "policies.yaml"),
        )

    # ------------------------------------------------------------------
    # 实体 schema 校验（给验证器/执行器）
    # ------------------------------------------------------------------
    def validate_entity(self, entity: dict) -> List[str]:
        etype = entity.get("type")
        spec = self.entity_types.get(etype)
        if spec is None:
            return [f"未知实体类型: {etype}"]
        errors: List[str] = []
        props = spec.get("properties", {})
        for name, pspec in props.items():
            value = entity.get(name)
            if value is None:
                if pspec.get("required"):
                    errors.append(f"{etype}.{name} 缺失（required）")
                continue
            errors.extend(self._check_value(f"{etype}.{name}", value, pspec))
        for key in entity:
            if key != "type" and key not in props:
                errors.append(f"{etype} 含本体未定义的属性: {key}")
        return errors

    @staticmethod
    def _check_value(path: str, value, pspec: dict) -> List[str]:
        t = pspec.get("type")
        if t == "string" and not isinstance(value, str):
            return [f"{path} 应为 string，实际 {type(value).__name__}"]
        if t == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                return [f"{path} 应为 integer"]
            if "min" in pspec and value < pspec["min"]:
                return [f"{path}={value} 低于最小值 {pspec['min']}"]
            if "max" in pspec and value > pspec["max"]:
                return [f"{path}={value} 超过最大值 {pspec['max']}"]
        if t == "enum" and value not in pspec.get("values", []):
            return [f"{path}={value!r} 必须是 {pspec.get('values')} 之一"]
        if t == "string_list" and (
            not isinstance(value, list)
            or not all(isinstance(x, str) for x in value)
        ):
            return [f"{path} 应为字符串列表"]
        return []

    # ------------------------------------------------------------------
    # 投影（给 LLM / 人）
    # ------------------------------------------------------------------
    def describe_for_llm(self) -> str:
        lines = [
            "# 领域本体（实体类型）",
        ]
        for name, spec in self.entity_types.items():
            lines.append(f"- {name} —— {spec.get('description', '')}")
            props = spec.get("properties", {})
            pdesc = ", ".join(
                f"{p}:{_render_inline({'type': s.get('type'), **({'of': s['of']} if s.get('of') else {})})}"
                for p, s in props.items()
            )
            lines.append(f"    属性: {pdesc}")
        lines.append("")
        lines.append("# 领域约束（世界状态任何时刻必须满足）")
        for c in self.constraints:
            lines.append(f"- [{c['id']}] {c.get('message', '')}")
        lines.append("")
        lines.append("# 可用动作（能力本体）")
        for name, spec in self.actions.items():
            lines.append(
                f"- {name}(risk={spec.get('risk')}, {spec.get('effect_class')}) —— {spec.get('description', '')}"
            )
            params = spec.get("params", {})
            if params:
                pdesc = ", ".join(
                    f"{p}:{s.get('type')}" + (f"(of {s['of']})" if s.get("type") == "entity_ref" else "")
                    for p, s in params.items()
                )
                lines.append(f"    参数: {pdesc}")
            for pre in spec.get("preconditions", []):
                lines.append(f"    前置条件: {_render_inline(pre)}")
            for eff in spec.get("effects", []):
                lines.append(f"    效果: {_render_inline(eff)}")
        return "\n".join(lines)

    def summary(self) -> str:
        return (
            f"本体 {self.name} v{self.version} | "
            f"实体类型 {len(self.entity_types)} | 动作 {len(self.actions)} | "
            f"约束 {len(self.constraints)} | 策略规则 {len(self.rules)}"
        )
