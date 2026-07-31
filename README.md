# 🚀 APQP DeepSeek LoRA Fine-Tuning

## 📌 Project Overview

面向 **APQP** 场景的本地智能助手 Demo：基于 **DeepSeek-LLM-7B-Chat + LoRA** 微调，配合 RAG、自然语言查库、跨文档校验与文件对话，提供可本地复现的前后端分离示例。

> **开源说明**：本仓库已擦除企业内部敏感数据（真实业务库、对话历史、向量库、上传文档、凭证与内网地址等），公开内容仅为**技术复现 Demo**，不包含生产环境数据，也不能直接当作企业正式系统使用。

---

## 🧠 Key Features

* LoRA 领域微调 + 4bit 量化本地推理
* RAG 知识问答（SQLite 向量库 + bge-small-zh）
* 自然语言查询项目进度 / 风险 / 问题 / 交付物（规则引擎为主）
* 跨文档浅层校验（PFD ↔ FMEA ↔ 控制计划）
* 文件上传多轮对话、评分与摘要
* React 聊天界面 + OpenAI 兼容 API

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React + Vite)                   │
│                    ChatInterface.tsx                              │
│  ┌─────────────┐  ┌───────────────┐  ┌──────────────────────┐  │
│  │  对话模式    │  │  文件上传模式   │  │   跨文档校验模式      │  │
│  └─────────────┘  └───────────────┘  └──────────────────────┘  │
└──────────────────────────────┬───────────────────────────────────┘
                               │ HTTP API (Vite Proxy :5173 → :8000)
┌──────────────────────────────▼───────────────────────────────────┐
│                      Backend (FastAPI)                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐      │
│  │   RAG 模块   │  │  Agent 路由  │  │   动态 SQL 查询模块   │      │
│  │ (SQLite向量) │  │  (工具调度)   │  │  (规则引擎+大模型)    │      │
│  └─────────────┘  └─────────────┘  └─────────────────────┘      │
│  ┌───────────────────────┐  ┌──────────────────────────────┐     │
│  │  跨文档校验模块         │  │  文件解析/上传模块            │     │
│  │  (cross_document_validator.py) │  │  (uploads/ + 多格式解析)  │     │
│  └───────────────────────┘  └──────────────────────────────┘     │
│                         main.py (CORS + Session 并发锁)            │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                    Data Layer                                      │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │  MySQL 数据库 │  │  本地模型 (7B)    │  │  知识库向量存储    │   │
│  │  (APQP数据)   │  │  (4bit量化)       │  │  (SQLite + bge)  │   │
│  └──────────────┘  └──────────────────┘  └──────────────────┘   │
│  ┌──────────────────┐  ┌────────────────────────────────────┐    │
│  │  会话存储 (SQLite)│  │  本地嵌入模型 bge-small-zh-v1.5    │    │
│  └──────────────────┘  └────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure

