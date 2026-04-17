# Plan: #634 适配 Claude Opus 4.7 task budget 与 thinking 协议变更

## 目标

补齐 Anthropic message 协议在 Bella SDK 中对 Claude Opus 4.7 新字段的表达能力，使请求侧能够正确透传：
- `output_config.task_budget`
- `thinking.display`

同时保证现有 thinking / reasoning 映射逻辑不被破坏，并让后续适配链路能够显式区分“开启 thinking”与“是否展示 summarized thinking”。

## 非目标

- 不在这次计划中扩展 beta header 的统一注入策略或配置中心能力。
- 不修改非 Anthropic message 协议无关的其他 provider 适配逻辑。
- 不在这次计划中引入额外的协议抽象重构，只做针对 Issue 的最小必要改动。
- 不处理响应侧更大范围的 reasoning 内容渲染策略调整，除非为兼容 `thinking.display` 必须联动。

## 验收标准

1. `MessageRequest.OutputConfig` 支持序列化/反序列化 `task_budget` 字段。
2. `MessageRequest.ThinkingConfig` 支持序列化/反序列化 `display` 字段。
3. `TransferFromCompletionsUtils` 在从 completion 协议映射到 message 协议时，能够保留或推导新的 thinking / task budget 信息，不丢字段。
4. `TransferToCompletionsUtils` 在从 message 协议映射回 completion 协议时，不因新增字段导致现有 reasoning_effort 映射失效。
5. 至少补充一组针对 DTO 或协议转换的测试/序列化校验，覆盖：
   - `output_config.task_budget`
   - `thinking.display`
   - 现有 `budget_tokens` 逻辑不回归

## 约束

- 需保持 Java 8 兼容。
- 优先在现有 DTO 和转换工具中做增量修改，避免引入大范围结构调整。
- 现有 `thinking` 字段已经被 `TransferFromCompletionsUtils` 与 `TransferToCompletionsUtils` 使用，新增字段必须兼容现有 `reasoning_effort` 的 map / string 分支。
- 后端适配层当前通过 `AnthropicAdaptor` 直接透传 JSON 请求，新增字段主要影响 SDK DTO 与协议转换层，而不是 HTTP 发送框架本身。
- backend 测试环境受限，优先补充 sdk/server 内可独立运行的单测或对象映射测试。

## 变更范围

- `api/sdk/src/main/java/com/ke/bella/openapi/protocol/message/MessageRequest.java`
- `api/sdk/src/main/java/com/ke/bella/openapi/protocol/message/TransferFromCompletionsUtils.java`
- `api/sdk/src/main/java/com/ke/bella/openapi/protocol/message/TransferToCompletionsUtils.java`
- 可能涉及：
  - `api/sdk/src/test/java/...` 下新增或补充 message 协议转换测试
  - 如现有测试目录中已有对应转换测试，则直接扩展已有测试类

## 实现思路

### 1. 扩展 MessageRequest DTO 以对齐 Opus 4.7 协议
- **目标**：让 message 请求对象具备表达新字段的能力。
- **涉及文件**：`api/sdk/src/main/java/com/ke/bella/openapi/protocol/message/MessageRequest.java`
- **具体改动**：
  - 在 `OutputConfig` 中新增 `taskBudget` 字段，并通过 `@JsonProperty("task_budget")` 映射。
  - 新增 `TaskBudget` 内部类，至少包含 `type`、`total`。
  - 在 `ThinkingConfig` 中新增 `display` 字段，兼容 `omitted` / `summarized`。
  - 如有必要，补充便捷工厂方法或 builder 使用方式，但保持最小改动，不额外抽象。

### 2. 调整 completion → message 的协议转换
- **目标**：从现有 completion 请求映射到 Anthropic message 请求时，保留新字段语义。
- **涉及文件**：`api/sdk/src/main/java/com/ke/bella/openapi/protocol/message/TransferFromCompletionsUtils.java`
- **具体改动**：
  - 审查 `setThinkingConfig(...)` 对 `reasoning_effort` 为 map 的处理。
  - 在已有 `budget_tokens` 提取逻辑基础上，兼容读取 `display`。
  - 如果 `reasoning_effort` 或相关扩展字段里已经存在 task budget 信息，补充映射到 `output_config.task_budget`。
  - 保证 string 类型 `low/medium/high` 的历史逻辑不受影响。

### 3. 调整 message → completion 的协议转换
- **目标**：从 message 请求回转 completion 请求时，不丢失已有 reasoning 语义，并兼容新增字段。
- **涉及文件**：`api/sdk/src/main/java/com/ke/bella/openapi/protocol/message/TransferToCompletionsUtils.java`
- **具体改动**：
  - 审查 `setThinkingConfig(...)` 当前仅根据 `isEnabled()` 映射 reasoning 的逻辑。
  - 评估 `thinking.display` 是否需要传递到 completion 侧对象；若当前 completion DTO 已支持 map 结构，则改为构造包含 `budget_tokens` / `display` 的 map，而不只降级成 `"medium"`。
  - 如 `output_config.task_budget` 在 completion 协议侧已有承载字段，则补齐回写；若没有，则明确维持 message-only 字段，并保证不会误丢或报错。

### 4. 校验 Anthropic 请求发送链路是否需要额外联动
- **目标**：确认新增字段在发送链路中能够被自然透传，无隐藏拦截点。
- **涉及文件**：`api/server/src/main/java/com/ke/bella/openapi/protocol/message/AnthropicAdaptor.java`
- **具体改动**：
  - 确认请求仍是基于序列化后的 JSON 直接发送，不需要为 `task_budget` / `thinking.display` 增加特殊 header 之外的处理。
  - 若 beta header 需要由 `extraHeaders` 注入，则在 plan 中明确依赖调用方或配置方补充，不在本次 DTO 改动中硬编码。

### 5. 补充测试与回归验证
- **目标**：验证新增字段映射正确且旧逻辑不回归。
- **涉及文件**：
  - 优先：`api/sdk/src/test/java/...` 相关转换测试
  - 如无现成测试类，则新增针对 message/completion 转换的单测
- **具体改动**：
  - 增加 DTO 序列化/反序列化测试，验证 `task_budget` 与 `display` 字段。
  - 增加 `TransferFromCompletionsUtils` 测试，覆盖 map 型 reasoning 输入。
  - 增加 `TransferToCompletionsUtils` 测试，覆盖 thinking enabled + display + budgetTokens 的映射。
  - 回归验证当前 low/medium/high → budget_tokens 的历史行为仍然成立。

## 风险与依赖

- `CompletionRequest.reasoning_effort` 当前可能是弱类型字段，新增 map 结构映射时要避免影响已有 string 分支。
- `task_budget` 的来源字段在 completion 协议侧是否已有统一承载，需要先确认；若没有，需要限定本次只完成 message DTO 对齐。
- GitHub Issue 当前标签尚未成功补齐，需要用户手动在主仓库补打 `type::bug`、`flow::ready`、`priority::p2`、`plan::required`。
- 若仓库现有测试覆盖不足，可能需要新增较小粒度的转换测试类。
