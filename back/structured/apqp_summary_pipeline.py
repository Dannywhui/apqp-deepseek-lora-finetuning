# -*- coding: utf-8 -*-
"""
APQP 多Sheet Excel 分层摘要流水线
=====================================
功能：
  - 读取包含70+工作表的APQP项目Excel文件
  - 三级分层递归摘要：单Sheet摘要 → 阶段汇总 → 结项报告
  - Sheet文本压缩策略（控制token）
  - 调试日志能力

技术约束：
  - 使用 transformers 原生调用本地 DeepSeek-7B-chat 模型
  - 禁止一次性把全部表格文本送入模型
  - 串行执行，防止显存溢出
"""

import os
import re
import time
import logging
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl import load_workbook

# 配置日志
logger = logging.getLogger(__name__)


# ============================================================
# 常量配置
# ============================================================

# 单次输入token上限（软限制，超过会告警）
MAX_INPUT_TOKENS = 5500
# token告警阈值（达到此比例时触发截断预警）
TOKEN_WARN_RATIO = 0.85

# LLM推理温度
LLM_TEMPERATURE = 0.2
# LLM推理最大新token数
LLM_MAX_NEW_TOKENS = 1024
# LLM推理top_p
LLM_TOP_P = 0.9

# 每个Sheet保留的样例行数
SAMPLE_ROWS = 20

# APQP五大阶段关键词映射（用于Sheet自动分组）
APQP_PHASE_KEYWORDS: Dict[str, List[str]] = {
    "phase1_plan": [
        "计划", "立项", "项目启动", "需求", "市场", "顾客需求",
        "可行性", "商务", "报价", "合同", "plan", "planning",
    ],
    "phase2_product_design": [
        "产品设计", "设计开发", "DFMEA", "DFMEA", "设计失效",
        "图纸", "规格", "BOM", "物料清单", "设计验证", "DV",
        "设计评审", "原型", "样件", "product design",
    ],
    "phase3_process_design": [
        "过程设计", "过程开发", "PFMEA", "PFMEA", "过程失效",
        "流程图", "PFD", "过程流程", "控制计划", "Control Plan", "CP",
        "作业指导书", "SOP", "工装", "设备", "检具",
        "包装", "储运", "process design",
    ],
    "phase4_product_validation": [
        "产品确认", "过程确认", "PPAP", "生产件批准",
        "试生产", "Run Rate", "节拍", "产能",
        "MSA", "测量系统", "GRR", "Cpk", "过程能力", "SPC",
        "尺寸检验", "材料试验", "性能试验", "validation", "PPAP",
    ],
    "phase5_feedback": [
        "反馈", "改进", "纠正措施", "预防措施", "CAPA",
        "经验教训", "持续改进", "客户投诉", "抱怨", "售后",
        "8D", "问题解决", "feedback", "improvement",
    ],
}

# 阶段中文名
APQP_PHASE_NAMES: Dict[str, str] = {
    "phase1_plan": "第一阶段：计划和确定项目",
    "phase2_product_design": "第二阶段：产品设计和开发",
    "phase3_process_design": "第三阶段：过程设计和开发",
    "phase4_product_validation": "第四阶段：产品和过程确认",
    "phase5_feedback": "第五阶段：反馈、评定和纠正措施",
}

# 特殊Sheet类型（需要专项提取）
SPECIAL_SHEET_PATTERNS: Dict[str, re.Pattern] = {
    "dfmea": re.compile(r"DFMEA|设计FMEA|设计失效", re.IGNORECASE),
    "pfmea": re.compile(r"PFMEA|过程FMEA|过程失效", re.IGNORECASE),
    "control_plan": re.compile(r"控制计划|Control\s*Plan|\bCP\b", re.IGNORECASE),
    "msa": re.compile(r"MSA|测量系统|GRR|偏倚|线性|稳定性", re.IGNORECASE),
    "spc": re.compile(r"SPC|过程能力|Cpk|Ppk|Cm|Cmk|控制图", re.IGNORECASE),
}

# 数值列关键词（用于自动识别需要统计的列）
NUMERIC_COL_KEYWORDS = [
    "RPN", "rpn", "严重度", "S ", "发生频度", "O ", "探测度", "D ",
    "Cpk", "Ppk", "Cm", "Cmk", "GRR", "GRR%", "ndc",
    "均值", "最大值", "最小值", "标准差", "方差",
    "数量", "个数", "金额", "成本", "重量",
    "得分", "评分", "等级",
]


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SheetCompressedData:
    """压缩后的单Sheet数据"""
    sheet_name: str
    column_names: List[str]
    sample_rows: List[Dict[str, Any]]
    numeric_stats: Dict[str, Dict[str, float]]
    special_extract: Optional[Dict[str, Any]]
    is_empty: bool
    row_count: int
    token_count: int = 0