```
.
├── back/                          # 后端代码
│   ├── main.py                    # FastAPI 主服务 (OpenAI 兼容 API)
│   ├── requirements.txt           # 后端依赖
│   ├── session_store.py           # 会话存储 (SQLite + 并发锁)
│   ├── queue_handler.py           # 异步任务队列处理器
│   ├── agent/                     # Agent 相关模块
│   │   ├── router.py              # 问题路由分发 (项目查询 vs 知识问答)
│   │   └── context.py             # 上下文与 Prompt 构建
│   ├── rag/                       # RAG 检索增强模块
│   │   ├── build_vector_store.py  # 向量库构建脚本 (支持 xlsx/pdf/docx)
│   │   ├── sqlite_vector_store.py # SQLite 向量存储 (documents + chunks)
│   │   ├── vector_store.py        # 向量存储接口
│   │   ├── embeddings.py          # 嵌入模型工厂 (语义/hashing 双后端)
│   │   ├── sync_knowledge_base.py # 知识库自动同步 (新增/修改/删除)
│   │   ├── prompting.py           # Prompt 模板
│   │   └── sources.py             # 数据源管理
│   ├── structured/                # 结构化数据查询模块
│   │   ├── cross_document_validator.py # 跨文档链路校验 (PFD/FMEA/CP)
│   │   ├── agent_dynamic.py       # 动态 SQL 查询主入口
│   │   ├── dynamic_sql.py         # SQL 生成与执行
│   │   ├── sql_rules.py           # SQL 生成规则引擎
│   │   ├── reply_rules.py         # 自然语言回复规则引擎
│   │   ├── excel_ingest.py        # Excel 数据导入
│   │   ├── migrate_db.py          # 数据库迁移脚本
│   │   ├── tools.py               # LangChain 工具封装
│   │   ├── queries.py             # 预定义查询
│   │   └── .env                   # 环境配置
│   └── uploads/                   # 上传文件临时目录
├── front/                         # 前端代码 (React + Vite + TailwindCSS)
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatInterface.tsx  # 主聊天界面 (对话/文件/校验三模式)
│   │   │   └── MarkdownRenderer.tsx # Markdown 渲染器
│   │   ├── hooks/
│   │   │   └── useTheme.ts        # 主题切换 Hook
│   │   ├── types/
│   │   │   └── index.ts           # TypeScript 类型定义
│   │   ├── utils/
│   │   │   └── index.ts           # 工具函数 (API 调用等)
│   │   ├── App.tsx                # 主应用
│   │   └── main.tsx               # 入口文件
│   ├── package.json
│   ├── vite.config.ts             # Vite 配置 (代理 :5173 → :8000)
│   └── tailwind.config.js
├── data/                          # 训练数据
│   ├── apqp_data.json
│   └── apqp_high_quality.json
├── knowledge_base/                # 知识库向量存储 (SQLite)
├── knowledge_docs/                # 知识库源文件 (txt/md/pdf/docx/xlsx)
├── models/
│   └── bge-small-zh-v1.5/        # 本地语义嵌入模型
├── chat_history/                  # 对话历史存储
│   └── sessions.db                # SQLite 会话数据库
├── tests/                         # 测试文件
├── train.py                       # LoRA 微调训练脚本
├── merge_model.py                 # 模型合并脚本
├── check_model.py                 # 模型加载检查脚本
└── README.md
```

---

## 🚀 Quick Start

### 环境要求

* Python 3.10+
* Node.js 18+
* MySQL 8.0+ (结构化项目数据)
* GPU (推荐 12GB+ 显存，RTX 3060 及以上)
  * 无 GPU 可使用 hashing 嵌入后端 + 规则引擎模式（仅结构化查询）

### 1. 安装后端依赖

```bash
cd back
pip install -r requirements.txt
```

> 网络受限环境：嵌入模型需使用本地路径，见「语义嵌入模型配置」一节。

### 2. 配置环境变量

复制仓库根目录的 `.env.example` 为 `back/structured/.env`，再填写本地配置（`.env` 已加入 `.gitignore`，请勿提交）：

```env
# 数据库配置
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=apqp

# 模型配置
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=local-placeholder
MODEL_NAME=local-model
QUANTIZATION=4bit
LOCAL_MODEL_PATH=./output/merge_model

# 嵌入模型 (默认 semantic，失败回退 hashing)
EMBEDDING_BACKEND=semantic
EMBEDDING_MODEL_PATH=../models/bge-small-zh-v1.5

# 推理模式: http (通过API) / direct (本地加载)
INFERENCE_MODE=http
```

### 3. 数据库初始化

```bash
cd back/structured
python migrate_db.py
```

### 4. 导入 Excel 数据

```bash
python excel_ingest.py
```

### 5. 构建知识库向量库

```bash
# 将文档放入 knowledge_docs/ 目录（支持 .txt, .md, .json, .pdf, .docx, .xlsx）
python -m back.rag.build_vector_store --backend semantic
# 若 PyMuPDF 不可用，加 --skip-pdf 跳过 PDF (PyPDF2 作为兜底)
```

### 6. 启动后端服务

```bash
cd back
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

服务将在 `http://127.0.0.1:8000` 启动。

### 7. 启动前端

```bash
cd front
npm install
npm run dev
```

前端将在 `http://localhost:5173` 启动。Vite 已配置代理，将 `/api`、`/chat`、`/kb` 请求转发到后端 8000 端口。

---

## 🔍 跨文档链路校验

### 功能说明

对 **PFD 过程流程图**、**FMEA**、**控制计划** 三份文档进行浅层显性文本匹配校验，人工触发并上传结构化文档。AI 仅检查 PFD 中存在的同名工序/特性是否在 FMEA 中存在对应失效条目并输出缺失提示。所有校验结果仅作人工参考。

### 使用方式

1. 前端进入「跨文档校验」模式
2. 上传 PFD 流程图文件（必填，支持 xlsx/pdf/docx）
3. 上传 FMEA 文件（必填）
4. 上传控制计划文件（可选）
5. 点击「开始校验」，结果包含：
   - 统计卡片（工序数、特性数、失效数、管控措施数）
   - 工序-失效匹配（已匹配/缺失）
   - 特性-失效匹配（已匹配/缺失）
   - FMEA 失效-控制计划匹配（已匹配/缺失）
   - 随机标红约 10 条高关注度缺失项

