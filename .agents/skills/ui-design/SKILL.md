---
name: ui-design
description: 维护项目 UI 平台的架构、交互契约、应用插槽、状态归属、响应式布局和扩展模型。适用于新增或修改页面、App、Slot、Shell、导航、Workspace 交互、跨页面状态，或需要审查 UI 实现与设计是否一致的场景。
---

# UI 设计

把 UI 设计作为可执行的工程约束维护，而不是只记录视觉稿。领域术语与业务不变量仍由 `domain-modeling` 和 `docs/ddd/<service>/` 负责；本技能只维护用户交互、前端平台结构和状态所有权。

## 文档位置

统一维护 `docs/ddd/ui_design/`：

- `README.md`：设计入口、范围和阅读顺序；
- `glossary.md`：Shell、Slot、App、App Instance 等 UI 术语；
- `architecture.md`：分层、依赖方向和运行时组合；
- `app-shell.md`：全局导航与 Workspace 切换；
- `slot-model.md`：App 注册、实例与 Slot 生命周期；
- `state-ownership.md`：服务端、URL、本地存储和内存状态归属；
- `responsive-layout.md`：桌面与移动端布局；
- `extension-model.md`：内置 App 与未来 plugin 的扩展边界；
- `*-flow.md`：重要用户旅程；
- `decisions/`：不可由上述规则直接推导的重要决策。

`docs/plan`、`docs/spec`、`docs/review` 继续留在 `docs/` 下，不迁入 UI 设计目录。

## 执行流程

1. 读取相关 `docs/ddd/<service>/CONTEXT.md` 和 Domain/Workflow，确认业务术语与规则。
2. 完整读取 `docs/ddd/ui_design/README.md` 指定的相关 UI 文档。
3. 对照当前代码、路由、API 契约、E2E 和参考实现，列出已确认事实与未决交互；不要从领域模型推断 UI 行为。
4. 若新增术语，先更新 `glossary.md`；若改变平台边界或状态归属，先写 ADR，再更新专题文档。
5. 更新用户旅程及其异常、空状态、加载状态、权限和响应式行为。
6. 再编写 `docs/spec` 与 `docs/plan`，然后实现。
7. 用单元测试验证状态机和纯规则，用组件场景验证视觉状态，用 E2E 验证关键用户旅程。

## 设计门禁

- 每个 UI 状态有唯一所有者，不复制服务端业务事实到持久化前端配置。
- Shell、Slot、App 和业务组件职责明确；App 不直接控制宿主布局。
- 新内置 App 与未来 plugin 使用同一 `AppDefinition` 契约。
- App 默认单实例时，模型仍使用稳定 `instanceId`，不得把单例假设写死进 Slot。
- Workspace 切换必须隔离 Workspace 级布局、活动 Session 和 App 状态。
- 桌面、窄屏、加载、空数据、失败和无权限状态均有明确行为。
- API Key 等秘密不写入 URL、localStorage、日志或可回显响应。
- 设计变更必须能映射到至少一个验证：单元测试、组件场景或 E2E。

## Command: review

当用户要求核对 UI 实现与设计时：

1. 按 `README.md` 阅读相关文档和 ADR；
2. 建立 `设计声明 -> 实现位置 -> 测试证据 -> 状态` 矩阵；
3. 状态使用 `aligned`、`partial`、`missing`、`implementation-only`；
4. 将结果写入 `docs/review/ui_design/<topic>.md`；
5. 有 `missing` 或未经确认的 `implementation-only` 时，不得宣称完全符合设计。

## 文档质量

记录稳定契约和决策，不记录像素流水账。复杂交互使用 Mermaid 状态图或时序图；表单必须写清字段、默认值、校验、秘密处理和更新语义。ADR 只追加或废止，不通过改写历史掩盖决策变化。
