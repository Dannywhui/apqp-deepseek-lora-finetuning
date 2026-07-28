"""
FastAPI 推理后端 - 基于 transformers 的本地大模型对话服务
支持 4-bit/8-bit 量化，OpenAI 格式的接口
"""

import torch
import torch._dynamo as dynamo
import os

# 直接创建 torch.compiler 模块
torch.compiler = dynamo
dynamo.config.suppress_errors = True
dynamo.config.disable = True
os.environ["TORCH_COMPILE_DISABLE"] = "1"

import torch.nn as nn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

import logging
import warnings
from datetime import datetime
import json
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from back.queue_handler import queue_manager, TaskStatus
from back.session_store import SessionStore
from pydantic import HttpUrl
from fastapi import FastAPI, HTTPException, BackgroundTasks
import random
import aiohttp
import re


from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, pipeline

try:
    from back.rag import (
        HashingEmbeddingModel,
        SemanticEmbeddingModel,
        get_embedding_model,
        JsonlVectorStore,
        SqliteVectorStore,
        build_rag_prompt,
    )
    from back.rag.sources import build_source_summaries
    from back.agent.context import build_agent_context, build_agent_prompt
    from back.structured.tools import get_structured_query_tools
except ImportError:
    from back.rag import (
        HashingEmbeddingModel,
        SemanticEmbeddingModel,
        get_embedding_model,
        JsonlVectorStore,
        SqliteVectorStore,
        build_rag_prompt,
    )
    from back.rag.sources import build_source_summaries
    from back.agent.context import build_agent_context, build_agent_prompt
    from back.structured.tools import get_structured_query_tools

import shutil
import base64
from fastapi import UploadFile, File, Form
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== 配置参数 ====================
# 获取脚本所在目录的绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VECTOR_STORE_PATH = os.getenv(
    "VECTOR_STORE_PATH",
    os.path.join(BASE_DIR, "..", "knowledge_base", "vector_store.sqlite"),
)
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "2")) # 减少检索资料数量
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.05"))
RAG_CONTEXT_MAX_CHARS = int(os.getenv("RAG_CONTEXT_MAX_CHARS", "1600"))
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "384"))
# 嵌入后端: "semantic" (bge-small-zh-v1.5, 512维) 或 "hashing" (兜底, 384维)
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "semantic").lower()
# 语义模型本地路径（无法直连 HuggingFace 时使用）
# 留空时 SemanticEmbeddingModel 会尝试从 HF 下载
DEFAULT_EMBEDDING_MODEL_PATH = os.path.join(BASE_DIR, "..", "models", "bge-small-zh-v1.5")
if not os.path.isdir(DEFAULT_EMBEDDING_MODEL_PATH):
    DEFAULT_EMBEDDING_MODEL_PATH = ""  # 回退到 HF 仓库名
if not os.getenv("EMBEDDING_MODEL_PATH") and DEFAULT_EMBEDDING_MODEL_PATH:
    os.environ["EMBEDDING_MODEL_PATH"] = DEFAULT_EMBEDDING_MODEL_PATH
