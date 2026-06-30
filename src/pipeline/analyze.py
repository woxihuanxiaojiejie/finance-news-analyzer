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


def generate_sentiment_flow_recommendations(
    analyzed_news: list[dict[str, Any]],
    ai_config: dict,
    api_key: str,
    data_dir: str,
) -> list[dict[str, Any]]:
    """基于市场情绪和资金流向，生成 AI 股票推荐。

    在批量新闻分析完成后调用。综合全局情绪指标、板块轮动信号、
    高影响力新闻等数据，让 AI 主动推荐各板块的看多/看空标的。
    """
    if not analyzed_news or not api_key:
        logger.warning("无已分析新闻或 API Key，跳过情绪推荐")
        return []

    # 聚合市场数据
    sentiment_stats = {"利好": 0, "中性": 0, "利空": 0}
    scores = []
    rotation_signals = []
    with_analysis = []

    for news in analyzed_news:
        a = news.get("ai_analysis")
        if not a:
            continue
        with_analysis.append(news)
        sentiment = a.get("sentiment", "中性")
        sentiment_stats[sentiment] = sentiment_stats.get(sentiment, 0) + 1
        scores.append(a.get("impact_score", 0))
        if a.get("sector_rotation") and a.get("rotation_detail"):
            rotation_signals.append({
                "rotation_detail": a["rotation_detail"],
                "impact_score": a.get("impact_score", 5),
            })

    total = len(with_analysis)
    if total == 0:
        return []

    def _pct(count):
        return round(count / total * 100, 1) if total > 0 else 0

    positive_pct = _pct(sentiment_stats["利好"])
    negative_pct = _pct(sentiment_stats["利空"])
    neutral_pct = _pct(sentiment_stats["中性"])
    net_bias = round(positive_pct - negative_pct, 1)

    avg_impact = round(sum(scores) / len(scores), 1) if scores else 0

    # 市场温度
    high_risk_count = sum(
        1 for n in with_analysis
        if n.get("ai_analysis", {}).get("risk_level") == "高"
    )
    net_sentiment_value = (net_bias + 100) / 2
    avg_impact_normalized = (avg_impact / 10) * 100
    risk_correction = 100 - (round(high_risk_count / total * 100, 1) * 2) if total > 0 else 50
    risk_correction = max(0, min(100, risk_correction))
    market_temperature = round(
        0.40 * net_sentiment_value +
        0.30 * avg_impact_normalized +
        0.20 * positive_pct +
        0.10 * risk_correction
    )
    market_temperature = max(0, min(100, market_temperature))

    # 行业排名
    industry_map: dict[str, list] = {}
    for news in with_analysis:
        for ind in news.get("ai_analysis", {}).get("industries", []):
            if ind not in industry_map:
                industry_map[ind] = []
            industry_map[ind].append(news)
    industry_ranked = sorted(industry_map.items(), key=lambda kv: len(kv[1]), reverse=True)

    # 高影响力新闻
    impact_sorted = sorted(
        with_analysis,
        key=lambda n: n.get("ai_analysis", {}).get("impact_score", 0),
        reverse=True,
    )

    # 已识别的股票列表
    existing_stocks = []
    for news in with_analysis:
        for stock in news.get("ai_analysis", {}).get("related_stocks", []):
            name = stock.get("name", "")
            if name and name not in existing_stocks:
                existing_stocks.append(name)

    # 构建 prompt
    from src.ai.prompts import build_sentiment_flow_prompt

    prompt = build_sentiment_flow_prompt(
        sentiment_overview={
            "positive_pct": positive_pct,
            "neutral_pct": neutral_pct,
            "negative_pct": negative_pct,
            "net_bias": net_bias,
        },
        market_temperature=market_temperature,
        avg_impact=avg_impact,
        total_analyzed=total,
        industry_ranked=industry_ranked,
        rotation_signals=rotation_signals,
        high_impact_news=impact_sorted[:5],
        existing_stocks=existing_stocks,
    )

    # 调用 AI
    client = DeepSeekClient(
        api_key=api_key,
        base_url=ai_config.get("base_url", "https://api.deepseek.com"),
        model=ai_config.get("model", "deepseek-chat"),
        temperature=ai_config.get("temperature", 0.3),  # 稍高温度增加多样性
    )

    result = client.recommend_by_sentiment_flow(prompt)

    # 保存原始响应
    try:
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        filepath = os.path.join(data_dir, f"ai-sentiment-flow-{today}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({
                "success": result["success"],
                "market_data": {
                    "market_temperature": market_temperature,
                    "net_bias": net_bias,
                    "avg_impact": avg_impact,
                    "total_analyzed": total,
                },
                "results": result.get("results"),
                "error": result.get("error"),
            }, f, ensure_ascii=False, indent=2)
        logger.info("情绪推荐原始响应已保存到 %s", filepath)
    except Exception:
        logger.exception("保存情绪推荐响应失败")

    if result["success"]:
        logger.info("情绪推荐成功，共 %d 条推荐", len(result.get("results", [])))
    else:
        logger.warning("情绪推荐失败: %s", result.get("error"))

    return result.get("results", [])


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