### API 接口

```bash
POST /api/v1/validate_documents
Content-Type: multipart/form-data

pfd_file:     PFD 流程图文件
fmea_file:    FMEA 文件
control_plan_file: 控制计划文件（可选）
```

---

## 📄 文件上传与对话

### 两种模式

前端支持两种文件操作模式：

| 模式 | 入口 | 行为 |
|------|------|------|
| **上传并对话** | 选择文件 + 输入问题 + 点击发送 | 初始化文件会话 (`/chat/start_file_session`)，之后进行多轮 Q&A |
| **评分+摘要** | 选择文件 + 点击「评分摘要」 | 一次性调用 `/api/v1/question_with_file`，返回 100/200 字摘要与评分 |

### 支持的文件格式

`.txt`, `.md`, `.json`, `.pdf`, `.docx`, `.xlsx`, `.pptx`, `.csv`

---

## 📚 RAG 知识库

### 语义嵌入模型

默认使用 **bge-small-zh-v1.5**（512 维语义向量），从本地路径 `models/bge-small-zh-v1.5/` 加载。

> 网络受限环境下（无法直连 HuggingFace），可通过 ModelScope 获取：
> ```bash
> git clone https://www.modelscope.cn/Xorbits/bge-small-zh-v1.5.git models/bge-small-zh-v1.5
> ```

若语义模型不可用，自动回退到 **HashingEmbeddingModel**（384 维，纯本地哈希，不依赖外部模型）。可通过环境变量强制指定：

```bash
EMBEDDING_BACKEND=hashing    # 强制使用哈希嵌入
EMBEDDING_BACKEND=semantic   # 优先语义，失败回退哈希（默认）
```

### SQLite 向量存储

使用两张表（外键级联）：

- **documents** - 文档元数据（source PK, path, category, chunk_count, created_at, file_mtime, file_size）
- **chunks** - 文档分块（id PK, source FK, chunk_index, text, embedding JSON, metadata JSON）

Embedding 以 JSON 文本存储，维度动态适配嵌入模型。

### 知识库同步

知识库支持自动同步（基于文件 mtime/size 变化）：

```bash
# API 方式
POST /kb/sync

# 命令行方式
python -m back.rag.sync_knowledge_base
```

同步逻辑：
- ✅ **新增**：`knowledge_docs/` 中有但向量库中没有的文件 → 加入
- ✅ **更新**：文件 mtime 或 size 变化 → 重新分块并更新
- ✅ **删除**：向量库中有但 `knowledge_docs/` 中没有的文件 → 移除

### 构建向量库

```bash
cd back
python -m back.rag.build_vector_store --backend semantic
# 可选参数: --input-dir ../knowledge_docs --skip-pdf
```

支持的文件后缀：`.txt`, `.md`, `.json`, `.pdf`, `.xlsx`

### 8D 文档精确匹配

当用户查询包含 `8D + 6~12 位数字` 格式（如 `8D202604007`）时：

1. 通过正则 `8D\d{6,12}` 提取 8D 编号
2. 在向量库中搜索匹配 source 文件名或内容的文档
3. 返回匹配文档的所有 chunks（score=1.0），绕开语义检索

### 知识库相关 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查（含 embedding_backend/embedding_model/embedding_dim） |
| GET | `/kb/documents` | 知识库文档列表 |
| GET | `/kb/documents/{source}` | 单文档查询 |
| POST | `/kb/documents` | 上传文档到知识库 |
| DELETE | `/kb/documents/{source}` | 删除知识库文档 |
| GET | `/kb/stats` | 知识库统计信息 |
| POST | `/kb/sync` | 触发知识库同步 |

---

## 💬 Dynamic SQL Query

### 规则引擎模式（推荐）

系统内置基于规则的 SQL 生成引擎，无需大模型即可快速响应查询：

```python
from back.structured.agent_dynamic import run_dynamic_query

result = run_dynamic_query("查询项目PROJ2026001的风险")
print(result['answer'])
```

**响应速度**：毫秒级
**适用场景**：结构化数据查询、报表生成

### 支持的查询示例

```
查询项目PROJ2026001的风险
查询项目PROJ2026001的进度
查询项目PROJ2026001的问题
查询项目PROJ2026001的交付物
查询风险
查询问题
APQP的几个阶段是什么？
FMEA和控制计划有什么关系？
```