GENERATION_MAX_NEW_TOKENS = int(os.getenv("GENERATION_MAX_NEW_TOKENS", "1024"))
# 文件上传配置
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {'.txt', '.md', '.csv', '.json', '.pdf', '.docx', '.xlsx', '.pptx'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_QUESTION_LEN = 1000
MODEL_PATH = os.path.join(BASE_DIR, "..", "output", "merge_model3")  # 合并后的完整模型路径
QUANTIZATION = None  # 量化方式: "4bit", "8bit", 或 None (根据你的模型配置)

# ==================== 全局变量 ====================
app = FastAPI(title="AI Chat API", version="1.0.0")
model = None
tokenizer = None
rag_store = SqliteVectorStore(VECTOR_STORE_PATH)
# 工厂函数：默认 semantic，失败回退 hashing（保留 HashingEmbeddingModel 作为兜底）
embedding_model = get_embedding_model(prefer=EMBEDDING_BACKEND, fallback_dimension=EMBEDDING_DIMENSION)
logger.info(
    "嵌入模型: %s (dim=%d, backend=%s)",
    type(embedding_model).__name__, embedding_model.dimension, EMBEDDING_BACKEND,
)

# ==================== CORS 配置 ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def generate_seq_id() -> str:
    """生成文档规定的seq_id：APQP+年月日时分秒+两位随机数字"""
    now = datetime.now().strftime("%y%m%d%H%M%S")
    rand_suffix = str(random.randint(0, 99)).zfill(2)
    return f"APQP{now}{rand_suffix}"



# ==================== 数据模型 ====================
class Message(BaseModel):
    """单条消息"""
    role: str = Field(..., description="角色: system, user, assistant")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    """聊天请求"""
    messages: List[Message] = Field(..., description="消息列表 (OpenAI 格式)")
    session_id: str = Field(default="default_session", description="会话ID，用于多轮对话记忆")  # 新增
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    max_new_tokens: int = Field(default=384, ge=1, le=4096, description="最大生成长度")
    top_p: float = Field(default=0.9, ge=0.0, le=1.0, description="Top-p 采样")
    stream: bool = Field(default=False, description="是否流式输出")
    model: Optional[str] = Field(default=None, description="模型名称 (可选)")

class QuestionParams(BaseModel):
    """评分请求参数"""
    needSummary100: bool = Field(default=True, description="是否需要生成100字内容摘要")
    needSummary200: bool = Field(default=True, description="是否需要生成200字内容摘要")
    needScore: bool = Field(default=True, description="是否需要打分")
    rules: Optional[str] = Field(default=None, description="评分具体规则描述")


CHAT_HISTORY_DIR = os.path.join(BASE_DIR, "..", "chat_history")  # 存在项目根目录

# 初始化会话存储（SQLite，支持并发）
SESSION_DB_PATH = os.path.join(BASE_DIR, "..", "chat_history", "sessions.db")
session_store = SessionStore(SESSION_DB_PATH)

def save_conversation(session_id: str, user_input: str, assistant_response: str, sources: List[Dict] = None):
    """保存一轮对话到 SQLite（并发安全）"""
    session_store.save_conversation(session_id, user_input, assistant_response, sources)
    
    # 可选：只保留最近 100 轮，防止数据无限膨胀
    session_store.truncate_history(session_id, max_rounds=100)

def load_conversation(session_id: str, max_rounds: int = 5) -> List[Dict]:
    """加载最近 N 轮对话历史"""
    return session_store.load_conversation(session_id, max_rounds)

def build_prompt_with_history(messages: List[Message], history: List[Dict]) -> List[Message]:
    """
    将历史对话和当前消息合并，构建完整的对话上下文
    """
    # 先加 system prompt（如果有）
    result = []
    seen_contents = set()

    for msg in messages:
        if msg.role == "system":
            result.append(msg)
            seen_contents.add((msg.role, msg.content))
    
    # 再加历史对话（按时间顺序）
    for h in history:
        user_msg = Message(role="user", content=h["user"])
        ass_msg = Message(role="assistant", content=h["assistant"])
        
        # ✅ 避免重复添加相同内容
        if (user_msg.role, user_msg.content) not in seen_contents:
            result.append(user_msg)
            seen_contents.add((user_msg.role, user_msg.content))
        if (ass_msg.role, ass_msg.content) not in seen_contents:
            result.append(ass_msg)
            seen_contents.add((ass_msg.role, ass_msg.content))

    
    # 最后加当前用户消息（如果有）
    for msg in messages:
        if msg.role == "user" and (msg.role, msg.content) not in seen_contents:
            result.append(msg)
            seen_contents.add((msg.role, msg.content))
        elif msg.role == "assistant" and (msg.role, msg.content) not in seen_contents:
            result.append(msg)
            seen_contents.add((msg.role, msg.content))
    
    return result



class ChatResponse(BaseModel):
    """聊天响应"""
    id: str = "chatcmpl-001"
    object: str = "chat.completion"
    created: int = 0
    model: str = "local-model"
    choices: List[Dict[str, Any]]
    usage: Dict[str, int]

def wrap_gpu_err(e: Exception):
    raw = str(e)
    if "Found no NVIDIA driver on your system" in raw or "No CUDA GPUs are available" in raw:
        return """【GPU驱动异常】
显卡有问题，我们正在修复中......"""
    return raw


# ==================== 模型加载 ====================
def load_model():
    """加载模型和分词器"""
    global model, tokenizer
    
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"模型路径不存在: {MODEL_PATH}")
    
    warnings.filterwarnings("ignore", message=".*UNEXPECTED.*")
    logging.getLogger("transformers.modeling_utils").setLevel(logging.ERROR)
    
    logger.info(f"正在加载模型: {MODEL_PATH}")
    
    # 加载分词器（保持不变）
    from transformers import PreTrainedTokenizerFast
    
    cfg_path = os.path.join(MODEL_PATH, "tokenizer_config.json")
    tok_path = os.path.join(MODEL_PATH, "tokenizer.json")
    
    bos = "<｜begin▁of▁sentence｜>"
    eos = "<｜end▁of▁sentence｜>"
    pad = "<｜end▁of▁sentence｜>"
    
    def _tok_content(v, default: str) -> str:
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get("content") or default
        return default
    
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        bos = _tok_content(cfg.get("bos_token"), bos)
        eos = _tok_content(cfg.get("eos_token"), eos)
        pad = _tok_content(cfg.get("pad_token"), pad)
    
    tokenizer = PreTrainedTokenizerFast(tokenizer_file=tok_path, bos_token=bos, eos_token=eos, pad_token=pad)
    
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    # ===== 修改：加载模型时忽略不匹配的权重 =====
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True,
        torch_dtype=torch.float16,
        device_map=None,
        low_cpu_mem_usage=True,
        ignore_mismatched_sizes=True,  # 忽略不匹配
    )
    
    if torch.cuda.is_available():
        model = model.cuda()
        logger.info("模型已加载到 GPU")
    else:
        logger.info("模型已加载到 CPU")
    
    # 设置 pad_token_id
    if model.config.pad_token_id is None:
        model.config.pad_token_id = tokenizer.eos_token_id
    
    if hasattr(model, 'generation_config'):
        model.generation_config.pad_token_id = tokenizer.eos_token_id
    
    logger.info("模型加载完成!")


def build_prompt(messages: List[Message]) -> str:
    """构建对话 prompt"""
    prompt = ""
    
    # ✅ 定义格式要求常量
    FORMAT_REQUIREMENT = "【格式要求】回答中如需强调关键词，请使用 **关键词** 包裹。"
    
    has_system = any(msg.role == "system" for msg in messages)
    
    if not has_system:
        # 没有 system 消息时，创建一个包含格式要求的 system 消息
        prompt += f"System: {FORMAT_REQUIREMENT}\n\n"
    
    for msg in messages:
        if msg.role == "system":
            # ✅ 在现有 system 消息中简洁地追加格式要求
            prompt += f"System: {msg.content}\n\n{FORMAT_REQUIREMENT}\n\n"
        elif msg.role == "user":
            prompt += f"User: {msg.content}\n\n"
        elif msg.role == "assistant":
            prompt += f"Assistant: {msg.content}\n\n"
    
    prompt += "Assistant: "
    return prompt


def load_rag_store():
    """Load the local SQLite vector store if it exists."""
    global rag_store
    rag_store = SqliteVectorStore(VECTOR_STORE_PATH).load()
    if rag_store.records:
        logger.info(f"RAG vector store loaded: {VECTOR_STORE_PATH} ({len(rag_store.records)} chunks)")
    else:
        logger.info(f"RAG vector store not found or empty: {VECTOR_STORE_PATH}")


def enrich_messages_with_rag(messages: List[Message]) -> tuple[List[Message], List[Dict[str, Any]]]:
    """Inject retrieved knowledge into the latest user message."""
    if not rag_store.records:
        return messages, []

    latest_user_index = None
    latest_question = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            latest_user_index = index
            latest_question = messages[index].content
            break

    if latest_user_index is None or not latest_question:
        return messages, []

    query_embedding = embedding_model.embed(latest_question)
    results = rag_store.search(query_embedding, top_k=RAG_TOP_K, min_score=RAG_MIN_SCORE)
    contexts = [
        {
            "text": result.record.text,
            "metadata": result.record.metadata,
            "score": result.score,
        }
        for result in results
    ]
    rag_content = build_rag_prompt(
        latest_question,
        contexts,
        max_context_chars=RAG_CONTEXT_MAX_CHARS,
    )
    enriched = list(messages)
    enriched[latest_user_index] = Message(role="user", content=rag_content)
    return enriched, build_source_summaries(contexts)

