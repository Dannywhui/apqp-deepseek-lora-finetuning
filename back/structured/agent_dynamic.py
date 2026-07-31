import os
import json
import re
from dotenv import load_dotenv
from typing import Any, Dict, List

try:
    from .dynamic_sql import generate_and_execute_sql
    from .excel_ingest import connect_mysql_from_env
    from .reply_rules import generate_natural_reply
except ImportError:
    from dynamic_sql import generate_and_execute_sql
    from excel_ingest import connect_mysql_from_env
    from reply_rules import generate_natural_reply

load_dotenv()

# ===== 两种推理模式 =====
# MODE=http: 通过 main.py 的 OpenAI 兼容接口调用（会被 RAG/Agent 增强，不推荐用于 SQL 生成）
# MODE=direct: 直接加载 transformers 模型本地推理（干净 prompt，推荐）
INFERENCE_MODE = os.getenv("INFERENCE_MODE", "http")

def _clean_html_tags(text: str) -> str:
    """移除模型输出中的 HTML 标签"""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _load_local_model():
    """延迟加载本地 transformers 模型"""
    global _model, _tokenizer
    if _model is not None:
        return
    
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    
    model_path = os.getenv("LOCAL_MODEL_PATH", "")
    if not model_path:
        # 尝试默认路径
        model_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "output", "merge_model3"
        )
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"本地模型路径不存在: {model_path}\n"
            "请在 .env 中设置 LOCAL_MODEL_PATH 或确保模型目录存在"
        )
    
    print(f"正在加载本地模型: {model_path} ...")
    
    use_4bit = os.getenv("QUANTIZATION", "4bit") == "4bit"
    
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    kwargs = {
        "pretrained_model_name_or_path": model_path,
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
    }
    
    if use_4bit and torch.cuda.is_available():
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
    else:
        kwargs["torch_dtype"] = torch.float16
    
    model = AutoModelForCausalLM.from_pretrained(**kwargs)
    
    if not use_4bit and torch.cuda.is_available():
        model = model.cuda()
    
    model.eval()
    
    _model = model
    _tokenizer = tokenizer
    print("本地模型加载完成！")


def generate_response(prompt: str, temperature: float, max_new_tokens: int, top_p: float) -> str:
    if INFERENCE_MODE == "direct":
        return _clean_html_tags(_generate_direct(prompt, temperature, max_new_tokens, top_p))
    else:
        return _clean_html_tags(_generate_http(prompt, temperature, max_new_tokens, top_p))


def _generate_direct(prompt: str, temperature: float, max_new_tokens: int, top_p: float) -> str:
    """直接用 transformers 本地推理，prompt 不被污染"""
    import torch
    
    _load_local_model()
    
    inputs = _tokenizer(prompt, return_tensors="pt")
    if torch.cuda.is_available():
        inputs = {k: v.cuda() for k, v in inputs.items()}
    
    with torch.no_grad():
        outputs = _model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature if temperature > 0 else 0.01,
            top_p=top_p,
            do_sample=temperature > 0,
            pad_token_id=_tokenizer.eos_token_id,
        )
    
    # 只取生成部分（去掉输入 prompt）
    input_len = inputs["input_ids"].shape[1]
    generated_ids = outputs[0][input_len:]
    return _tokenizer.decode(generated_ids, skip_special_tokens=True).strip()


def _generate_http(prompt: str, temperature: float, max_new_tokens: int, top_p: float) -> str:
    """通过 main.py 的 OpenAI 兼容接口调用"""
    from openai import OpenAI
    
    base_url = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1")
    # 确保不以 /v1 结尾，因为 openai SDK 会自动加
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY", "local-placeholder"),
        base_url=base_url,
    )
    
    # 加 system 消息标记 SKIP_ENRICH，让 main.py 跳过 RAG/Agent 增强；
    # 同时用独立 session_id，双保险避免内部 SQL 生成调用污染用户会话历史
    response = client.chat.completions.create(
        model=os.getenv("MODEL_NAME", "local-model"),
        messages=[
            {"role": "system", "content": "SKIP_ENRICH"},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_new_tokens,
        top_p=top_p,
        timeout=180,
        extra_body={"session_id": "_internal_sql_gen"},
    )
    return response.choices[0].message.content


def format_results_for_prompt(results: List[Dict[str, Any]], sql: str) -> str:
    if not results:
        return f"【查询结果】\nSQL: {sql}\n未查询到数据"
    
    lines = [f"【查询结果】", f"SQL: {sql}"]
    for i, row in enumerate(results, 1):
        row_str = "；".join(f"{k}: {v}" for k, v in row.items())
        lines.append(f"{i}. {row_str}")
    return "\n".join(lines)


def build_final_prompt(question: str, results: List[Dict[str, Any]], sql: str) -> str:
    results_text = format_results_for_prompt(results, sql)
    return f"""你是企业内部 APQP 与项目质量管理助手。回答必须严格基于下方查询结果，禁止编造。

【输出格式】
【结论】1-2句概括查询结果
【项目情况】分点列出关键事实（编号、责任人、日期、状态、数值等）
【关注点】需要跟进的风险/问题/缺口；没有则写「暂无额外关注点」
【建议】1-3条可执行下一步

【内容质量】
1. 使用专业简洁业务语言；多条数据请分点清晰展示
2. 禁止输出不存在的项目ID、风险等级、日期、负责人等字段
3. 关键词可用 **加粗**；不要输出 SQL、JSON 或字段英文名

【用户问题】
{question}

{results_text}

请按上述格式回答："""


def run_dynamic_query(question: str) -> Dict[str, Any]:
    results, sql = generate_and_execute_sql(question, generate_response)
    
    # generate_and_execute_sql 失败时 sql 为错误信息而非有效 SQL
    if not sql.strip().upper().startswith("SELECT"):
        return {"error": sql}
    
    # 使用规则引擎生成自然语言回复（替代大模型，更快更可靠）
    answer = generate_natural_reply(question, results, sql)
    
    return {
        "question": question,
        "sql": sql,
        "results": results,
        "answer": answer
    }


if __name__ == "__main__":
    print("==== APQP动态SQL查询Demo ====")
    print(f"推理模式: {INFERENCE_MODE} (http=通过API, direct=本地加载)")
    print("输入 exit 退出对话\n")
    while True:
        user_input = input("用户提问：")
        if user_input.strip().lower() == "exit":
            print("会话结束")
            break
        
        try:
            result = run_dynamic_query(user_input)
            if "error" in result:
                print(f"\n错误：{result['error']}\n")
            else:
                print(f"\n生成SQL：\n{result['sql']}")
                print(f"\n查询结果：\n{json.dumps(result['results'], ensure_ascii=False, indent=2)}")
                print(f"\nAI回复：\n{result['answer']}\n")
        except Exception as e:
            print(f"\n执行出错：{e}\n")