@dataclass
class SheetSummary:
    """单Sheet摘要"""
    sheet_name: str
    summary: str
    token_count: int
    inference_time: float
    error: Optional[str] = None


@dataclass
class PhaseSummary:
    """阶段汇总"""
    phase_key: str
    phase_name: str
    sheet_summaries: List[SheetSummary]
    phase_summary: str
    token_count: int
    inference_time: float


@dataclass
class PipelineDebugInfo:
    """流水线调试信息"""
    total_time: float = 0.0
    sheet_times: Dict[str, float] = field(default_factory=dict)
    token_risks: List[Dict[str, Any]] = field(default_factory=list)
    truncation_warnings: List[str] = field(default_factory=list)
    slowest_sheets: List[Tuple[str, float]] = field(default_factory=list)
    skipped_sheets: List[str] = field(default_factory=list)
    error_sheets: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class PipelineResult:
    """流水线最终结果"""
    final_report: str
    phase_summaries: List[PhaseSummary]
    sheet_summaries: List[SheetSummary]
    debug_info: PipelineDebugInfo


# ============================================================
# 工具函数
# ============================================================

def _count_tokens(text: str, tokenizer: Any = None) -> int:
    """统计token数量，优先使用分词器，否则按字符数估算"""
    if tokenizer is not None:
        try:
            return len(tokenizer.encode(text))
        except Exception:
            pass
    # 粗略估算：中文约1字1token，英文约4字符1token
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_chars = len(text) - cn_chars
    return cn_chars + max(1, en_chars // 4)


def _truncate_text(text: str, max_tokens: int, tokenizer: Any = None) -> Tuple[str, bool]:
    """按token数截断文本，返回(截断后文本, 是否被截断)"""
    current_tokens = _count_tokens(text, tokenizer)
    if current_tokens <= max_tokens:
        return text, False

    # 二分法截断
    left, right = 0, len(text)
    truncated = False
    while left < right:
        mid = (left + right) // 2
        candidate = text[:mid]
        if _count_tokens(candidate, tokenizer) <= max_tokens:
            left = mid + 1
        else:
            right = mid
            truncated = True
    return text[:max(0, left - 1)], truncated


def _safe_read_excel_sheet(
    workbook_path: str,
    sheet_name: str,
) -> Optional[pd.DataFrame]:
    """安全读取单个Excel Sheet，捕获异常"""
    try:
        df = pd.read_excel(workbook_path, sheet_name=sheet_name, dtype=object)
        return df
    except Exception as e:
        logger.warning(f"读取Sheet失败 [{sheet_name}]: {e}")
        return None


def _is_blank_or_template(df: pd.DataFrame) -> bool:
    """判断Sheet是否为空白或纯模板（无实际数据）"""
    if df is None or df.empty:
        return True

    # 去除全空行和全空列
    df_clean = df.dropna(how="all").dropna(axis=1, how="all")
    if df_clean.empty:
        return True

    # 如果有效行数少于2行（只有表头），视为模板
    if len(df_clean) < 2:
        return True

    # 如果所有单元格内容都是模板词（如"填写"、"示例"、"备注"、"无"），视为模板
    template_keywords = {"填写", "示例", "备注", "无", "N/A", "n/a", "NA", "—", "-", "/"}
    non_empty_cells = 0
    template_cells = 0
    for col in df_clean.columns:
        for val in df_clean[col].dropna():
            val_str = str(val).strip()
            if val_str:
                non_empty_cells += 1
                if val_str in template_keywords or val_str.startswith("请"):
                    template_cells += 1

    if non_empty_cells > 0 and template_cells / non_empty_cells > 0.8:
        return True

    return False


# ============================================================
# Sheet文本压缩
# ============================================================

def _extract_numeric_stats(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """提取数值列的统计指标"""
    stats: Dict[str, Dict[str, float]] = {}

    for col in df.columns:
        col_str = str(col)
        # 只对疑似数值列做统计
        is_numeric_col = any(kw in col_str for kw in NUMERIC_COL_KEYWORDS)
        if not is_numeric_col:
            # 尝试转换为数值，如果大部分可转换也视为数值列
            try:
                numeric_series = pd.to_numeric(df[col], errors="coerce")
                if numeric_series.notna().sum() >= max(3, len(df) * 0.3):
                    is_numeric_col = True
            except Exception:
                continue

        if not is_numeric_col:
            continue

        try:
            numeric_series = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(numeric_series) == 0:
                continue
            stats[col_str] = {
                "count": int(len(numeric_series)),
                "mean": float(numeric_series.mean()),
                "min": float(numeric_series.min()),
                "max": float(numeric_series.max()),
                "std": float(numeric_series.std()) if len(numeric_series) > 1 else 0.0,
            }
            # 对于RPN等指标，额外统计高风险数量
            if "rpn" in col_str.lower():
                high_risk = int((numeric_series >= 100).sum())
                stats[col_str]["high_risk_count"] = high_risk
        except Exception:
            continue

    return stats


def _extract_special_sheet(
    sheet_name: str,
    df: pd.DataFrame,
) -> Optional[Dict[str, Any]]:
    """对特殊Sheet进行专项信息提取（FMEA/控制计划/MSA/SPC等）"""
    sheet_lower = sheet_name.lower()
    result: Dict[str, Any] = {}

    # DFMEA / PFMEA 专项提取
    if SPECIAL_SHEET_PATTERNS["dfmea"].search(sheet_name) or \
       SPECIAL_SHEET_PATTERNS["pfmea"].search(sheet_name):
        result["type"] = "fmea"
        result["items"] = []

        # 尝试定位关键列
        col_map = _find_fmea_columns(df.columns)
        if col_map:
            for _, row in df.iterrows():
                try:
                    rpn_val = _safe_float(row.get(col_map.get("rpn", "RPN")))
                    severity = _safe_float(row.get(col_map.get("severity", "严重度")))
                    item = {
                        "failure_mode": str(row.get(col_map.get("failure_mode", ""))),
                        "effect": str(row.get(col_map.get("effect", ""))),
                        "cause": str(row.get(col_map.get("cause", ""))),
                        "severity": severity,
                        "occurrence": _safe_float(row.get(col_map.get("occurrence", ""))),
                        "detection": _safe_float(row.get(col_map.get("detection", ""))),
                        "rpn": rpn_val,
                        "risk_level": "高" if rpn_val >= 100 else ("中" if rpn_val >= 60 else "低"),
                    }
                    # 只保留高风险项或前10项
                    if rpn_val >= 60 or len(result["items"]) < 10:
                        result["items"].append(item)
                except Exception:
                    continue

            # 按RPN降序，保留前20个
            result["items"].sort(key=lambda x: x.get("rpn", 0), reverse=True)
            result["items"] = result["items"][:20]

    # 控制计划专项提取
    elif SPECIAL_SHEET_PATTERNS["control_plan"].search(sheet_name):
        result["type"] = "control_plan"
        result["control_items"] = []
        try:
            for _, row in df.head(30).iterrows():
                vals = [str(v) for v in row.dropna().values if str(v).strip()]
                if vals:
                    result["control_items"].append(" | ".join(vals[:8]))
        except Exception:
            pass

    # MSA专项提取
    elif SPECIAL_SHEET_PATTERNS["msa"].search(sheet_name):
        result["type"] = "msa"
        try:
            for col in df.columns:
                col_str = str(col).lower()
                if "grr" in col_str or "ndc" in col_str:
                    vals = pd.to_numeric(df[col], errors="coerce").dropna()
                    if len(vals) > 0:
                        result[col_str] = {
                            "mean": float(vals.mean()),
                            "min": float(vals.min()),
                            "max": float(vals.max()),
                        }
        except Exception:
            pass

    # SPC/过程能力专项提取
    elif SPECIAL_SHEET_PATTERNS["spc"].search(sheet_name):
        result["type"] = "spc"
        result["cpk_values"] = []
        try:
            for _, row in df.iterrows():
                for col in df.columns:
                    col_str = str(col).lower()
                    if "cpk" in col_str or "ppk" in col_str:
                        val = _safe_float(row.get(col))
                        if val is not None:
                            result["cpk_values"].append({
                                "characteristic": str(row.iloc[0]) if len(row) > 0 else "",
                                col_str: val,
                                "status": "合格" if val >= 1.33 else ("警告" if val >= 1.0 else "不合格"),
                            })
            result["cpk_values"] = result["cpk_values"][:30]
        except Exception:
            pass

    return result if result else None


def _find_fmea_columns(columns: List) -> Dict[str, str]:
    """在FMEA表中尝试定位关键列"""
    col_map: Dict[str, str] = {}
    for col in columns:
        col_str = str(col).lower()
        if "失效模式" in col_str or "failure" in col_str:
            col_map["failure_mode"] = str(col)
        elif "失效影响" in col_str or "effect" in col_str:
            col_map["effect"] = str(col)
        elif "失效原因" in col_str or "cause" in col_str:
            col_map["cause"] = str(col)
        elif "严重度" in col_str or (col_str == "s"):
            col_map["severity"] = str(col)
        elif "频度" in col_str or "发生" in col_str or (col_str == "o"):
            col_map["occurrence"] = str(col)
        elif "探测度" in col_str or (col_str == "d"):
            col_map["detection"] = str(col)
        elif "rpn" in col_str or "风险优先" in col_str:
            col_map["rpn"] = str(col)
    return col_map


def _safe_float(val: Any) -> Optional[float]:
    """安全转换为float"""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f == f else None  # 排除NaN
    except (ValueError, TypeError):
        return None


def compress_sheet(
    workbook_path: str,
    sheet_name: str,
    tokenizer: Any = None,
) -> SheetCompressedData:
    """
    压缩单个Sheet为token友好的格式

    策略：
      - 保留表名、列名
      - 保留表头 + 前SAMPLE_ROWS行样例
      - 计算数值列统计指标
      - 对特殊Sheet（FMEA/控制计划/MSA/SPC）做专项提取
    """
    logger.info(f"[Sheet压缩] 正在处理: {sheet_name}")

    df = _safe_read_excel_sheet(workbook_path, sheet_name)
    if df is None:
        return SheetCompressedData(
            sheet_name=sheet_name,
            column_names=[],
            sample_rows=[],
            numeric_stats={},
            special_extract=None,
            is_empty=True,
            row_count=0,
        )

    # 判断是否为空白/模板Sheet
    is_empty = _is_blank_or_template(df)

    # 列名
    column_names = [str(c) for c in df.columns]

    # 样例行（前N行）
    sample_rows: List[Dict[str, Any]] = []
    if not is_empty:
        df_sample = df.head(SAMPLE_ROWS).fillna("")
        for _, row in df_sample.iterrows():
            row_dict = {str(k): str(v) for k, v in row.items() if str(v).strip()}
            if row_dict:
                sample_rows.append(row_dict)

    # 数值列统计
    numeric_stats = _extract_numeric_stats(df) if not is_empty else {}

    # 特殊Sheet专项提取
    special_extract = _extract_special_sheet(sheet_name, df) if not is_empty else None

    # 构建压缩文本并统计token
    compressed_text = _format_compressed_sheet(
        sheet_name, column_names, sample_rows, numeric_stats, special_extract
    )
    token_count = _count_tokens(compressed_text, tokenizer)

    return SheetCompressedData(
        sheet_name=sheet_name,
        column_names=column_names,
        sample_rows=sample_rows,
        numeric_stats=numeric_stats,
        special_extract=special_extract,
        is_empty=is_empty,
        row_count=len(df),
        token_count=token_count,
    )


def _format_compressed_sheet(
    sheet_name: str,
    column_names: List[str],
    sample_rows: List[Dict[str, Any]],
    numeric_stats: Dict[str, Dict[str, float]],
    special_extract: Optional[Dict[str, Any]],
) -> str:
    """将压缩数据格式化为文本供LLM输入"""
    lines: List[str] = []
    lines.append(f"=== Sheet: {sheet_name} ===")
    lines.append(f"列名: {', '.join(column_names)}")

    if sample_rows:
        lines.append(f"\n数据样例（前{len(sample_rows)}行）:")
        for i, row in enumerate(sample_rows, 1):
            row_str = " | ".join(f"{k}:{v}" for k, v in list(row.items())[:10])
            lines.append(f"  行{i}: {row_str}")

    if numeric_stats:
        lines.append("\n数值列统计:")
        for col, stats in numeric_stats.items():
            parts = [f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}"
                     for k, v in stats.items()]
            lines.append(f"  [{col}]: {', '.join(parts)}")

    if special_extract:
        lines.append("\n专项提取:")
        ext_type = special_extract.get("type", "unknown")
        if ext_type == "fmea":
            lines.append("  [FMEA高风险项]:")
            for item in special_extract.get("items", []):
                lines.append(
                    f"    - RPN={item.get('rpn')} "
                    f"(S={item.get('severity')}/O={item.get('occurrence')}/D={item.get('detection')}) "
                    f"[{item.get('risk_level')}] "
                    f"失效模式: {item.get('failure_mode', '')[:50]}"
                )
        elif ext_type == "control_plan":
            lines.append("  [控制计划要点]:")
            for item in special_extract.get("control_items", [])[:15]:
                lines.append(f"    - {item}")
        elif ext_type == "msa":
            lines.append("  [MSA指标]:")
            for k, v in special_extract.items():
                if k != "type":
                    lines.append(f"    - {k}: {v}")
        elif ext_type == "spc":
            lines.append("  [过程能力Cpk/Ppk]:")
            for item in special_extract.get("cpk_values", [])[:15]:
                lines.append(f"    - {item}")

    return "\n".join(lines)


# ============================================================
# LLM调用封装
# ============================================================

class LocalLLMClient:
    """
    本地LLM客户端封装
    使用transformers原生调用DeepSeek-7B-chat模型
    """

    def __init__(self, model: Any, tokenizer: Any):
        self.model = model
        self.tokenizer = tokenizer

    def generate(
        self,
        prompt: str,
        temperature: float = LLM_TEMPERATURE,
        max_new_tokens: int = LLM_MAX_NEW_TOKENS,
        top_p: float = LLM_TOP_P,
        debug: bool = False,
    ) -> Tuple[str, int, float]:
        """
        调用本地模型生成回复

        返回: (生成文本, 输入token数, 推理耗时秒)
        """
        import torch

        start_time = time.time()
        input_tokens = _count_tokens(prompt, self.tokenizer)

        if debug:
            logger.info(f"[LLM调用] 输入token数: {input_tokens}")
            logger.info(f"[LLM调用] 原始prompt (前500字符): {prompt[:500]}")

        # token超限检查
        if input_tokens > MAX_INPUT_TOKENS:
            logger.warning(
                f"[LLM调用] token数超阈值! 输入={input_tokens}, 上限={MAX_INPUT_TOKENS}"
            )

        # 编码输入
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=4096,
        )
        inputs.pop("token_type_ids", None)

        device = next(self.model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        # 推理
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,  # 关闭随机采样
                temperature=temperature,
                top_p=top_p,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # 解码输出
        response = self.tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        ).strip()

        inference_time = time.time() - start_time

        if debug:
            logger.info(f"[LLM调用] 推理耗时: {inference_time:.2f}秒")
            logger.info(f"[LLM调用] 输出 (前300字符): {response[:300]}")

        return response, input_tokens, inference_time