# ==================== Agent 上下文构建 =====================
def retrieve_rag_contexts(question: str) -> List[Dict[str, Any]]:
    if not rag_store.records:
        return []

    from back.agent.router import extract_eightd_id
    eightd_id = extract_eightd_id(question)
    if eightd_id:
        source = rag_store.find_source_by_text_keyword(eightd_id)
        if source:
            chunks = rag_store.get_source_chunks(source)
            return [
                {
                    "text": chunk.text,
                    "metadata": chunk.metadata,
                    "score": 1.0,
                }
                for chunk in chunks
            ]

    query_embedding = embedding_model.embed(question)
    results = rag_store.search(query_embedding, top_k=RAG_TOP_K, min_score=RAG_MIN_SCORE)
    return [
        {
            "text": result.record.text,
            "metadata": result.record.metadata,
            "score": result.score,
        }
        for result in results
    ]

_executor = ThreadPoolExecutor(max_workers=16)


# 新增：回调重试配置
CALLBACK_MAX_RETRY = 3
CALLBACK_RETRY_INTERVAL = 2  # 每次重试间隔2秒

def rewrite_query(history: List[Message], current_query: str) -> str:
    """根据对话历史重写用户当前问题，解决指代和省略"""
    # 如果只有 0-1 条历史，不需要重写
    if len(history) <= 1:
        return current_query
    
    # 只取最近几轮历史
    recent_history = history[-6:]
    
    # 拼接重写 prompt
    rewrite_prompt = f"""根据对话历史，将用户当前问题改写为独立完整的问句。

历史对话：
{format_history_for_rewrite(recent_history)}

用户当前问题：{current_query}

改写后的问题（直接输出，不要解释）："""
    
    try:
        # ✅ 使用线程池执行，避免阻塞事件循环
        future = _executor.submit(
            generate_response,
            rewrite_prompt,
            0.1,  # temperature
            128,  # max_new_tokens
            0.9   # top_p
        )
        rewritten = future.result(timeout=10)  # 10秒超时
        return rewritten.strip()
    except Exception as e:
        logger.warning(f"查询重写失败，使用原始问题: {e}")
        return current_query


def format_history_for_rewrite(history: List[Message]) -> str:
    """格式化历史对话为文本"""
    lines = []
    for msg in history:
        if msg.role == "user":
            lines.append(f"用户：{msg.content}")
        elif msg.role == "assistant":
            lines.append(f"客服：{msg.content}")
    return "\n".join(lines)

# ==================== Agent 消息增强 =====================
def enrich_messages_with_agent(messages: List[Message]) -> tuple[List[Message], List[Dict[str, Any]]]:
    latest_user_index = None
    latest_question = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            latest_user_index = index
            latest_question = messages[index].content
            break

    if latest_user_index is None or not latest_question:
        return messages, []
    
     # ==== 这里加查询重写逻辑 ====
    # 如果有多轮对话，先调用模型重写问题
    rewritten_question = rewrite_query(messages[:latest_user_index], latest_question)
    
    # 用重写后的问题去检索
    tools = {tool.name: tool for tool in get_structured_query_tools()}
    agent_context = build_agent_context(
        rewritten_question,
        tools=tools,
        rag_retriever=retrieve_rag_contexts,
    )


    agent_prompt = build_agent_prompt(
        latest_question,
        agent_context,
        max_context_chars=RAG_CONTEXT_MAX_CHARS,
    )
    enriched = list(messages)
    enriched[latest_user_index] = Message(role="user", content=agent_prompt)
    sources = _build_structured_source_summaries(agent_context.tool_result)
    sources.extend(build_source_summaries(agent_context.rag_contexts))
    return enriched, sources


def _build_structured_source_summaries(tool_result: Any) -> List[Dict[str, Any]]:
    sources: Dict[str, Dict[str, Any]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            source_file = value.get("source_file")
            source_sheet = value.get("source_sheet")
            if source_file:
                source = str(source_file)
                sheet = str(source_sheet) if source_sheet else ""
                key = f"{source}::{sheet}"
                label = f"{source}，{sheet}" if sheet else source
                sources.setdefault(
                    key,
                    {
                        "source": source,
                        "label": label,
                        "pages": [],
                        "chunks": [],
                        "score": 1.0,
                    },
                )

            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(tool_result)
    return list(sources.values())

def auto_highlight_key_terms(text: str) -> str:
    """自动为文本中的关键术语、数字、评分等添加红色加粗"""
    
    # ============ 第一步：评分维度和总分（优先级最高） ============
    
    dimension_keywords = [
        '数据支撑', '逻辑严密性', '竞品分析', '竞品/竞对分析', '实操建议',
        '内容完整性', '技术准确性', '逻辑清晰度', '格式规范性', '创新性',
        '可行性', '完整性', '准确性', '清晰度', '专业性', '实用性',
        '市场分析', '技术深度', '方案完整度', '成本分析', '风险评估'
    ]
    
    for keyword in dimension_keywords:
        text = re.sub(
            rf'({re.escape(keyword)})\s*[：:]\s*(\d+\.?\d*\s*分)',
            r'<span style="color:red;font-weight:bold;">\1</span>：<span style="color:red;font-weight:bold;">\2</span>',
            text
        )
    
    # 总分
    text = re.sub(
        r'(总分|总得分|综合得分|合计)\s*[：:]\s*(\d+\.?\d*\s*分)',
        r'<span style="color:red;font-weight:bold;">\1</span>：<span style="color:red;font-weight:bold;">\2</span>',
        text
    )
    
    # ============ 第二步：数字相关 ============
    
    # 百分比
    text = re.sub(
        r'(?<!["\'<])(\d+\.?\d*\s*%)(?!["\'>])',
        r'<span style="color:red;font-weight:bold;">\1</span>',
        text
    )
    
    # 金额
    text = re.sub(
        r'(?<!["\'<])(\d+\.?\d*\s*(?:亿|万)?\s*(?:美元|元|人民币))(?!["\'>])',
        r'<span style="color:red;font-weight:bold;">\1</span>',
        text
    )
    
    # 年份
    text = re.sub(
        r'(?<!["\'<])(\d{4}\s*年)(?!["\'>])',
        r'<span style="color:red;font-weight:bold;">\1</span>',
        text
    )
    
    # ============ 第三步：【】包裹的内容 ============
    
    text = re.sub(
        r'【(.+?)】',
        r'<span style="color:red;font-weight:bold;">【\1】</span>',
        text
    )
    
    # ============ 第四步：技术缩写（摘要中常见） ============
    
    # 大写字母缩写（如：AI、PLM、ERP、APQP、CAGR等）
    text = re.sub(
        r'(?<!["\'<])\b([A-Z]{2,6}(?:/[A-Z]{2,6})?)\b(?!["\'>])',
        r'<span style="color:red;font-weight:bold;">\1</span>',
        text
    )
    
    return text

def generate_response(prompt: str, temperature: float, max_new_tokens: int, top_p: float) -> str:
    """生成回复"""
    if model is None or tokenizer is None:
        raise RuntimeError("模型未加载")
    
    max_new_tokens = min(max_new_tokens, GENERATION_MAX_NEW_TOKENS)

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096)
    inputs.pop("token_type_ids", None)
    
    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    
    response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    response = response.strip()

    logger.info(f"模型原始输出: {repr(response[:200])}")  # 只打印前200字符
    
    # 在这里统一转换
    response = convert_bold_to_red(response)
    
    return response

