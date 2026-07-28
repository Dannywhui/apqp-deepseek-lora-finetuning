# 🚀 APQP DeepSeek LoRA Fine-Tuning

## 📌 Project Overview

本项目基于 **DeepSeek-LLM-7B-Chat** 大模型，通过 **LoRA (Low-Rank Adaptation)** 微调技术，构建面向 **APQP (Advanced Product Quality Planning)** 领域的智能质量管理助手系统。

系统采用前后端分离架构，整合了大模型微调、RAG 检索增强、动态 SQL 查询、规则引擎等多种能力，为企业 APQP 项目管理提供智能化支持。

---

## 🧠 Key Features

### 核心功能

* ✅ **大模型领域微调** - 基于 LoRA 的 APQP 领域知识适配
* ✅ **RAG 检索增强** - 本地 JSONL 向量库，支持企业知识文档检索
* ✅ **动态 SQL 查询** - 支持自然语言查询数据库（规则引擎 + 大模型双模式）
* ✅ **规则引擎** - 快速可靠的 SQL 生成与自然语言回复，毫秒级响应
* ✅ **结构化输出** - 专业的分析 + 风险 + 建议格式
* ✅ **Web 交互界面** - 基于 React + Vite 的现代化聊天界面
* ✅ **API 服务** - OpenAI 兼容的 `/chat/completions` 接口

### 支持的查询类型

* 📊 项目进度/状态查询
* ⚠️ 项目风险查询
* 🐛 项目问题查询
* 📋 项目交付物查询

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (React)                      │
│                    ChatInterface.tsx                         │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP API
┌──────────────────────────────▼──────────────────────────────┐
│                      Backend (FastAPI)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   RAG 模块   │  │  Agent 路由  │  │   动态 SQL 查询模块   │  │
│  │  (向量检索)   │  │  (工具调度)   │  │  (规则引擎+大模型)    │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                         main.py                              │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                    Data Layer                                │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │  MySQL 数据库 │  │  本地模型 (7B)    │  │  知识库文件   │   │
│  │  (APQP数据)   │  │  (4bit量化)       │  │  (JSONL向量) │   │
│  └──────────────┘  └──────────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure

```
.
├── back/                          # 后端代码
│   ├── main.py                    # FastAPI 主服务 (OpenAI 兼容 API)
│   ├── requirements.txt           # 后端依赖
│   ├── agent/                     # Agent 相关模块
│   │   ├── router.py              # 问题路由分发
│   │   └── context.py             # 上下文管理
│   ├── rag/                       # RAG 检索增强模块
│   │   ├── build_vector_store.py  # 向量库构建脚本
│   │   ├── vector_store.py        # 向量存储
│   │   ├── embeddings.py          # 嵌入向量
│   │   └── sources.py             # 数据源管理
│   ├── structured/                # 结构化数据查询模块
│   │   ├── agent_dynamic.py       # 动态 SQL 查询主入口
│   │   ├── dynamic_sql.py         # SQL 生成与执行
│   │   ├── sql_rules.py           # SQL 生成规则引擎
│   │   ├── reply_rules.py         # 自然语言回复规则引擎
│   │   ├── excel_ingest.py        # Excel 数据导入
│   │   ├── migrate_db.py          # 数据库迁移脚本
│   │   ├── tools.py               # LangChain 工具封装
│   │   └── .env                   # 环境配置
│   ├── uploads/                   # 上传文件目录
│   └── queue_handler.py           # 队列处理器
├── front/                         # 前端代码 (React + Vite)
│   ├── src/
│   │   ├── components/
│   │   │   └── ChatInterface.tsx  # 聊天界面组件
│   │   ├── App.tsx                # 主应用
│   │   └── main.tsx               # 入口文件
│   ├── package.json
│   └── vite.config.ts
├── data/                          # 训练数据
│   ├── apqp_data.json
│   └── apqp_high_quality.json
├── knowledge_base/                # 知识库向量存储
├── tests/                         # 测试文件
├── train.py                       # LoRA 微调训练脚本
├── merge_model.py                 # 模型合并脚本
└── README.md
```

---

## 🚀 Quick Start

### 环境要求

* Python 3.10+
* Node.js 18+
* MySQL 8.0+
* GPU (推荐 12GB+ 显存，RTX 3060 及以上)

### 1. 安装后端依赖

```bash
cd back
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `back/structured/.env` 文件并配置：

```env
# 数据库配置
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=apqp_db

# 模型配置
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
OPENAI_API_KEY=local-placeholder
MODEL_NAME=local-model
QUANTIZATION=4bit
LOCAL_MODEL_PATH=./output/merge_model

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

### 5. 启动后端服务

```bash
cd back
python main.py
```

服务将在 `http://127.0.0.1:8000` 启动。

### 6. 启动前端

```bash
cd front
npm install
npm run dev
```

前端将在 `http://localhost:5173` 启动。

---

## 💬 Dynamic SQL Query

### 规则引擎模式（推荐）

系统内置基于规则的 SQL 生成引擎，无需大模型即可快速响应查询：

```python
from agent_dynamic import run_dynamic_query

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
```

### 错误处理

系统对以下边界情况提供清晰的错误提示：

* ❌ **项目不存在** - "未查询到项目【PROJ999999】的风险数据..."
* ❌ **项目ID格式错误** - "项目ID格式应为PROJ开头+数字（如PROJ2026001）"
* ❌ **查询类型不支持** - "当前支持查询：风险、问题、进度、交付物"
* ❌ **无法识别需求** - "请提供项目ID和查询类型"

---

## 📚 RAG 知识库

### 构建向量库

1. 将文档放入 `knowledge_docs/` 目录（支持 `.txt`, `.md`, `.json`, `.pdf`）
2. 运行构建脚本：

```bash
python -m back.rag.build_vector_store --input-dir knowledge_docs --output knowledge_base/vector_store.jsonl
```

### JSONL 向量格式

```json
{
  "id": "doc_001_chunk_0001",
  "text": "knowledge chunk text",
  "embedding": [0.01, 0.02],
  "metadata": {
    "source": "apqp_rag_sample.md",
    "chunk_index": 1,
    "category": "APQP"
  }
}
```

> 默认使用本地哈希嵌入器，无需下载嵌入模型。可随时替换为更强的本地嵌入模型。

---

## 🤖 Model Fine-Tuning

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

### 训练数据格式

企业级结构化输出格式：

```text
【主题】
【问题分析】
【风险】
【改进建议】
```

---

## 🔌 API 接口

### Chat Completions (OpenAI 兼容)

```bash
POST /v1/chat/completions
Content-Type: application/json

{
  "model": "local-model",
  "messages": [
    {"role": "user", "content": "查询项目PROJ2026001的风险"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024
}
```

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

---

## 🧪 Testing

运行测试：

```bash
# 动态 SQL 链路测试
cd back/structured
python test_dynamic_flow.py

# 边界情况测试
python test_edge_cases.py

# 正常流程测试
python test_normal_flow.py
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

---

## 💡 Future Work

* 🔹 升级到 Qwen2.5-7B-Instruct
* 🔹 支持更多数据库表的动态查询
* 🔹 图表可视化展示
* 🔹 多轮对话上下文优化
* 🔹 用户权限管理
* 🔹 导出报表功能

---

## 🧑‍💻 Author

David Li

---

## ⭐ Acknowledgements

* DeepSeek LLM
* Hugging Face Transformers
* PEFT (LoRA)
* LangChain
* FastAPI
* React
* 开源 AI 社区

---

## 📜 License

MIT License