# ============================================================
# Prompt模板
# ============================================================

def _build_sheet_summary_prompt(sheet_data: SheetCompressedData) -> str:
    """构建单Sheet摘要Prompt"""
    compressed_text = _format_compressed_sheet(
        sheet_data.sheet_name,
        sheet_data.column_names,
        sheet_data.sample_rows,
        sheet_data.numeric_stats,
        sheet_data.special_extract,
    )

    return f"""你是专业的APQP项目质量工程师。请根据以下Sheet的压缩数据，生成该工作表的简洁摘要。

【要求】
1. 说明该Sheet主题、核心内容、关键数据；有数值统计（RPN、Cpk、GRR等）时列出关键指标
2. 有风险项时指出主要风险及影响
3. 摘要控制在150字以内，使用要点式表达；直接输出摘要，不要开场白
4. 禁止空话；不要编造压缩数据中没有的内容

【Sheet压缩数据】
{compressed_text}

【摘要】:"""


def _build_phase_summary_prompt(
    phase_name: str,
    sheet_summaries: List[SheetSummary],
) -> str:
    """构建阶段汇总Prompt"""
    summaries_text = "\n\n".join(
        f"--- [{s.sheet_name}] ---\n{s.summary}"
        for s in sheet_summaries
    )

    return f"""你是专业的APQP项目质量工程师。请根据以下各Sheet的摘要，汇总生成{phase_name}的阶段总结。

【要求】
1. 概述本阶段完成的主要工作
2. 列出关键交付物与完成情况
3. 指出关键质量指标与风险
4. 控制在300字以内，使用Markdown；直接输出，不要开场白
5. 建议写清可执行动作；不要编造摘要中没有的内容

【本阶段各Sheet摘要】
{summaries_text}

【{phase_name}阶段总结】:"""