> 不带项目编号的 APQP 流程/知识类问题走 RAG 知识库，不走 SQL 查询。

### Agent 路由分类

`back/agent/router.py` 中的 `classify_question()` 根据问题内容自动路由：

| 路由 | 触发条件 | 行为 |
|------|----------|------|
| `hybrid` | 项目ID + 知识关键词 + 进度关键词 | 工具调用 + RAG 检索 |
| `high_risks` | 项目ID + 风险关键词 | 调用 `apqp_high_risks` 工具 |
| `open_issues` | 项目ID + 问题关键词 | 调用 `apqp_open_issues` 工具 |
| `missing_deliverables` | 项目ID + 交付物关键词 | 调用 `apqp_missing_deliverables` 工具 |
| `project_status` | 项目ID + 进度关键词 | 调用 `apqp_project_status` 工具 |
| `rag` | 无项目ID 或 纯知识查询 | 仅 RAG 知识库检索 |

### 错误处理

系统对以下边界情况提供清晰的错误提示：

* ❌ **项目不存在** - "未查询到项目【PROJ999999】的风险数据..."
* ❌ **项目ID格式错误** - "项目ID格式应为PROJ开头+数字（如PROJ2026001）"
* ❌ **查询类型不支持** - "当前支持查询：风险、问题、进度、交付物"
* ❌ **无法识别需求** - "请提供项目ID和查询类型"

---

## 🤖 Model Fine-Tuning & Inference

### 推理量化（RTX 3060 12GB）

后端默认使用 **4bit 量化**加载合并后的本地模型，适配 RTX 3060 等 12GB 显卡：

```bash
# 环境变量（推荐）
QUANTIZATION=4bit   # 可选: 4bit / 8bit / none(fp16)
```

对应 `back/main.py` 加载逻辑：

```python
# QUANTIZATION=4bit（默认）
BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
)
device_map = "auto"
```

| 模式 | 适用场景 | 显存占用（约） |
|------|----------|----------------|
| `4bit` | RTX 3060 12GB（推荐） | ~5–7GB |
| `8bit` | 显存更充裕时 | 更高 |
| `none` / `fp16` | 大显存卡全精度 | 最高 |

无 CUDA 时会自动回退 CPU（不量化）。

### 训练配置

推荐 RTX 3060 (12GB) 配置：

```python
load_in_4bit = True
per_device_train_batch_size = 1
gradient_accumulation_steps = 8

lora_r = 8
lora_alpha = 16
lora_dropout = 0.05
```

### 训练流程

```bash
# 1. 训练 LoRA
python train.py

# 2. 合并模型
python merge_model.py
```

### 训练数据与统一回答格式

微调数据沿用企业级结构化输出；线上 Prompt 已按场景规范重写，与之对齐并强化内容质量：

**知识问答 / 文件分析：**

```text
【主题】
【结论】
【要点】
【风险】
【建议】
```

**项目结构化查询：**

```text
【结论】
【项目情况】
【关注点】
【建议】
```

**混合问答（项目事实 + 流程依据）：**

```text
【结论】
【项目事实】
【流程依据】
【建议】
```

内容质量要求：先结论后细节；引用编号/责任人/日期/指标；建议可执行；禁止空话套话；控制在约 400 字以内。

相关实现：

* `back/agent/context.py` — Agent 按路由生成格式化 Prompt
* `back/rag/prompting.py` — RAG Prompt
* `back/main.py` — 默认 system、评分/摘要、文件会话、查询改写
* `back/structured/reply_rules.py` — 规则引擎自然语言回复
* `back/structured/apqp_summary_pipeline.py` — 结项报告分层摘要

---

## 🔌 API 接口

### 完整 API 列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查（含 rag 配置信息） |
| GET | `/models` | 模型列表 |
| GET | `/queue/status` | 队列状态 |
| GET | `/chat/history/{session_id}` | 对话历史 |
| POST | `/chat/start_file_session` | 初始化文件会话 |
| POST | `/score` | 评分接口 |
| POST | `/chat/completions` | 聊天补全（OpenAI 兼容） |
| POST | `/chat/callback` | 异步回调 |
| POST | `/api/v1/question_with_file` | 文件评分+摘要（一次性） |
| POST | `/api/v1/validate_documents` | 跨文档链路校验 |
| GET | `/kb/documents` | 知识库文档列表 |
| GET | `/kb/documents/{source}` | 单文档查询 |
| POST | `/kb/documents` | 上传知识库文档 |
| DELETE | `/kb/documents/{source}` | 删除知识库文档 |
| GET | `/kb/stats` | 知识库统计 |
| POST | `/kb/sync` | 触发知识库同步 |