async def generate_stream(prompt: str, temperature: float, max_new_tokens: int, top_p: float):
    """流式生成回复"""
    if model is None or tokenizer is None:
        raise RuntimeError("模型未加载")
    
    max_new_tokens = min(max_new_tokens, GENERATION_MAX_NEW_TOKENS)

    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096)
    inputs.pop("token_type_ids", None)
    
    # 移到模型所在的设备
    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}
    
    from transformers import TextIteratorStreamer
    from threading import Thread
    
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    
    generation_kwargs = {
        **inputs,
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "do_sample": True,
        "pad_token_id": tokenizer.eos_token_id,
        "eos_token_id": tokenizer.eos_token_id,
        "streamer": streamer
    }
    
    thread = Thread(target=model.generate, kwargs=generation_kwargs)
    thread.start()
    
    for text in streamer:
        yield f"data: {text}\n\n"
    
    yield "data: [DONE]\n\n"
    thread.join()

def extract_text_from_file(file_path: str) -> str:
    """根据文件扩展名提取文本内容"""
    ext = Path(file_path).suffix.lower()
    
    # 纯文本文件
    if ext in {'.txt', '.md', '.csv', '.json'}:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    # PDF文件
    elif ext == '.pdf':
        try:
            import PyPDF2
            text = ""
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
            return text
        except ImportError:
            return "[错误: 未安装 PyPDF2 库，无法解析 PDF 文件]"
    
    # Word文档
    elif ext == '.docx':
        try:
            from docx import Document
            doc = Document(file_path)
            return "\n".join([para.text for para in doc.paragraphs])
        except ImportError:
            return "[错误: 未安装 python-docx 库，无法解析 Word 文档]"
    
    # Excel文件
    elif ext in {'.xlsx', '.xls'}:
        try:
            import pandas as pd
            df = pd.read_excel(file_path)
            return df.to_string(index=False)
        except ImportError:
            return "[错误: 未安装 pandas/openpyxl 库，无法解析 Excel 文件]"
    
    # PowerPoint文件
    elif ext == '.pptx':
        try:
            from pptx import Presentation
            prs = Presentation(file_path)
            text = ""
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
            return text
        except ImportError:
            return "[错误: 未安装 python-pptx 库，无法解析 PowerPoint 文件]"
    
    else:
        return f"[不支持的文件类型: {ext}]"


@app.get("/")
async def root():
    """健康检查"""
    return {
        "status": "ok",
        "message": "AI Chat API 运行中",
        "model": MODEL_PATH,
        "quantization": QUANTIZATION,
        "rag": {
            "vector_store": VECTOR_STORE_PATH,
            "chunks": len(rag_store.records),
            "top_k": RAG_TOP_K,
            "min_score": RAG_MIN_SCORE,
            "embedding_backend": EMBEDDING_BACKEND,
            "embedding_model": type(embedding_model).__name__,
            "embedding_dim": embedding_model.dimension,
        }
    }


# ==================== 知识库文档管理 API ====================

@app.get("/kb/documents")
async def list_kb_documents():
    """列出知识库中的所有文档"""
    docs = rag_store.list_documents()
    return {
        "total": len(docs),
        "documents": [
            {
                "source": d.source,
                "path": d.path,
                "category": d.category,
                "chunk_count": d.chunk_count,
                "created_at": d.created_at,
            }
            for d in docs
        ],
    }


@app.get("/kb/documents/{source}")
async def get_kb_document(source: str):
    """查询单个文档元数据"""
    doc = rag_store.get_document(source)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档不存在: {source}")
    return {
        "source": doc.source,
        "path": doc.path,
        "category": doc.category,
        "chunk_count": doc.chunk_count,
        "created_at": doc.created_at,
        "file_mtime": doc.file_mtime,
        "file_size": doc.file_size,
    }


@app.get("/kb/documents/{source}/content")
async def get_kb_document_content(source: str):
    """获取文档的全文内容（从向量库分片拼接）"""
    doc = rag_store.get_document(source)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档不存在: {source}")

    chunks = rag_store.search(
        query_embedding=[0.0] * EMBEDDING_DIMENSION,
        top_k=doc.chunk_count,
        min_score=0.0,
        source_filter=source,
    )
    chunks.sort(key=lambda r: r.record.metadata.get("chunk_index", 0))
    content = "\n\n".join(r.record.text for r in chunks)

    return {
        "source": source,
        "content": content,
        "chunk_count": len(chunks),
        "content_length": len(content),
    }


@app.delete("/kb/documents/{source}")
async def delete_kb_document(source: str):
    """删除知识库中的指定文档（含全部分片）"""
    doc = rag_store.get_document(source)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档不存在: {source}")
    deleted = rag_store.delete_document(source)
    logger.info(f"KB document deleted: {source} ({deleted} chunks removed)")
    return {
        "source": source,
        "deleted_chunks": deleted,
        "remaining_documents": len(rag_store.list_documents()),
        "remaining_chunks": rag_store.count_chunks(),
    }