def _build_final_report_prompt(phase_summaries: List[PhaseSummary]) -> str:
    """构建最终结项报告Prompt"""
    phases_text = "\n\n".join(
        f"## {ps.phase_name}\n{ps.phase_summary}"
        for ps in phase_summaries
    )

    return f"""你是资深的APQP项目评审专家。请根据以下五大阶段的总结，生成一份完整的APQP项目结项报告。

【报告结构要求 - 严格按照以下5个部分输出】
1. **项目概述**：简述项目背景、目标、范围（150字以内）
2. **APQP五大阶段完成情况**：综合各阶段完成情况进行评估（400字以内）
3. **关键质量指标汇总**：汇总风险、过程能力、测量系统等关键指标（300字以内）
4. **现存风险与遗留问题**：列出主要风险和未解决问题（200字以内）
5. **结项结论与改进建议**：给出结项结论和可执行改进建议（200字以内）

【输出格式】
- 使用标准Markdown；标题层级分明
- 关键数据和结论用列表呈现；总字数控制在1500字以内
- 建议要可执行（动作 + 责任角色 + 时机）；禁止空话套话
- 不要编造阶段总结中没有的事实

【五大阶段总结】
{phases_text}

【APQP项目结项报告】:"""


# ============================================================
# 阶段分组
# ============================================================

