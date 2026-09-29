# Onto —— Agent 开发的本体（Ontology）理论 · 最佳实践 · 项目实战

> 一句话定位：**本体是 Agent 时代的「存在契约」——它规定了一个系统里有哪些东西、它们如何关联、
> 哪些动作可以改变它们、以及按什么规则改变。LLM 提供语义理解，本体提供存在约束。**

本仓库是一套完整的学习路径 + 一个可运行的实战项目（OntoOps：本体驱动的运维排障 Agent）。

---

## 目录结构

```
onto/
├── README.md                  ← 你在这里（学习计划 + 导航）
├── docs/
│   ├── 01-theory.md           # 理论：从第一性原理推导「为什么 Agent 需要本体」
│   ├── 02-best-practices.md   # 最佳实践与反模式（10 条军规 + 6 个反模式）
│   ├── 03-project-guide.md    # OntoOps 项目实战指南（含练习题）
│   └── 04-architecture.md     # 对话窗口与部署架构：表现形态 / Tool(MCP) vs A2A / 架构图
└── project/
    ├── ontology/              # ★ 本体即代码（Ontology-as-Code）
    │   ├── core.yaml          #   领域本体：实体类型 + 约束（TBox）
    │   ├── capabilities.yaml  #   能力本体：动作 + 前置条件 + 效果 + 风险
    │   └── policies.yaml      #   策略本体：风险等级 → 审批要求
    ├── runtime/               # ★ 本体驱动的 Agent 运行时（~900 行，无框架）
    │   ├── ontology.py        #   本体加载 / 校验 / 投影（给 LLM 的上下文切片）
    │   ├── world.py           #   世界状态（ABox：实例层）
    │   ├── validator.py       #   SHACL-lite 约束验证器
    │   ├── actions.py         #   动作执行器：前置条件→策略→执行→效果→复验
    │   ├── llm.py             #   LLM 适配器（OpenAI 兼容接口 + Mock 剧本）
    │   ├── agent.py           #   Agent 循环：感知→规划→行动
    │   └── cli.py             #   命令行入口
    ├── scenarios/
    │   └── payment-incident.json   # 演示场景：支付服务故障排障
    └── tests/
        └── test_pipeline.py   # 端到端测试（无需 API key）
```

## 快速开始（60 秒）

```bash
cd project
python -m runtime.cli demo scenarios/payment-incident.json   # Mock 全流程演示
python -m runtime.cli inspect                                # 查看本体摘要
python -m runtime.cli chat                                   # 接真实 LLM 交互（需配环境变量）
python -m unittest discover -s tests -v                      # 跑测试
```

Mock 演示**不需要任何 API key**，确定性回放完整 Agent 循环，包括一次「LLM 想直接重启生产数据库
→ 被能力本体的前置条件拦截」的名场面。

接真实 LLM：设置 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`ONTO_MODEL` 三个环境变量
（任何 OpenAI 兼容接口均可：DeepSeek、智谱 GLM、Qwen 等）。

---

## 四周学习计划

每周约 6–8 小时。原则：**每周都有一个「动手产出」，不以「读完了」为完成标准。**

### 第 1 周：第一性原理与理论地图
| 步骤 | 内容 | 产出 / 验证 |
|---|---|---|
| 1.1 | 精读 `docs/01-theory.md` 第 1–2 节（六步推导链），合上文档自己复述一遍推导 | 能不看资料回答：「如果两个 Agent 对 Order 的定义不一致，会发生什么？」 |
| 1.2 | 读第 3 节简史：本体三次浪潮与两次冬天 | 写 5 行笔记：为什么这次「回归」不一样 |
| 1.3 | 读第 4–5 节：Agent 本体栈（L0–L4）与当代范式的映射 | 拿你手边任何一个 Agent 项目，标注它的每一层分别是什么、缺什么 |
| 1.4 | 读第 6 节：2025–2026 前沿 | 在团队内做一次 15 分钟分享 |

### 第 2 周：本体工程动手
| 步骤 | 内容 | 产出 / 验证 |
|---|---|---|
| 2.1 | 读 `project/ontology/core.yaml`，对照 01 文档的 TBox/ABox 概念 | 修改它：新增一种实体（如 `Team`），跑 `python -m runtime.cli inspect` 不报错 |
| 2.2 | 读 `capabilities.yaml`，理解前置条件/效果 DSL | 给 `scale_service` 加一条新前置条件并触发它 |
| 2.3 | 读 `docs/02-best-practices.md` 的 10 条军规 | 用「能力问题（Competency Questions）」方法为你自己的业务写 8 个问题 |
| 2.4 | 读反模式清单，审查你过去项目的 prompt/工具定义 | 找出至少 1 个你踩过的反模式 |

### 第 3 周：项目实战 OntoOps
| 步骤 | 内容 | 产出 / 验证 |
|---|---|---|
| 3.1 | 跑通 `demo`，对照 `docs/03-project-guide.md` 第 1–3 章逐行理解日志 | 能解释拦截发生在哪一层、依据本体哪条规则 |
| 3.2 | 完成指南第 4 章练习 A：新增 `get_logs` 动作（读类） | 测试通过 |
| 3.3 | 完成练习 B：新增 `Snapshot` 实体 + 快照约束 | 测试通过 |
| 3.4 | 完成练习 C：接真实 LLM 排障 | 观察真 LLM 是否也会被前置条件拦下，记录日志 |

### 第 4 周：进阶——多 Agent 与本体演化
| 步骤 | 内容 | 产出 / 验证 |
|---|---|---|
| 4.1 | 读 `docs/03-project-guide.md` 第 5 章（进阶方向）与 `docs/04-architecture.md`（对话窗口架构：Tool/MCP 一层起步 vs A2A 演进） | 能回答「何时该从 tool 升级到 A2A」的三个硬问题 |
| 4.2 | 选做：给 OntoOps 加第二个 Agent（如审批 Agent），共享同一本体 | 两个 Agent 对同一实体的理解来自同一文件 |
| 4.3 | 选做：给本体加版本号与迁移逻辑，演练一次 breaking change | 旧实例数据能迁移 |
| 4.4 | 通读 `runtime/` 全部源码（约 900 行） | 能白板画出一次动作调用的完整生命周期 |

---

## 延伸阅读（按优先级）

1. Gruber (1993), *A Translation Approach to Portable Ontology Specifications* —— 本体的经典定义
2. Sequeda et al. (2025), *Knowledge Graphs as a Source of Trust for LLM-powered Agents*
3. IETF draft-li-dmsc-macp —— 明确指出 A2A 缺语义层，这正是本体的位置
4. W3C OWL 2 Primer / SHACL 规范 —— 形式化表示的工业标准
5. OBO Foundry 的模块化原则 —— 「核心本体 + 领域扩展」的治理经验

详细文献与链接见 `docs/01-theory.md` 第 6 节。