@app.post("/kb/documents")
async def add_kb_document(file: UploadFile = File(...)):
    """上传文档到知识库（自动分片、嵌入、入库）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    # 读取文件内容
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件过大，上限 {MAX_FILE_SIZE} 字节")

    # 落盘到临时目录（复用既有 _read_document 逻辑需要文件路径）
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    tmp_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(tmp_path, "wb") as f:
        f.write(content)

    # 提取文本
    from back.rag.build_vector_store import _read_document
    from pathlib import Path
    try:
        text = _read_document(Path(tmp_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件解析失败: {e}")

    # 入库
    added = rag_store.add_document(
        source=file.filename,
        text=text,
        embedding_fn=embedding_model.embed,
        path=tmp_path,
        category="APQP",
    )
    logger.info(f"KB document added: {file.filename} ({added} chunks)")
    return {
        "source": file.filename,
        "added_chunks": added,
        "total_documents": len(rag_store.list_documents()),
        "total_chunks": rag_store.count_chunks(),
    }


@app.get("/kb/stats")
async def kb_stats():
    """知识库统计信息"""
    docs = rag_store.list_documents()
    return {
        "total_documents": len(docs),
        "total_chunks": rag_store.count_chunks(),
        "documents": [
            {"source": d.source, "chunk_count": d.chunk_count, "created_at": d.created_at}
            for d in docs
        ],
    }


@app.post("/kb/sync")
async def sync_kb_docs(skip_pdf: bool = False):
    """同步 knowledge_docs/ 目录到向量库（仅新增未入库的文件）"""
    from back.rag.sync_knowledge_base import sync_knowledge_base

    try:
        stats = sync_knowledge_base(
            input_dir=os.path.join(BASE_DIR, "..", "knowledge_docs"),
            db_path=VECTOR_STORE_PATH,
            skip_pdf=skip_pdf,
        )
        logger.info(f"KB sync completed: {stats}")
        return {
            "success": True,
            **stats,
        }
    except Exception as e:
        logger.error(f"KB sync failed: {e}")
        raise HTTPException(status_code=500, detail=f"同步失败: {e}")


@app.get("/models")
async def list_models():
    """获取可用模型列表"""
    return {
        "object": "list",
        "data": [{
            "id": "local-model",
            "object": "model",
            "created": 1700000000,
            "owned_by": "local",
            "permission": [],
            "root": "local-model",
            "parent": None
        }]
    }


@app.post("/chat/completions", response_model=ChatResponse)
async def chat_completions(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    聊天补全接口 (OpenAI 兼容)
    
    请求示例:
    {
        "messages": [
            {"role": "user", "content": "你好"}
        ],
        "temperature": 0.7,
        "max_new_tokens": 512,
        "top_p": 0.9
    }
    """
    skip_enrich = any(
        msg.role == "system" and "SKIP_ENRICH" in msg.content
        for msg in request.messages
    )
    if model is None:
        raise HTTPException(status_code=500, detail="模型未加载，请检查服务状态")
    
    try:
        # ===== 新增：加载历史对话 =====
        session_id = request.session_id
        history = load_conversation(session_id, max_rounds=5)
        
        # ===== 新增：把历史拼接到当前消息里 =====
        enriched_messages_with_history = build_prompt_with_history(request.messages, history)
        
        if skip_enrich:
            enriched_messages = enriched_messages_with_history
            sources = []
        else:
            enriched_messages, sources = enrich_messages_with_agent(enriched_messages_with_history)
        prompt = build_prompt(enriched_messages)
        
        if request.stream:
            return StreamingResponse(
                generate_stream(prompt, request.temperature, request.max_new_tokens, request.top_p),
                media_type="text/event-stream"
            )
        
        # 提取用户当前提问
        user_question = ""
        for msg in reversed(request.messages):
            if msg.role == "user":
                user_question = msg.content
                break

        if request.stream:
            # 后台异步执行完整生成+保存对话，不阻塞流式输出
            async def save_stream_chat_record():
                # 内部调用（SKIP_ENRICH）不保存历史，避免污染用户会话
                if skip_enrich:
                    return
                loop = asyncio.get_event_loop()
                full_answer = await loop.run_in_executor(
                    None, generate_response, prompt, request.temperature, request.max_new_tokens, request.top_p
                )
                save_conversation(session_id, user_question, full_answer, sources)
            # 加入后台任务
            background_tasks.add_task(save_stream_chat_record)
            return StreamingResponse(
                generate_stream(prompt, request.temperature, request.max_new_tokens, request.top_p),
                media_type="text/event-stream"
            )
        
        response_text = generate_response(
            prompt,
            request.temperature,
            request.max_new_tokens,
            request.top_p
        )

        # 内部调用（SKIP_ENRICH）不保存历史，避免污染用户会话
        if not skip_enrich:
            save_conversation(session_id, user_question, response_text, sources)
        
        import time
        return ChatResponse(
            id=f"chatcmpl-{int(time.time())}",
            object="chat.completion",
            created=int(time.time()),
            model="local-model",
            choices=[{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text
                },
                "sources": sources,
                "finish_reason": "stop"
            }],
            usage={
                "prompt_tokens": len(tokenizer(prompt)["input_ids"]),
                "completion_tokens": len(tokenizer(response_text)["input_ids"]),
                "total_tokens": len(tokenizer(prompt)["input_ids"]) + len(tokenizer(response_text)["input_ids"])
            }
        )
        
    except Exception as e:
        logger.error(f"生成失败: {e}")
        err_msg = wrap_gpu_err(e)
        logger.error(f"生成失败: {err_msg}")
        raise HTTPException(status_code=500, detail=err_msg)

@app.post("/chat/start_file_session")
async def start_file_session(
    file: UploadFile = File(...),
    system_prompt: str = Form(default="你是数据分析助手，请基于用户上传的文件内容回答问题。"),
    session_id: str = Form(default=None)
):
    """
    上传文件并初始化一个可追问的对话会话。
    返回初始 messages 列表，调用方拿着它走 /chat/completions 即可多轮追问。
    
    参数:
    - file: 上传的文件
    - system_prompt: 自定义 system 角色设定（可选）
    """
    # 检查文件扩展名
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}。支持的类型: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # 检查文件大小
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)"
        )
    
    try:
        # 保存文件
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 提取文件内容
        file_content = extract_text_from_file(file_path)
        
        # 限制长度
        max_content_length = 4000
        if len(file_content) > max_content_length:
            file_content = file_content[:max_content_length] + "\n...(文件内容已截断)"
        
        # 构建初始 messages，文件内容塞进 system
        system_content = f"SKIP_ENRICH\n\n{system_prompt}\n\n用户上传了文件《{file.filename}》，内容如下：\n\n{file_content}"
        
        messages = [
            {"role": "system", "content": system_content}
        ]

        if not session_id:
            session_id = f"session_{int(time.time())}_{file.filename}"
        
        return {
            "code": 200,
            "messages": messages,
            "filename": file.filename,
            "session_id": session_id,
            "usage_note": "请将此 messages 作为初始上下文，后续对话通过 /chat/completions 接口传入完整 messages 列表即可追问"
        }
        
    except Exception as e:
        logger.error(f"文件处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/chat/history/{session_id}")
