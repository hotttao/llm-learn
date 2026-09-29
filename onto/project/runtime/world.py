"""世界状态（ABox：实例层 / 断言盒）。

本体(core.yaml)定义「什么是 Service」；World 记录「现在有哪些 Service、什么状态」。
工程口诀：图谱(ABox)可以脏，本体(TBox)必须净——World 只做存储与查询，
合法性判断全部交给 validator / executor。
"""
from __future__ import annotations

import copy
import json
from typing import Dict, List, Optional

_ID_PREFIX = {
    "Incident": ("INC", 1000),
    "Deployment": ("DEP", 1000),
    "Alert": ("ALR", 2000),
    "ActionRecord": ("ACT", 3000),
}


def entity_key(entity: dict) -> str:
    """实体身份键：name 优先、id 兜底；关系型实体（如 Dependency）用 from→to 组合键。"""
    etype = entity.get("type", "?")
    if entity.get("name"):
        return f"{etype}:{entity['name']}"
    if entity.get("id"):
        return f"{etype}:{entity['id']}"
    if entity.get("from") and entity.get("to"):
        return f"{etype}:{entity['from']}->{entity['to']}"
    raise ValueError(f"实体缺少 name/id 标识: {entity}")


class World:
    def __init__(self):
        self.entities: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    @classmethod
    def from_entities(cls, entities: List[dict]) -> "World":
        w = cls()
        for e in entities:
            w.add(e)
        return w

    def add(self, entity: dict) -> str:
        key = entity_key(entity)
        if key in self.entities:
            raise ValueError(f"实体已存在: {key}")
        self.entities[key] = entity
        return key

    def remove_entity(self, entity: dict) -> None:
        self.entities.pop(entity_key(entity), None)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get(self, etype: str, ident: str) -> Optional[dict]:
        """按 name 优先、id 兜底解析实体引用。"""
        for e in self.entities.values():
            if e["type"] == etype and (e.get("name") == ident or e.get("id") == ident):
                return e
        return None

    def query(self, etype: str, where: Optional[dict] = None) -> List[dict]:
        """where 匹配：字段=值（eq）；「x_in」键 → 成员判断；值为 {contains: v} → 列表包含。"""
        out = []
        for e in self.entities.values():
            if e["type"] != etype:
                continue
            if where and not _match(e, where):
                continue
            out.append(e)
        return out

    def next_id(self, etype: str) -> str:
        prefix, base = _ID_PREFIX.get(etype, (etype.upper()[:3], 1))
        n = sum(1 for e in self.entities.values() if e["type"] == etype)
        return f"{prefix}-{base + n + 1}"

    # ------------------------------------------------------------------
    # 事务性：快照 / 回滚（军规 8 的执行基础）
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, dict]:
        return copy.deepcopy(self.entities)

    def restore(self, snap: Dict[str, dict]) -> None:
        self.entities = snap

    # ------------------------------------------------------------------
    # 投影与摘要
    # ------------------------------------------------------------------
    def project(self) -> str:
        """当前世界状态的紧凑文本投影（喂给 LLM 的观察）。"""
        if not self.entities:
            return "（世界为空）"
        lines = []
        for key in sorted(self.entities, key=lambda k: (k.split(":")[0], k)):
            lines.append(f"{key.split(':')[0]}: {json.dumps(self.entities[key], ensure_ascii=False)}")
        return "\n".join(lines)

    def stats(self) -> str:
        counts: Dict[str, int] = {}
        for e in self.entities.values():
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        parts = [f"{t}×{n}" for t, n in sorted(counts.items())]
        return "世界状态: " + ", ".join(parts) if parts else "世界状态: （空）"


def _match(entity: dict, where: dict) -> bool:
    for k, v in where.items():
        actual = entity.get(k[:-3] if k.endswith("_in") else k)
        if k.endswith("_in"):
            if actual not in v:
                return False
        elif isinstance(v, dict) and "contains" in v:
            if not isinstance(actual, list) or v["contains"] not in actual:
                return False
        elif actual != v:
            return False
    return True