def classify_sheet_to_phase(sheet_name: str) -> str:
    """根据Sheet名称自动分类到APQP五大阶段"""
    sheet_lower = sheet_name.lower()

    # 从最具体的阶段开始匹配（倒序，避免误匹配）
    for phase_key in reversed(APQP_PHASE_KEYWORDS):
        for keyword in APQP_PHASE_KEYWORDS[phase_key]:
            if keyword.lower() in sheet_lower:
                return phase_key

    # 默认归入未分类（后续会按字母顺序分散到各阶段或单独处理）
    return "unclassified"


# ============================================================
# 主流水线
# ============================================================

class APQPSummaryPipeline:
    """
    APQP多Sheet Excel分层摘要流水线

    三级摘要流程：
    1. 一级：遍历每个Sheet → 生成单Sheet摘要
    2. 二级：按APQP五大阶段分组 → 生成阶段总结
    3. 三级：汇总全部阶段 → 生成最终结项报告
    """

    def __init__(self, model: Any, tokenizer: Any, debug: bool = True):
        self.llm = LocalLLMClient(model, tokenizer)
        self.tokenizer = tokenizer
        self.debug = debug

    def run(
        self,
        excel_path: str,
        max_sheets: Optional[int] = None,
    ) -> PipelineResult:
        """
        执行完整的分层摘要流水线

        参数:
            excel_path: Excel文件路径
            max_sheets: 最多处理的Sheet数（用于调试，None表示全部）

        返回:
            PipelineResult 包含最终报告、各阶段总结、调试信息
        """
        pipeline_start = time.time()
        debug_info = PipelineDebugInfo()

        logger.info("=" * 60)
        logger.info(f"[流水线启动] 文件: {excel_path}")
        logger.info("=" * 60)

        # ========== 第一步：读取所有Sheet名 ==========
        try:
            workbook = load_workbook(excel_path, read_only=True, data_only=True)
            all_sheet_names = workbook.sheetnames
            workbook.close()
        except Exception as e:
            raise RuntimeError(f"Excel文件读取失败: {e}") from e

        logger.info(f"[Sheet列表] 共 {len(all_sheet_names)} 个Sheet")
        if self.debug:
            for i, name in enumerate(all_sheet_names, 1):
                logger.info(f"  {i:2d}. {name}")

        if max_sheets:
            all_sheet_names = all_sheet_names[:max_sheets]
            logger.info(f"[调试模式] 仅处理前 {max_sheets} 个Sheet")

        # ========== 第二步：一级摘要（逐个Sheet） ==========
        logger.info("\n" + "=" * 60)
        logger.info("[一级摘要] 开始逐个Sheet生成摘要")
        logger.info("=" * 60)

        sheet_summaries: List[SheetSummary] = []

        for sheet_name in all_sheet_names:
            sheet_start = time.time()

            try:
                # 压缩Sheet
                compressed = compress_sheet(excel_path, sheet_name, self.tokenizer)

                if compressed.is_empty:
                    logger.info(f"  [跳过] {sheet_name} - 空白/纯模板Sheet")
                    debug_info.skipped_sheets.append(sheet_name)
                    continue

                if self.debug:
                    logger.info(
                        f"  [Sheet] {sheet_name} - "
                        f"行数:{compressed.row_count}, "
                        f"压缩token:{compressed.token_count}, "
                        f"样例行:{len(compressed.sample_rows)}, "
                        f"统计列:{len(compressed.numeric_stats)}"
                    )

                # Token超限检查
                if compressed.token_count > MAX_INPUT_TOKENS * TOKEN_WARN_RATIO:
                    warn_msg = (
                        f"Sheet [{sheet_name}] 压缩后token数={compressed.token_count}, "
                        f"接近上限{MAX_INPUT_TOKENS}"
                    )
                    logger.warning(f"  [Token预警] {warn_msg}")
                    debug_info.token_risks.append({
                        "sheet": sheet_name,
                        "tokens": compressed.token_count,
                        "type": "single_sheet",
                    })
                    debug_info.truncation_warnings.append(warn_msg)

                # 构建Prompt并调用LLM
                prompt = _build_sheet_summary_prompt(compressed)
                prompt_tokens = _count_tokens(prompt, self.tokenizer)

                if self.debug:
                    logger.info(f"  [LLM] 单Sheet摘要Prompt token数: {prompt_tokens}")

                if prompt_tokens > MAX_INPUT_TOKENS:
                    logger.warning(
                        f"  [Token超限] 单Sheet摘要Prompt超过上限{MAX_INPUT_TOKENS}, "
                        f"实际={prompt_tokens}, 将截断"
                    )
                    prompt, was_truncated = _truncate_text(
                        prompt, MAX_INPUT_TOKENS, self.tokenizer
                    )
                    if was_truncated:
                        debug_info.truncation_warnings.append(
                            f"Sheet [{sheet_name}] 摘要Prompt已截断"
                        )

                summary_text, input_tokens, inference_time = self.llm.generate(
                    prompt,
                    temperature=LLM_TEMPERATURE,
                    max_new_tokens=256,
                    top_p=LLM_TOP_P,
                    debug=self.debug,
                )

                sheet_elapsed = time.time() - sheet_start
                debug_info.sheet_times[sheet_name] = sheet_elapsed

                if self.debug:
                    logger.info(
                        f"  [完成] {sheet_name} - "
                        f"输入token:{input_tokens}, "
                        f"推理耗时:{inference_time:.2f}s, "
                        f"总耗时:{sheet_elapsed:.2f}s"
                    )

                sheet_summaries.append(SheetSummary(
                    sheet_name=sheet_name,
                    summary=summary_text,
                    token_count=input_tokens,
                    inference_time=inference_time,
                ))

            except Exception as e:
                sheet_elapsed = time.time() - sheet_start
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(f"  [错误] {sheet_name} - {error_msg}")
                if self.debug:
                    logger.error(traceback.format_exc())

                debug_info.sheet_times[sheet_name] = sheet_elapsed
                debug_info.error_sheets.append((sheet_name, error_msg))

                # 错误Sheet也添加一个占位摘要
                sheet_summaries.append(SheetSummary(
                    sheet_name=sheet_name,
                    summary=f"[该Sheet处理失败: {error_msg}]",
                    token_count=0,
                    inference_time=0,
                    error=error_msg,
                ))

        # ========== 第三步：二级摘要（按阶段分组） ==========
        logger.info("\n" + "=" * 60)
        logger.info("[二级摘要] 按APQP五大阶段分组汇总")
        logger.info("=" * 60)

        # 分组
        phase_groups: Dict[str, List[SheetSummary]] = {
            k: [] for k in APQP_PHASE_KEYWORDS
        }
        phase_groups["unclassified"] = []

        for ss in sheet_summaries:
            phase_key = classify_sheet_to_phase(ss.sheet_name)
            if phase_key not in phase_groups:
                phase_groups[phase_key] = []
            phase_groups[phase_key].append(ss)

        # 未分类的Sheet均分
        unclassified = phase_groups.pop("unclassified", [])
        if unclassified:
            logger.info(f"  [未分类] {len(unclassified)} 个Sheet将均分到各阶段")
            phase_keys = list(APQP_PHASE_KEYWORDS.keys())
            for i, ss in enumerate(unclassified):
                target_phase = phase_keys[i % len(phase_keys)]
                phase_groups[target_phase].append(ss)

        # 生成各阶段总结
        phase_summaries: List[PhaseSummary] = []

        for phase_key in APQP_PHASE_KEYWORDS:
            phase_name = APQP_PHASE_NAMES[phase_key]
            group_sheets = phase_groups.get(phase_key, [])

            if not group_sheets:
                logger.info(f"  [跳过] {phase_name} - 无Sheet")
                phase_summaries.append(PhaseSummary(
                    phase_key=phase_key,
                    phase_name=phase_name,
                    sheet_summaries=[],
                    phase_summary="本阶段无相关Sheet数据。",
                    token_count=0,
                    inference_time=0,
                ))
                continue

            logger.info(
                f"  [阶段] {phase_name} - "
                f"包含 {len(group_sheets)} 个Sheet: "
                f"{', '.join(s.sheet_name for s in group_sheets[:5])}"
                f"{'...' if len(group_sheets) > 5 else ''}"
            )

            try:
                prompt = _build_phase_summary_prompt(phase_name, group_sheets)
                prompt_tokens = _count_tokens(prompt, self.tokenizer)

                if self.debug:
                    logger.info(f"    [LLM] 阶段汇总Prompt token数: {prompt_tokens}")

                if prompt_tokens > MAX_INPUT_TOKENS:
                    logger.warning(
                        f"    [Token超限] 阶段汇总Prompt超过上限{MAX_INPUT_TOKENS}, "
                        f"实际={prompt_tokens}"
                    )
                    debug_info.token_risks.append({
                        "phase": phase_name,
                        "tokens": prompt_tokens,
                        "type": "phase_summary",
                    })
                    prompt, was_truncated = _truncate_text(
                        prompt, MAX_INPUT_TOKENS, self.tokenizer
                    )
                    if was_truncated:
                        debug_info.truncation_warnings.append(
                            f"阶段 [{phase_name}] 汇总Prompt已截断"
                        )

                phase_text, input_tokens, inference_time = self.llm.generate(
                    prompt,
                    temperature=LLM_TEMPERATURE,
                    max_new_tokens=512,
                    top_p=LLM_TOP_P,
                    debug=self.debug,
                )

                logger.info(
                    f"    [完成] {phase_name} - "
                    f"输入token:{input_tokens}, 推理耗时:{inference_time:.2f}s"
                )

                phase_summaries.append(PhaseSummary(
                    phase_key=phase_key,
                    phase_name=phase_name,
                    sheet_summaries=group_sheets,
                    phase_summary=phase_text,
                    token_count=input_tokens,
                    inference_time=inference_time,
                ))

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(f"    [错误] {phase_name} - {error_msg}")
                phase_summaries.append(PhaseSummary(
                    phase_key=phase_key,
                    phase_name=phase_name,
                    sheet_summaries=group_sheets,
                    phase_summary=f"[阶段汇总失败: {error_msg}]",
                    token_count=0,
                    inference_time=0,
                ))

        # ========== 第四步：三级摘要（最终报告） ==========
        logger.info("\n" + "=" * 60)
        logger.info("[三级摘要] 生成最终结项报告")
        logger.info("=" * 60)

        try:
            prompt = _build_final_report_prompt(phase_summaries)
            prompt_tokens = _count_tokens(prompt, self.tokenizer)

            if self.debug:
                logger.info(f"  [LLM] 最终报告Prompt token数: {prompt_tokens}")

            if prompt_tokens > MAX_INPUT_TOKENS:
                logger.warning(
                    f"  [Token超限] 最终报告Prompt超过上限{MAX_INPUT_TOKENS}, "
                    f"实际={prompt_tokens}"
                )
                debug_info.token_risks.append({
                    "level": "final_report",
                    "tokens": prompt_tokens,
                    "type": "final_report",
                })
                prompt, was_truncated = _truncate_text(
                    prompt, MAX_INPUT_TOKENS, self.tokenizer
                )
                if was_truncated:
                    debug_info.truncation_warnings.append("最终报告Prompt已截断")

            final_report, _, _ = self.llm.generate(
                prompt,
                temperature=LLM_TEMPERATURE,
                max_new_tokens=1500,
                top_p=LLM_TOP_P,
                debug=self.debug,
            )

            logger.info("  [完成] 最终结项报告生成完毕")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"  [错误] 最终报告生成失败: {error_msg}")
            final_report = f"# 结项报告生成失败\n\n错误信息: {error_msg}"

        # ========== 第五步：汇总调试信息 ==========
        debug_info.total_time = time.time() - pipeline_start

        # 找出耗时最高的Sheet（Top5）
        sorted_times = sorted(
            debug_info.sheet_times.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        debug_info.slowest_sheets = sorted_times[:5]

        logger.info("\n" + "=" * 60)
        logger.info("[流水线完成] 性能统计")
        logger.info("=" * 60)
        logger.info(f"  总耗时: {debug_info.total_time:.2f} 秒")
        logger.info(f"  处理Sheet数: {len(sheet_summaries)} (跳过 {len(debug_info.skipped_sheets)})")
        logger.info(f"  错误Sheet数: {len(debug_info.error_sheets)}")

        if debug_info.slowest_sheets:
            logger.info("  耗时最高的5个Sheet:")
            for name, t in debug_info.slowest_sheets:
                logger.info(f"    - {name}: {t:.2f}s")

        if debug_info.token_risks:
            logger.info("  Token超限风险:")
            for risk in debug_info.token_risks:
                logger.info(f"    - {risk}")

        if debug_info.truncation_warnings:
            logger.info("  截断预警:")
            for warn in debug_info.truncation_warnings:
                logger.info(f"    - {warn}")

        return PipelineResult(
            final_report=final_report,
            phase_summaries=phase_summaries,
            sheet_summaries=sheet_summaries,
            debug_info=debug_info,
        )


# ============================================================
# 便捷入口函数
# ============================================================

def generate_apqp_report(
    excel_path: str,
    model: Any,
    tokenizer: Any,
    debug: bool = True,
    max_sheets: Optional[int] = None,
) -> PipelineResult:
    """
    便捷函数：生成APQP项目结项报告

    参数:
        excel_path: Excel文件路径
        model: 已加载的transformers模型
        tokenizer: 已加载的分词器
        debug: 是否输出调试日志
        max_sheets: 最多处理的Sheet数（调试用）

    返回:
        PipelineResult 对象
    """
    pipeline = APQPSummaryPipeline(model, tokenizer, debug=debug)
    return pipeline.run(excel_path, max_sheets=max_sheets)