async def get_chat_history(
    session_id: str,
    max_rounds: int = 50  # 默认返回最近50轮
):
    """
    获取指定会话的对话历史
    
    返回格式：
    {
        "code": 200,
        "session_id": "test_multi_001",
        "total": 3,
        "history": [
            {
                "timestamp": "2026-01-15T10:30:01",
                "user": "你好，我叫小明",
                "assistant": "你好小明！...",
                "sources": [...]
            }
        ]
    }
    """
    try:
        history = load_conversation(session_id, max_rounds=max_rounds)
        return {
            "code": 200,
            "session_id": session_id,
            "total": len(history),
            "history": history
        }
    except Exception as e:
        logger.error(f"读取历史失败: {e}")
        return {
            "code": 500,
            "msg": str(e),
            "history": []
        }


@app.delete("/chat/history/{session_id}")
async def delete_chat_history(session_id: str):
    """
    删除指定会话的历史记录
    """
    file_path = os.path.join(CHAT_HISTORY_DIR, f"{session_id}.jsonl")
    
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"code": 200, "msg": f"会话 {session_id} 已删除"}
    else:
        return {"code": 404, "msg": f"会话 {session_id} 不存在"}
    

# ==================== 修改启动事件 ====================
@app.on_event("startup")
async def startup_event():
    """启动时加载模型和注入生成函数"""
    global model, tokenizer
    
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        load_rag_store()
        load_model()

        asyncio.create_task(queue_manager.process_queue())
        
        # ===== 注入生成函数到队列管理器 =====
        from functools import partial
        
        async def async_generate(task_data):
            """异步包装生成函数，支持多任务类型分派"""
            task_type = task_data.get("task_type", "scoring")

            # === APQP结项报告任务 ===
            if task_type == "apqp_report":
                file_path = task_data.get("file_path")
                debug = task_data.get("debug", True)
                max_sheets = task_data.get("max_sheets")

                if not file_path or not os.path.exists(file_path):
                    raise RuntimeError(f"文件不存在: {file_path}")

                from back.structured.apqp_summary_pipeline import generate_apqp_report

                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    generate_apqp_report,
                    file_path,
                    model,
                    tokenizer,
                    debug,
                    max_sheets,
                )

                # 组装对外返回的数据
                debug_info = {
                    "total_time_seconds": round(result.debug_info.total_time, 2),
                    "processed_sheets": len(result.sheet_summaries),
                    "skipped_sheets": result.debug_info.skipped_sheets,
                    "error_sheets": [
                        {"sheet": s, "error": e}
                        for s, e in result.debug_info.error_sheets
                    ],
                    "slowest_sheets": [
                        {"sheet": s, "time_seconds": round(t, 2)}
                        for s, t in result.debug_info.slowest_sheets
                    ],
                    "token_risks": result.debug_info.token_risks,
                    "truncation_warnings": result.debug_info.truncation_warnings,
                }

                return {
                    "answer": {
                        "final_report": result.final_report,
                        "phase_summaries": [
                            {
                                "phase_key": ps.phase_key,
                                "phase_name": ps.phase_name,
                                "summary": ps.phase_summary,
                                "sheets": [s.sheet_name for s in ps.sheet_summaries],
                            }
                            for ps in result.phase_summaries
                        ],
                        "debug_info": debug_info if debug else None,
                    },
                    "seq_id": task_data.get("seq_id", ""),
                    "task_type": "apqp_report",
                    "usage": {},
                }

            # === 默认：评分/摘要任务（原有逻辑） ===
            prompts = task_data["prompts"]
            seq_id = task_data.get("seq_id")

            results = {"summary100": "", "summary200": "", "score": ""}

            async def gen_one(key: str, prompt: str):
                if prompt:
                    loop = asyncio.get_event_loop()
                    try:
                        results[key] = await loop.run_in_executor(
                            None,
                            generate_response,
                            prompt,
                            0.3,
                            2048,
                            0.9
                        )
                    except Exception as e:
                        logger.error(f"[{seq_id}] 生成{key}失败: {e}")

            tasks = []
            for key in ["summary100", "summary200", "score"]:
                if key in prompts and prompts[key]:
                    tasks.append(gen_one(key, prompts[key]))

            await asyncio.gather(*tasks)

            return {
                "answer": results,
                "seq_id": seq_id,
                "task_type": "scoring",
                "usage": {}
            }
        queue_manager.set_generate_func(async_generate)
        logger.info("✅ 队列管理器已初始化")
        
    except Exception as e:
        logger.error(f"启动失败: {e}")
        err_msg = wrap_gpu_err(e)
        raise RuntimeError(err_msg)


# ==================== 获取队列状态 ====================
@app.get("/queue/status")
async def get_queue_status():
    """获取队列状态"""
    status = queue_manager.get_queue_status()
    return {
        "code": 200,
        **status
    }

def build_scoring_prompts(file_content: str, params: QuestionParams) -> Dict[str, Optional[str]]:
    """根据参数构建不同的prompt"""
    prompts = {
        "summary100": None,
        "summary200": None,
        "score": None
    }
    
    # ✅ 使用更简单、更明确的标记方式
    FORMAT_REQUIREMENT = """【格式要求 - 必须严格遵守】
1. 所有关键术语、数字、维度名称前后必须添加【】符号
2. 示例：文档分析了【AI】与【机器学习】的融合趋势，预计到【2032年】市场规模达【95亿美元】
3. 评分输出中，维度名和分数必须用【】包裹，如：【数据支撑】【25分】"""

    if params.needSummary100 or params.needSummary200:
        summary_system = f"System: 你是专业的文档摘要助手。输出时，关键术语和数字必须用【】包裹。\n\n{FORMAT_REQUIREMENT}\n\n"
        
        if params.needSummary100:
            prompts["summary100"] = f"""{summary_system}User: 请为以下文档生成100字以内的摘要，关键术语用【】包裹。

【文档内容】
{file_content}

Assistant:"""
        
        if params.needSummary200:
            prompts["summary200"] = f"""{summary_system}User: 请为以下文档生成200字以内的摘要，关键术语用【】包裹。

【文档内容】
{file_content}

Assistant:"""

    if params.needScore:
        score_system = f"System: 你是严谨客观的评审专家。评分输出中，维度名和分数必须用【】包裹。\n\n{FORMAT_REQUIREMENT}\n\n"
        
        rules = params.rules if params.rules else "请从内容完整性、逻辑清晰度、技术准确性等维度进行综合评分"
        
        prompts["score"] = f"""{score_system}User: 请根据以下要求对文档评分：
{rules}

【文档内容】
{file_content}

请严格按以下格式输出评分（维度名和分数必须用【】包裹）：
【维度名称】【X分】
理由：一句话说明

【总分】【XX分】

Assistant:"""
        
    return prompts

