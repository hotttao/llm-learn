# 03 · 项目实战：OntoOps —— 本体驱动的运维排障 Agent

> 项目代码在 [../project](../project)，约 1000 行纯 Python（仅依赖 PyYAML），无任何 Agent 框架——
> 我们要学的是本体这一层，框架只会挡住视线。
> **它同时是教材和沙盒：每个练习都要求你改本体文件，而不是改代码。**

---

## 0. 为什么选运维排障这个场景

因为它是本体价值最密集的场景：

1. **领域本体自然**：服务、依赖、告警、故障单、部署——概念边界清晰；
2. **能力本体致命**：重启生产数据库这类动作，前置条件（先有故障单）和风险分级（要审批）
   不是锦上添花而是生死线；
3. **状态一致性可检验**：critical 服务 ≥2 副本、已解决故障的受影响服务必须健康——
   约束违反一眼可见；
4. **可以完全离线**：Mock LLM 按剧本走，没有 API key 也能跑完整循环。

## 1. 架构总览

```
                        ┌──────────────────────────────┐
                        │   ontology/ （本体 = 单一事实源）│
                        │   core.yaml      领域本体 L1   │
                        │   capabilities.yaml 能力本体 L2 │
                        │   policies.yaml  策略(治理)     │
                        └──────┬───────────────────────┘
                    被四处阅读 ↓（一份定义，四处执行）
      ┌────────────────────────┼────────────────────────┐
      │                        │                        │
  LLM 读（投影成提示词）   验证器执行（校验状态）     执行器执行（分派/应用效果）
      │                        │                        │
      └──────────── agent.py：感知 → 规划 → 行动 ────────┘
                                  │
                            world.py（ABox：世界状态账本）
```

一次动作调用的完整生命周期（这是本项目最重要的一张图）：

```
LLM 输出 {action, params}
  ① 参数 schema 校验（依据 core.yaml 的实体定义）
  ② 实体引用解析（名字 → 实体）
  ③ 前置条件求值（依据 capabilities.yaml）────── 不满足 → 拦截，结构化错误回给 LLM
  ④ 策略检查（依据 policies.yaml 的风险分级）── 需审批 → Mock 自动批 / chat 模式人工 y/n
  ⑤ 执行 handler（模拟外部副作用）
  ⑥ 应用声明式 effects（set/create/retract，先存快照）
  ⑦ 全量约束复验（依据 core.yaml 的 constraints）─ 违反 → 回滚快照 + 报错
  ⑧ 提交，观察结果回给 LLM，进入下一轮
```

## 2. 跑起来（5 分钟）

```bash
cd project
python -m runtime.cli demo scenarios/payment-incident.json
```

观察日志中的这几个关键帧（对照上面的生命周期图）：

- **STEP 1**：Agent 上来就想 `restart_service(payment-db)` →
  `✗ BLOCKED by precondition`：不存在覆盖该服务的 open 状态 Incident——这就是「③前置条件」在干活；
- 中段：查询服务 → 查依赖（发现 payment-api → payment-db）→ 查最近部署（发现嫌疑版本）
  → 回滚（风险 high → 审批 → 通过）→ **创建故障单** → 重启；
- 重启后：`effects` 自动把 payment-db 置为 healthy 并清除了相关 Alert——「⑥声明式效果」；
- 结尾：`resolve_incident` 触发「⑦约束复验」检查受影响服务全部健康后提交；
- 最后打印**事件账本**：每一步动作、依据的本体规则、被拦/通过——这就是审计轨迹（audit trail）。

再跑：

```bash
python -m runtime.cli inspect          # 打印本体摘要：实体、动作、约束、策略
python -m unittest discover -s tests -v
```

## 3. 逐文件精读指南（按此顺序）

| 顺序 | 文件 | 精读关注点 | 对应理论 |
|---|---|---|---|
| 1 | `ontology/core.yaml` | description 与 schema 的双写；constraints 的 scope/where/require 三段式 | 军规 1；SHACL 思想 |
| 2 | `ontology/capabilities.yaml` | 前置条件/效果的声明式 DSL；risk 分级 | 军规 2/5/7 |
| 3 | `ontology/policies.yaml` | 风险 → 审批的映射表；与前置条件的分层 | 军规 7 |
| 4 | `runtime/ontology.py` | `project_for_llm()`：本体如何变成提示词 | 军规 9（投影） |
| 5 | `runtime/validator.py` | ~140 行实现 SHACL-lite：target/scope/condition/message 四要素 | 军规 8 |
| 6 | `runtime/actions.py` | ①–⑧ 生命周期的代码化；快照回滚 | 军规 8 |
| 7 | `runtime/agent.py` | 感知→规划→行动循环；被拦后错误如何回喂 LLM | 01 文档第 1 节 |
| 8 | `runtime/llm.py` | MockLLM（确定性剧本）与 OpenAICompatibleLLM（urllib 实现） | — |

