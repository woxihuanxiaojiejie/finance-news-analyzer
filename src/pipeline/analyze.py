"""AI 分析编排模块。"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from src.ai import DeepSeekClient

logger = logging.getLogger(__name__)


def batch_analyze(
    news_list: list[dict[str, Any]],
    ai_config: dict,
    api_key: str,
    data_dir: str,
) -> list[dict[str, Any]]:
    """分批对新闻进行 AI 分析。

    返回每条新闻附加 AI 分析结果后的记录。
    """
    if not news_list:
        return []

    if not api_key:
        logger.error("API Key 未配置，跳过 AI 分析")
        for news in news_list:
            news["ai_analysis"] = None
        return news_list

    client = DeepSeekClient(
        api_key=api_key,
        base_url=ai_config.get("base_url", "https://api.deepseek.com"),
        model=ai_config.get("model", "deepseek-chat"),
        temperature=ai_config.get("temperature", 0.2),
    )

    batch_size = ai_config.get("max_news_per_batch", 10)
    batches = [
        news_list[i : i + batch_size]
        for i in range(0, len(news_list), batch_size)
    ]

    analyzed_count = 0
    failed_count = 0
    raw_responses = []

    for batch_idx, batch in enumerate(batches):
        logger.info(
            "AI 分析第 %d/%d 批（%d 条）",
            batch_idx + 1, len(batches), len(batch),
        )

        result = client.analyze_news(batch)

        # 保存原始响应
        raw_responses.append({
            "batch": batch_idx,
            "success": result["success"],
            "response": result,
        })

        if result["success"] and result["results"]:
            for news, analysis in zip(batch, result["results"]):
                news["ai_analysis"] = analysis
                if analysis:
                    analyzed_count += 1
        else:
            for news in batch:
                news["ai_analysis"] = None
                news["ai_error"] = result.get("error", "分析失败")
            failed_count += len(batch)

    logger.info(
        "AI 分析完成：成功 %d 条，失败 %d 条",
        analyzed_count, failed_count,
    )

    # 保存原始 AI 响应到 data 目录
    _save_raw_responses(raw_responses, data_dir)

    return news_list


def _save_raw_responses(responses: list[dict], data_dir: str) -> None:
    """保存 AI 原始响应到 data 目录。"""
    try:
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        filename = f"ai-raw-response-{today}.json"
        filepath = os.path.join(data_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(responses, f, ensure_ascii=False, indent=2)
        logger.info("AI 原始响应已保存到 %s", filepath)
    except Exception:
        logger.exception("保存 AI 原始响应失败")
