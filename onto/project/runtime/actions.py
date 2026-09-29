"""动作执行器：一次动作调用的完整生命周期（本项目的核心）。

  ① dispatch        查能力本体，动作不存在 → 拦截
  ② param           参数 schema 校验 + entity_ref 存在性解析
  ③ precondition    前置条件求值（语义合法性）——不满足 → 拦截，错误回喂 LLM
  ④ policy          策略检查（治理许可）——需审批则走审批
  ⑤ handler         执行外部副作用/读观察（本项目中为模拟实现）
  ⑥ effects         应用声明式效果（先存世界快照）
  ⑦ re-validate     全量复验（实体 schema + 领域约束）——违反 → 回滚快照并报错
  ⑧ commit          提交，返回观察结果

前置条件/效果都是数据（capabilities.yaml），不是代码——同一份声明
既渲染进 LLM 提示词，又被这里求值执行：一份定义，四处执行。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .ontology import _render_inline
from .world import World


class ActionError(Exception):
    """动作被本体拦截。stage 标明拦截在哪一层，供结构化回喂 LLM。"""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class ActionResult:
    def __init__(self, action: str, observations: str, effects_log: List[str], approval: Optional[str] = None):
        self.action = action
        self.observations = observations
        self.effects_log = effects_log
        self.approval = approval

    def render(self) -> str:
        parts = []
        if self.observations:
            parts.append(self.observations)
        parts.extend(self.effects_log)
        if self.approval:
            parts.append(f"[governance] {self.approval}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# DSL 求值辅助：$param 引用替换
# ---------------------------------------------------------------------------
def _subst(obj, params: dict):
    if isinstance(obj, str) and obj.startswith("$"):
        name = obj[1:]
        if name not in params:
            raise ActionError("dsl", f"DSL 引用了不存在的参数 ${name}")
        return params[name]
    if isinstance(obj, dict):
        return {k: _subst(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_subst(v, params) for v in obj]
    return obj


class Executor:
    def __init__(self, ontology, world: World, validator, auto_approve: Optional[bool] = None,
                 approver: Optional[Callable] = None, emit: Callable = print):
        self.ont = ontology
        self.world = world
        self.validator = validator
        self.auto_approve = ontology.demo_auto_approve if auto_approve is None else auto_approve
        self.approver = approver  # chat 模式下由 CLI 注入 input() 审批
        self.emit = emit

    # ------------------------------------------------------------------
    def execute(self, action_name: str, params: dict) -> ActionResult:
        params = dict(params or {})

        # ① dispatch
        spec = self.ont.actions.get(action_name)
        if spec is None:
            raise ActionError("dispatch", f"未知动作 {action_name!r}，不在能力本体中")

        # ② 参数 schema + 实体引用解析
        resolved = self._validate_params(spec, params)

        # ③ 前置条件（语义合法性）
        for pre in spec.get("preconditions", []):
            ok, rendered = self._eval_precondition(pre, params, resolved)
            if not ok:
                raise ActionError("precondition", f"前置条件不满足: {rendered}")

        # ④ 策略（治理许可）
        rule = self._match_policy(spec, resolved)
        approval = self._request_approval(spec, rule, resolved) if rule else None

        # ⑤ handler：外部副作用/读观察
        handler = HANDLERS.get(action_name, _default_handler)
        observations = handler(self, params, resolved)

        # ⑥⑦⑧ 效果应用 + 复验 + 提交（失败回滚）
        snap = self.world.snapshot()
        try:
            effects_log = self._apply_effects(spec.get("effects", []), params, resolved)
            violations = self._full_validate()
            if violations:
                raise ActionError("constraint", "效果使世界违反约束（已回滚）: " + "; ".join(violations))
        except ActionError:
            self.world.restore(snap)
            raise
        except Exception as e:  # effects DSL 执行异常同样回滚
            self.world.restore(snap)
            raise ActionError("effect", f"效果应用失败（已回滚）: {e}") from e

        return ActionResult(action_name, observations, effects_log, approval)

    # ------------------------------------------------------------------
    def _validate_params(self, spec: dict, params: dict) -> Dict[str, dict]:
        resolved: Dict[str, dict] = {}
        pdefs = spec.get("params", {})
        for name in params:
            if name not in pdefs:
                raise ActionError("param", f"未知参数 {name!r}")
        for name, pdef in pdefs.items():
            value = params.get(name)
            if value is None:
                if pdef.get("required"):
                    raise ActionError("param", f"缺少必填参数 {name!r}")
                continue
            t = pdef.get("type", "string")
            if t == "entity_ref":
                if not isinstance(value, str):
                    raise ActionError("param", f"参数 {name} 应为实体引用字符串")
                entity = self.world.get(pdef["of"], value)
                if entity is None:
                    raise ActionError("param", f"参数 {name}={value!r} 未解析到已存在的 {pdef['of']}")
                resolved[name] = entity
                continue
            if t == "integer" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
                value = int(value)  # LLM 常把数字给成字符串，宽容转换
                params[name] = value
            errs = self.ont._check_value(name, value, pdef)
            if errs:
                raise ActionError("param", "; ".join(errs))
        return resolved

    def _eval_precondition(self, pre: dict, params: dict, resolved: dict):
        if "exists" in pre or "none" in pre:
            positive = "exists" in pre
            body = pre.get("exists") or pre.get("none")
            where = _subst(body.get("where", {}), params)
            found = self.world.query(body["of"], where)
            return (bool(found) if positive else not found), _render_inline(pre)
        if "field" in pre:
            f = pre["field"]
            entity = resolved[f["entity"][1:]]
            v = entity.get(f["field"])
            if "neq" in f:
                return v != _subst(f["neq"], params), _render_inline(pre)
            if "eq" in f:
                return v == _subst(f["eq"], params), _render_inline(pre)
            return v is not None, _render_inline(pre)
        raise ActionError("dsl", f"无法识别的前置条件: {pre!r}")

    def _match_policy(self, spec: dict, resolved: dict) -> Optional[dict]:
        risk = spec.get("risk", "none")
        tiers = {r.get("tier") for r in resolved.values() if isinstance(r, dict)}
        for rule in self.ont.rules:
            w = rule.get("when", {})
            if "risk_in" in w and risk not in w["risk_in"]:
                continue
            if "target_tier_in" in w and not (tiers & set(w["target_tier_in"])):
                continue
            return rule
        return None

    def _request_approval(self, spec: dict, rule: dict, resolved: dict) -> str:
        targets = ", ".join(
            (r.get("name") or r.get("id") or "?") for r in resolved.values() if isinstance(r, dict)
        )
        if self.auto_approve:
            self.emit(
                f"  [GOVERNANCE] 自动批准（演示模式）: {spec.get('risk')} 风险动作"
                f" {spec.get('name', '')} → {targets} | 规则 {rule.get('id')}"
            )
            return f"auto-approved(rule={rule.get('id')})"
        if self.approver is None:
            raise ActionError("policy", f"策略要求人工审批但未配置 approver: {rule.get('id')}")
        if not self.approver(spec, rule, resolved):
            raise ActionError("policy", f"人工审批被拒绝（规则 {rule.get('id')}）")
        return f"human-approved(rule={rule.get('id')})"

    def _apply_effects(self, effects: List[dict], params: dict, resolved: dict) -> List[str]:
        log: List[str] = []
        for eff in effects or []:
            if "set" in eff:
                s = eff["set"]
                entity = resolved[s["entity"][1:]]
                entity[s["field"]] = _subst(s.get("value"), params)
                log.append(f"[world] set {s['entity']}.{s['field']} = {entity[s['field']]!r}")
            elif "create" in eff:
                c = eff["create"]
                ent = {"type": c["of"]}
                for k, v in (c.get("with") or {}).items():
                    if isinstance(v, dict) and "auto_id" in v:
                        ent[k] = self.world.next_id(v["auto_id"])
                    else:
                        ent[k] = _subst(v, params)
                errs = self.ont.validate_entity(ent)
                if errs:
                    raise ActionError("effect", f"创建 {c['of']} 违反实体 schema: {'; '.join(errs)}")
                self.world.add(ent)
                log.append(f"[world] create {ent['type']} {ent.get('id')}")
            elif "retract" in eff:
                r = eff["retract"]
                where = _subst(r.get("where", {}), params)
                for e in self.world.query(r["of"], where):
                    self.world.remove_entity(e)
                    log.append(f"[world] retract {e['type']} {e.get('id')}")
            else:
                raise ActionError("dsl", f"无法识别的效果: {eff!r}")
        return log

    def _full_validate(self) -> List[str]:
        errs: List[str] = []
        for e in self.world.entities.values():
            errs.extend(self.ont.validate_entity(e))
        errs.extend(self.validator.validate_world(self.world))
        return errs


# ---------------------------------------------------------------------------
# Handlers：动作的外部副作用/读观察。约定：不许改世界状态——
# 世界状态变更只能通过声明式 effects（⑥），这是「声明与执行分离」的纪律。
# 换成真实系统时，把这里换成 API 调用即可，本体文件一行不动。
# ---------------------------------------------------------------------------
HANDLERS: Dict[str, Callable] = {}
_default_handler = lambda ex, params, resolved: ""


def _handler(name: str):
    def deco(fn):
        HANDLERS[name] = fn
        return fn
    return deco


@_handler("list_services")
def _h_list_services(ex: Executor, params, resolved):
    rows = sorted(ex.world.query("Service"), key=lambda s: s.get("name", ""))
    return "\n".join(
        f"- {s['name']} [{s['tier']}] status={s['status']} replicas={s.get('replicas')}" for s in rows
    ) or "无服务"


@_handler("get_service")
def _h_get_service(ex: Executor, params, resolved):
    s = resolved["service"]
    return (
        f"{s['name']} [{s['tier']}] status={s['status']} "
        f"replicas={s.get('replicas')} owner={s.get('owner_team')}"
    )


@_handler("get_dependencies")
def _h_get_deps(ex: Executor, params, resolved):
    name = resolved["service"]["name"]
    lines = []
    for d in sorted(ex.world.query("Dependency", {"to": name}), key=lambda x: x.get("from", "")):
        lines.append(f"- {d['from']} --{d['kind']}--> {d['to']}  （本服务被依赖）")
    for d in sorted(ex.world.query("Dependency", {"from": name}), key=lambda x: x.get("to", "")):
        lines.append(f"- {d['from']} --{d['kind']}--> {d['to']}  （本服务的依赖）")
    return "\n".join(lines) or "无依赖记录"


@_handler("get_recent_deployments")
def _h_get_deploys(ex: Executor, params, resolved):
    rows = sorted(
        ex.world.query("Deployment", {"service": resolved["service"]["name"]}),
        key=lambda d: d.get("id", ""),
    )
    return "\n".join(
        f"- {d['id']} v{d['version']} status={d['status']} note={d.get('note', '')}" for d in rows
    ) or "无部署记录"


@_handler("list_incidents")
def _h_list_incidents(ex: Executor, params, resolved):
    rows = sorted(ex.world.query("Incident"), key=lambda i: i.get("id", ""))
    return "\n".join(
        f"- {i['id']} [{i['status']}] {i['severity']} affects={i.get('affected_services')} :: {i.get('summary', '')}"
        for i in rows
    ) or "无故障单"


@_handler("create_incident")
def _h_create_incident(ex, params, resolved):
    return "故障单已创建（编号见下方世界变更）"


@_handler("resolve_incident")
def _h_resolve(ex, params, resolved):
    return "故障单已关闭"


@_handler("rollback_deployment")
def _h_rollback(ex, params, resolved):
    return "部署已回滚"


@_handler("restart_service")
def _h_restart(ex, params, resolved):
    return "重启指令已下发"


@_handler("scale_service")
def _h_scale(ex, params, resolved):
    return "副本数调整指令已下发"