### Chat Completions (OpenAI 兼容)

```bash
POST /chat/completions
Content-Type: application/json

{
  "model": "local-model",
  "messages": [
    {"role": "user", "content": "查询项目PROJ2026001的风险"}
  ],
  "session_id": "your_session_id",
  "temperature": 0.7,
  "max_new_tokens": 1024
}
```

> `session_id` 用于隔离对话历史，防止跨会话污染。

### 跳过 RAG/Agent 增强

在 system 消息中添加 `SKIP_ENRICH` 可跳过 RAG 和 Agent 增强，直接调用模型：

```json
{
  "messages": [
    {"role": "system", "content": "SKIP_ENRICH"},
    {"role": "user", "content": "你的问题"}
  ]
}
```

### 文件会话

文件会话的 system_prompt 会自动包含 `SKIP_ENRICH`，确保模型仅基于上传的文件内容回答，不走知识库检索。

---

## 🔒 关键设计约束

* **会话隔离**：聊天历史按 `session_id` 隔离，防止交叉污染
* **并发安全**：会话存储使用 SQLite 写锁，确保并发访问不丢数据
* **SQL 安全**：SQL 查询使用表名和字段名白名单 + 参数化查询，防止注入
* **内部 SQL 生成**：使用独立 `session_id`（`_internal_sql_gen`），跳过对话历史保存
* **嵌入维度动态**：SQLite 向量存储的 embedding 维度随嵌入模型自适应
* **4bit 默认量化**：`QUANTIZATION=4bit`，适配 RTX 3060 12GB 本地推理
* **Prompt 结构顺序**：规则 → 输出格式/内容质量 → 【知识库资料/项目数据】 → 回答指令 → 【用户问题】
* **统一输出格式**：知识问答用【主题/结论/要点/风险/建议】；项目查询用【结论/项目情况/关注点/建议】

---

## 🧪 Testing

运行测试：

```bash
# Agent 路由测试
python -m pytest tests/test_agent_router.py

# Agent Prompt 测试
python -m pytest tests/test_agent_prompt.py

# Agent 上下文测试
python -m pytest tests/test_agent_context.py

# RAG 测试
python -m pytest tests/test_rag.py

# 语义 vs 哈希嵌入对比
python tests/test_semantic_vs_hash.py

# 结构化查询测试
python -m pytest tests/test_structured_queries.py
python -m pytest tests/test_structured_tools.py

# 8D 检索测试
python -m pytest tests/test_eightd_route.py
python -m pytest tests/test_multi_eightd.py

# 主流程集成测试
python -m pytest tests/test_main_agent_integration.py
```

---

## 📈 Results

### 微调效果

* ✔ 输出更结构化
* ✔ 领域理解更准确
* ✔ 专业话术更规范

### 规则引擎效果

* ⚡ 响应速度：毫秒级
* 🎯 准确率：100%（支持的查询类型）
* 💾 资源占用：无需 GPU
* 🔒 安全性：SQL 白名单校验，防止注入

### 语义嵌入效果 (bge-small-zh-v1.5 vs Hashing)

| 场景 | Hashing | bge-small-zh-v1.5 |
|------|---------|---------------------|
| 语义相关文本相似度 | ~0.0 | ~0.6+ |
| 语义无关文本相似度 | ~0.0 | ~0.4 |
| 是否需要下载模型 | 否 | 是（~100MB） |
| 运行速度 | 极快 | 快 |

---

## 💡 Future Work

* 🔹 升级到更强的基座模型 (Qwen2.5-7B / DeepSeek-V3)
* 🔹 支持更多数据库表的动态查询
* 🔹 图表可视化展示（项目进度 Gantt、风险矩阵等）
* 🔹 多轮对话上下文优化（滑动窗口 + 摘要）
* 🔹 用户权限管理（多租户隔离）
* 🔹 导出报表功能（PDF/Excel）
* 🔹 跨文档校验的同义不同名匹配（如"孔径尺寸"↔"内孔直径"）
* 🔹 向量库增量构建（不用每次全量重建）

---

## 🧑‍💻 Author

David Li
XiaoHan Lan
Hui Wang

---

## ⭐ Acknowledgements

* DeepSeek LLM
* Hugging Face Transformers
* PEFT (LoRA)
* LangChain
* FastAPI
* React
* bge-small-zh-v1.5 (北京智源研究院)
* 开源 AI 社区
