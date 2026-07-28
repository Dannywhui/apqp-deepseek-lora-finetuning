import os
import json
import torch
from transformers import AutoModelForCausalLM
from peft import PeftModel  # 修复：添加 peft

# ===== 修正路径 =====
base_model_path = "./deepseek_model/deepseek-ai/deepseek-llm-7b-chat"  # 修复：改为实际文件夹名
lora_path = "./output/deepseek-mutil-test/checkpoint-27"  # 修复：指向 checkpoint
save_path = "./output/merge_model3"

os.makedirs(save_path, exist_ok=True)

def load_tokenizer(model_dir: str):
    from transformers import PreTrainedTokenizerFast

    cfg_path = os.path.join(model_dir, "tokenizer_config.json")
    tok_path = os.path.join(model_dir, "tokenizer.json")

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

    tok = PreTrainedTokenizerFast(tokenizer_file=tok_path, bos_token=bos, eos_token=eos, pad_token=pad)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok


def _fix_no_split_modules(model):
    ns = getattr(model, "_no_split_modules", None)
    if isinstance(ns, set):
        model._no_split_modules = list(ns)

def merge_lora():
    print("加载 tokenizer...")
    tokenizer = load_tokenizer(base_model_path)

    # ===== 直接用 CPU 加载基础模型 =====
    print("加载基础模型（CPU / float32）...")
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_path,
        device_map="cpu",
        torch_dtype=torch.float32,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )

    _fix_no_split_modules(base_model)

    print("加载 LoRA...")
    model = PeftModel.from_pretrained(base_model, lora_path)

    print("开始合并 LoRA...")
    model = model.merge_and_unload()

    print("保存模型...")
    model.save_pretrained(save_path, safe_serialization=True)

    tokenizer.save_pretrained(save_path)
    print("✅ 合并完成！保存路径：", save_path)

if __name__ == "__main__":
    merge_lora()