## 4. 练习（完成 = 本课程出师）

### 练习 A（30 min）：新增一个读类动作 `get_logs`

给 `capabilities.yaml` 加：

```yaml
get_logs:
  description: 查询某服务最近的重启/操作日志记录
  effect_class: read
  risk: none
  params:
    service: {type: entity_ref, of: Service, required: true}
  preconditions: []
  effects: []
```

再在 `runtime/actions.py` 的 `HANDLERS` 里加一个同名函数（从 world 里捞
`ActionRecord` 类型的实体，`where.service == service`），最后往演示剧本
`scenarios/payment-incident.json` 的 steps 里插一步。
**验收**：`python -m unittest discover -s tests` 全绿，demo 日志出现该步。

思考题：为什么读类动作的前置条件可以是空的，而 restart 不行？

### 练习 B（45 min）：新增实体 `Snapshot` + 联动约束

1. `core.yaml` 的 `entity_types` 加 `Snapshot`（properties: `id`, `service`(ref), `created_at`, `storage`(enum)）；
2. `constraints` 加一条：`storage == production 的 Snapshot，其 service 必须是 critical`；
   （提示：参考 `resolved-incident-services-healthy` 的写法——它就是「跨实体引用约束」的样例）；
3. 新增动作 `snapshot_service`（risk: medium，effects 里用 `create`）；
4. **验收**：写一个测试，先给 standard 服务建快照 → 断言动作被约束复验拦截并回滚。

这个练习让你亲手体验「TBox 的规则保护 ABox 的一致性」。

### 练习 C（20 min）：接真 LLM

```bash
export OPENAI_BASE_URL="https://api.deepseek.com/v1"   # 任何 OpenAI 兼容端点
export OPENAI_API_KEY="sk-..."
export ONTO_MODEL="deepseek-chat"
python -m runtime.cli chat scenarios/payment-incident.json
```

观察三件事：
1. 提示词完全由本体投影生成（`inspect` 可看）——你没有为这个模型写一行 prompt；
2. 真 LLM 常常也会先想直接重启——看它被拦截后**能否自我修正**（错误信息是结构化的，
   含缺失条件说明，这是「本体错误回喂」设计的目的）；
3. `risk: high` 动作会停下来等你按 y——治理层不信任任何模型。

### 练习 D（选做，60 min）：第二个 Agent

写一个 8 行的 `approval_agent.py`：读同一个 `capabilities.yaml`，收到审批请求时
根据动作 description + 当前世界投影自行判断并回复。两个 Agent 对「什么是
restart_service」的理解来自**同一份文件**——这就是 A2A 缺失而本体补位的那一层。

## 5. 进阶方向（第 4 周）

1. **本体演化**：给 `core.yaml` 的 `version` 加迁移逻辑——删掉 `Service.owner_team`
   字段，把旧场景文件迁移到新版本（体会军规 4 的成本）；
2. **多 Agent 分工**：排障 Agent + 审批 Agent + 复盘 Agent，共享 world 与本体，
   各自只被投影到自己的能力子集（L4 角色本体的雏形）；
3. **从 Mock 到真**：把 `HANDLERS` 换成真实 API 调用，本体文件一行不改——
   体会「声明与执行分离」带来的解耦；
4. **接入语义网生态**：把 core.yaml 翻译成 LinkML，用其工具链生成 JSON Schema 和
   文档站，感受标准表示层的收益。

## 6. 常见调试问题

| 症状 | 原因 |
|---|---|
| `BLOCKED by precondition` 但你预期该通过 | 前置条件 where 里的 `$param` 名与 params 不匹配；或实体过滤条件写反 |
| 动作通过但世界没变 | effects 的 `entity: "$service"` 引用的是**参数名**，检查 DSL 拼写 |
| 中文日志乱码 | Git Bash 下先 `export PYTHONIOENCODING=utf-8`（cli.py 已内置 reconfigure） |
| chat 模式 401 | 检查 `OPENAI_API_KEY`；部分端点要求 base_url 带 `/v1` |

---

**结业标准**：不看资料，能向同事讲清楚（1）六步推导链；（2）一次动作调用的 ①–⑧ 生命周期；
（3）为什么前置条件和策略必须分两层。做到这三点，你已经超过市面上大多数 Agent 开发者
对这一层的理解。