def convert_bold_to_red(text: str) -> str:
    """将各种标记转换为红色HTML"""
    if not text:
        return text
    
    # 转换 **加粗** 格式
    text = re.sub(r'\*\*(.+?)\*\*', r'<span style="color:red;font-weight:bold;">\1</span>', text)
    
    # 转换 【关键词】 格式（新增）
    text = re.sub(r'【(.+?)】', r'<span style="color:red;font-weight:bold;">【\1】</span>', text)
    
    # 如果没有找到任何标记，使用自动加粗
    if '<span style="color:red;font-weight:bold;">' not in text:
        text = auto_highlight_key_terms(text)
    
    return text

@app.post("/api/v1/question_with_file")
async def question_with_file(
    file: UploadFile = File(...),
    question: str = Form(...),
    callback_url: Optional[str] = Form(None)
):
    """
    APQP标准AI评分接口，multipart/form-data
    两种模式：
    1. 传callback_url：异步，返回seq_id
    2. 不传callback_url：同步阻塞，直接返回answer
    """

    # 统一异常返回模板
    def error_resp(msg: str):
        return {
            "code": -1,
            "message": msg,
            "data": None
        }
    
    logger.info(f"📥 收到请求: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    start_time = time.time()  # 用于计算总耗时

    # 1. 校验模型是否加载
    if model is None or tokenizer is None:
        return error_resp("评分服务报错：模型未加载")
    
    try:
        question_params = QuestionParams.parse_raw(question)
    except Exception as e:
        return error_resp(f"参数解析失败：{str(e)}")

    # 2. 校验question长度
    if len(question) > MAX_QUESTION_LEN:
        return error_resp(f"评分问题过长，最大支持{MAX_QUESTION_LEN}字符")

    # 3. 校验文件后缀
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        return error_resp(f"不支持的文件格式{file_ext}，允许：{ALLOWED_EXTENSIONS}")

    # 4. 校验文件大小
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > MAX_FILE_SIZE:
        return error_resp(f"评分服务报错：文件超过5MB限制")

    try:
        # 保存文件
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 提取文本
        file_content = extract_text_from_file(file_path)
        if len(file_content) > 4000:
            file_content = file_content[:4000] + "\n...(文件内容已截断)"

        # 构建评分Prompt
        # 根据参数构建不同的prompts
        prompts = build_scoring_prompts(file_content, question_params)

        logger.info(f"🔧 开始处理: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")

        # 构建异步生成所有结果
        async def generate_all_results():
            results = {"summary100": "", "summary200": "", "score": ""}
    
            async def gen_one(key: str, prompt: str):
                if prompt:
                    results[key] = await asyncio.to_thread(
                        generate_response,
                        prompt=prompt,
                        temperature=0.3,
                        max_new_tokens=2048,
                        top_p=0.9
                    )
    
            tasks = []
            for key in ["summary100", "summary200", "score"]:
                if prompts.get(key):
                    tasks.append(gen_one(key, prompts[key]))
    
            await asyncio.gather(*tasks)
            return results
        

        # 分支1：有callback_url → 异步队列处理，立即返回seq_id
        if callback_url and callback_url.strip():
            seq_id = generate_seq_id()
            task_data = {
                "seq_id": seq_id,
                "prompts": prompts,
                "callback_url": callback_url.strip(),
                "file_name": file.filename
            }
            # 提交队列
            try:
                task_id = queue_manager.add_task(task_data)

                logger.info(f"📤 异步提交: {datetime.now().strftime('%H:%M:%S.%f')[:-3]} | seq_id: {seq_id}")
                # 文档规定异步返回结构
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "seq_id": seq_id
                    }
                }
            except ValueError as e:
                # 队列满异常
                return error_resp(f"评分服务报错：任务超出队列长度，{str(e)}")

        # 分支2：无callback_url → 同步阻塞打分，直接返回answer
        all_results = await generate_all_results()

        logger.info(f"✅ 生成完成: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
        
        # ✅ 第5行：总耗时
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"⏱️  总耗时: {elapsed:.0f}ms")

        return {
            "code": 0,
            "message": "success",
            "data": {
            "answer": all_results
            }
        }

    except Exception as e:
        logger.error(f"❌ 失败: {datetime.now().strftime('%H:%M:%S.%f')[:-3]} | {str(e)}")
        return error_resp(f"评分服务报错：{str(e)}")
    

