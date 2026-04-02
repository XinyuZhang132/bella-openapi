# drift-detector

AI 厂商 API 漂移检测工具，用于感知各 AI 厂商 API 的变更（新增参数、废弃字段、响应结构变化等）。

面向 [bella-openapi](https://github.com/LianjiaTech/bella-openapi) 网关的适配器迭代维护辅助工具。

## 工作原理

```
       ┌─────────────────────────────────────────────────────┐
       │              双层 Snapshot 采集                      │
       │                                                     │
       │  Layer 1: 官方文档 spec               Layer 2: 实际响应  │
       │  (OpenAPI YAML/JSON)             (probe 请求 bella API)│
       │       ↓                                   ↓         │
       │  request_schema                   response_structure│
       │  response_schema                  (字段名 → 类型)    │
       └──────────────────┬──────────────────────────────────┘
                          │
                     Diff 引擎
                          │
              git diff 风格输出 + 飞书/Slack 通知
```

**Snapshot** 保存为 JSON 文件（`snapshots/<vendor>/<date>/`），可 git 追踪历史变化。

## 快速开始

### 1. 安装

```bash
cd drift-detector
pip install -e ".[dev]"
```

### 2. 配置

复制配置模板并编辑：

```bash
cp config/vendors.yaml config/vendors.local.yaml
```

最少需要配置 `BELLA_TEST_API_KEY` 和 `BELLA_API_BASE_URL`：

```bash
export BELLA_API_BASE_URL=http://localhost:8080
export BELLA_TEST_API_KEY=your-test-apikey
export OPENAI_PROBE_MODEL=gpt-4o-mini
```

### 3. 采集快照

```bash
# 采集所有启用厂商的 API 响应快照
drift-detector snapshot

# 只采集 OpenAI
drift-detector snapshot --vendor openai

# 采集文档 spec + API 响应
drift-detector snapshot --vendor openai --source both

# 采集特定接口
drift-detector snapshot --vendor openai --endpoint chat_completions
```

### 4. 对比变更

```bash
# 对比 openai/chat_completions 的最新两次快照
drift-detector diff --vendor openai --endpoint chat_completions

# 对比文档 spec 变化
drift-detector diff --vendor openai --endpoint chat_completions --source doc

# 对比指定快照文件
drift-detector diff \
  --vendor openai --endpoint chat_completions \
  --baseline snapshots/openai/2026-04-01/chat_completions_api_2026-04-01T00-00-00Z.json \
  --current  snapshots/openai/2026-04-02/chat_completions_api_2026-04-02T00-00-00Z.json
```

### 5. 一次性监控（适合 cron）

```bash
# 采集 + 对比 + 通知（有变更才发送）
drift-detector watch --notify-feishu "$FEISHU_WEBHOOK_URL"
```

### 6. 查看配置

```bash
drift-detector list-vendors
```

## 输出示例

```
╭─ openai / chat_completions  [api] ──────────────────────────────╮
│  +1 added  ~1 modified  ⚠ 1 BREAKING                            │
│  baseline: 2026-04-01T00:00:00Z  →  current: 2026-04-02T00:00:00Z│
│                                                                  │
│ ! response_structure.choices[0].message.refusal  [BREAKING]     │
│   - null                                                         │
│   + string                                                       │
│                                                                  │
│ + response_structure.choices[0].message.audio  [non-breaking]   │
│   + null                                                         │
╰──────────────────────────────────────────────────────────────────╯
```

## 定时调度（cron）

每天凌晨 2 点自动检测并推送飞书通知：

```bash
# crontab -e
0 2 * * * cd /path/to/bella-openapi/drift-detector && \
  BELLA_TEST_API_KEY=xxx FEISHU_WEBHOOK_URL=xxx \
  drift-detector watch --source both 2>&1 >> /var/log/drift-detector.log
```

或使用 GitHub Actions（见 `.github/workflows/drift-detect.yml`）。

## 项目结构

```
drift-detector/
├── pyproject.toml            # Python 项目配置
├── config/
│   ├── vendors.yaml          # 厂商配置（文档 URL、测试 API、认证）
│   └── probes.yaml           # 探针请求配置
├── snapshots/                # 快照存储（JSON，建议 git 追踪）
│   └── <vendor>/<date>/
├── src/
│   └── drift_detector/
│       ├── cli.py            # Click CLI 入口
│       ├── config.py         # 配置加载（支持环境变量替换）
│       ├── models.py         # 数据模型（Snapshot, DiffItem, DriftReport）
│       ├── snapshotter/      # 快照采集层
│       │   ├── api_snapshotter.py   # Layer 2：实际 API 响应
│       │   └── doc_snapshotter.py   # Layer 1：官方文档 spec
│       ├── differ/           # Diff 引擎
│       │   ├── engine.py     # DeepDiff 驱动的 diff 计算
│       │   └── formatter.py  # Rich 彩色终端输出 + Markdown 格式
│       ├── vendors/          # 厂商特定适配器
│       │   ├── openai.py
│       │   └── aws_bedrock.py
│       └── notifier/         # 通知模块
│           ├── feishu.py     # 飞书 Webhook
│           └── slack.py      # Slack Webhook
└── tests/
```

## 支持的厂商

| 厂商 | Layer 1（文档 diff） | Layer 2（响应 diff） | 说明 |
|------|:---:|:---:|------|
| OpenAI | ✅ | ✅ | 标准 OpenAPI YAML spec |
| Anthropic | 🔄 | ✅ | SDK API 参考文档 |
| AWS Bedrock | 🔄 | ✅ | botocore service model（需安装 boto3） |
| Google Vertex/Gemini | 🔄 | ✅ | Google Discovery API |
| 阿里云/通义千问 | ❌ | ✅ | 无标准 spec，仅响应 diff |
| 字节/火山引擎 | ❌ | ✅ | 无标准 spec，仅响应 diff |

✅ 已支持  🔄 计划中  ❌ 暂不支持

## 添加新厂商

1. 在 `config/vendors.yaml` 添加厂商配置
2. 如有特殊文档格式，在 `src/drift_detector/vendors/` 添加适配器
3. 在 `config/probes.yaml` 添加对应的探针请求

## 依赖

- `httpx` — HTTP 客户端
- `click` — CLI 框架
- `pyyaml` — YAML 解析
- `deepdiff` — 递归 dict diff
- `rich` — 彩色终端输出