# ==================== 跨文档校验 API ====================
@app.post("/api/v1/validate_documents")
async def validate_documents(
    pfd_file: UploadFile = File(..., description="PFD流程图文件"),
    fmea_file: UploadFile = File(..., description="FMEA文件"),
    control_plan_file: UploadFile = File(None, description="控制计划文件（可选）")
):
    """
    流程图-FMEA-控制计划 三位一体跨文档链路校验接口
    
    参数:
    - pfd_file: PFD流程图文件（必填）
    - fmea_file: FMEA文件（必填）
    - control_plan_file: 控制计划文件（可选）
    
    返回:
    - code: 0成功，-1失败
    - message: 状态信息
    - data: 校验结果，包含summary和checks
    - report: 格式化的校验报告文本
    """
    def error_resp(msg: str):
        return {
            "code": -1,
            "message": msg,
            "data": None,
            "report": ""
        }
    
    try:
        from back.structured.cross_document_validator import CrossDocumentValidator
        
        validator = CrossDocumentValidator()
        
        files_to_save = []
        if pfd_file:
            pfd_path = os.path.join(UPLOAD_DIR, pfd_file.filename)
            with open(pfd_path, "wb") as f:
                f.write(await pfd_file.read())
                f.flush()
                os.fsync(f.fileno())
            files_to_save.append(pfd_path)
        
        if fmea_file:
            fmea_path = os.path.join(UPLOAD_DIR, fmea_file.filename)
            with open(fmea_path, "wb") as f:
                f.write(await fmea_file.read())
                f.flush()
                os.fsync(f.fileno())
            files_to_save.append(fmea_path)
        
        cp_path = None
        if control_plan_file:
            cp_path = os.path.join(UPLOAD_DIR, control_plan_file.filename)
            with open(cp_path, "wb") as f:
                f.write(await control_plan_file.read())
                f.flush()
                os.fsync(f.fileno())
            files_to_save.append(cp_path)
        
        pfd_data = validator.parse_document(pfd_path, "pfd")
        fmea_data = validator.parse_document(fmea_path, "fmea")
        cp_data = validator.parse_document(cp_path, "control_plan") if cp_path else None
        
        warnings = []
        if len(pfd_data["processes"]) == 0 and len(pfd_data["characteristics"]) == 0:
            warnings.append("PFD流程图文件未提取到工序或特性，请确认文件内容包含'工序'、'过程'、'步骤'、'特性'等关键词")
        if len(fmea_data["failure_modes"]) == 0 and len(fmea_data["processes"]) == 0:
            warnings.append("FMEA文件未提取到失效模式或工序，请确认文件内容包含'失效'、'故障'、'缺陷'等关键词")
        if cp_data and len(cp_data["controls"]) == 0 and len(cp_data["processes"]) == 0:
            warnings.append("控制计划文件未提取到管控措施或工序，请确认文件内容包含'控制'、'检查'、'检验'等关键词")
        
        result = validator.validate(pfd_data, fmea_data, cp_data)
        report = validator.format_report(result)
        
        # 清理临时文件（Windows下可能文件仍被占用，重试删除）
        import time as _time
        for file_path in files_to_save:
            for _ in range(3):
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    break
                except PermissionError:
                    _time.sleep(0.5)
        
        return {
            "code": 0,
            "message": "success",
            "data": result,
            "report": report,
            "warnings": warnings
        }
    
    except Exception as e:
        logger.error(f"跨文档校验失败: {e}")
        return error_resp(f"校验失败：{str(e)}")


# ==================== APQP结项报告生成 API（异步任务模式） ====================
@app.post("/api/v1/generate_apqp_report")
async def generate_apqp_report_api(
    file: UploadFile = File(..., description="APQP项目Excel文件（含70+Sheet）"),
    callback_url: Optional[str] = Form(None, description="回调URL（可选，完成后通知）"),
    debug: bool = Form(True, description="是否开启调试日志"),
    max_sheets: Optional[int] = Form(None, description="最多处理的Sheet数（调试用，None=全部）"),
):
    """
    APQP多Sheet Excel分层摘要 - 异步任务模式

    工作流程：
    1. POST 上传 Excel → 后端接收文件，返回 task_id（毫秒级响应，不会超时）
    2. 后端后台进程执行 APQP 分层摘要任务
    3. 循环调用 GET /api/v1/task/{task_id} 查看状态：running / finished / failed
    4. 任务完成后获取最终报告

    核心方案：三级分层递归摘要
    一级：遍历每个Sheet，单独生成单表摘要（自动跳过空白/纯模板Sheet）
    二级：按APQP五大阶段分组汇总，生成各阶段总结
    三级：汇总全部阶段总结，输出正式APQP项目结项报告
    """
    def error_resp(msg: str):
        return {
            "code": -1,
            "message": msg,
            "data": None
        }

    logger.info(f"📥 [结项报告] 收到请求: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")

    # 校验模型是否加载
    if model is None or tokenizer is None:
        return error_resp("报告生成服务报错：模型未加载")

    # 校验文件后缀
    file_ext = Path(file.filename).suffix.lower() if file.filename else ""
    if file_ext not in {'.xlsx', '.xls'}:
        return error_resp(f"不支持的文件格式{file_ext}，仅支持 .xlsx / .xls")

    # 校验文件大小
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > MAX_FILE_SIZE:
        return error_resp(f"文件过大，上限 {MAX_FILE_SIZE // 1024 // 1024}MB")

    try:
        # 保存文件
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"  [文件保存] {file_path} ({file_size} 字节)")
    except Exception as e:
        logger.error(f"  [文件保存失败] {e}")
        return error_resp(f"文件保存失败：{str(e)}")

    # 入队（毫秒级返回）
    seq_id = generate_seq_id()
    task_data = {
        "seq_id": seq_id,
        "task_type": "apqp_report",
        "file_path": file_path,
        "file_name": file.filename,
        "callback_url": callback_url.strip() if callback_url else None,
        "debug": debug,
        "max_sheets": max_sheets,
    }

    try:
        task_id = queue_manager.add_task(task_data)
        logger.info(f"  [入队成功] task_id={task_id}, seq_id={seq_id}")
        return {
            "code": 0,
            "message": "success",
            "data": {
                "task_id": task_id,
                "seq_id": seq_id,
                "status": "pending",
                "query_url": f"/api/v1/task/{task_id}",
            }
        }
    except ValueError as e:
        return error_resp(f"任务队列已满：{str(e)}")


@app.get("/api/v1/task/{task_id}")
async def get_task_status(task_id: str):
    """
    查询异步任务状态

    状态说明：
    - pending    : 任务已入队，等待处理
    - processing : 任务正在执行中（running）
    - completed  : 任务已完成（finished），可在 data.result 中获取报告
    - failed     : 任务失败，可在 data.error 中查看错误信息

    轮询建议：间隔 2-3 秒查询一次
    """
    task = queue_manager.get_task(task_id)

    if not task:
        return {
            "code": -1,
            "message": "任务不存在",
            "data": None
        }

    # 状态映射（对外更友好的状态名）
    status_map = {
        "pending": "pending",
        "processing": "running",
        "completed": "finished",
        "failed": "failed",
    }
    external_status = status_map.get(task["status"], task["status"])

    result_data = {
        "task_id": task_id,
        "status": external_status,
        "created_at": task["created_at"].isoformat() if task["created_at"] else None,
        "completed_at": task["completed_at"].isoformat() if task["completed_at"] else None,
    }

    # 任务完成时返回结果
    if task["status"] == "completed" and task.get("result"):
        result_data["result"] = task["result"].get("answer", {})
    # 任务失败时返回错误
    elif task["status"] == "failed":
        result_data["error"] = task.get("error", "未知错误")

    return {
        "code": 0,
        "message": "success",
        "data": result_data
    }


# ==================== 启动命令 ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
