"""HTML 报告渲染模块（v3.0 增强版）。"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import jinja2

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


# ---------- v3.0 辅助函数 ----------

def _calc_credibility(source: str) -> int:
    """根据来源计算可信度评分。"""
    source_lower = source.lower()
    if any(kw in source_lower for kw in ["官方", "公告", "政府", "央行", "证监会", "银保监会"]):
        return 100
    if any(kw in source_lower for kw in ["监管", "交易所", "上交所", "深交所", "港交所"]):
        return 95
    if any(kw in source_lower for kw in ["财联社", "华尔街见闻", "路透", "bloomberg", "金融时报", "财新"]):
        return 85
    if any(kw in source_lower for kw in ["新浪财经", "东方财富", "同花顺", "证券时报", "券商"]):
        return 80
    if any(kw in source_lower for kw in ["行业媒体", "产业", "36氪"]):
        return 70
    return 50


def _calc_freshness(published_at: str) -> float:
    """根据发布时间计算时效性评分，公式 e^(-t/24)。"""
    if not published_at:
        return 0.5
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hours = (now - pub).total_seconds() / 3600
        if hours < 0:
            return 1.0
        return round(__import__("math").exp(-hours / 24), 4)
    except Exception:
        return 0.5


def _watchlist_trend(news_list_for_ind):
    """判断行业观察趋势：短期/中期/长期。"""
    trend_counts = {"短期": 0, "中期": 0, "长期": 0}
    for n in news_list_for_ind:
        t = n.get("ai_analysis", {}).get("trend", "短期")
        trend_counts[t] = trend_counts.get(t, 0) + 1
    return max(trend_counts, key=trend_counts.get)


def _watchlist_risk(news_list_for_ind):
    """判断行业观察风险：高/中/低。"""
    risk_counts = {"高": 0, "中": 0, "低": 0}
    for n in news_list_for_ind:
        r = n.get("ai_analysis", {}).get("risk_level", "低")
        risk_counts[r] = risk_counts.get(r, 0) + 1
    total = len(news_list_for_ind)
    if total > 0 and risk_counts["高"] / total >= 0.3:
        return "高"
    elif total > 0 and risk_counts["中"] / total >= 0.3:
        return "中"
    return "低"


# ---------- 主聚合函数 ----------

def _aggregate_for_report(news_list: list[dict[str, Any]]) -> dict:
    """聚合新闻数据用于报告渲染（v3.0 增强版）。"""
    high_risk = []
    with_analysis = []
    without_analysis = []

    for news in news_list:
        analysis = news.get("ai_analysis")
        if analysis:
            with_analysis.append(news)
            if analysis.get("risk_level") == "高":
                high_risk.append(news)
        else:
            without_analysis.append(news)

    # ---- 情绪分析统计 ----
    sentiment_stats = {"利好": 0, "中性": 0, "利空": 0}
    sentiment_total = 0
    bullish_bearish_list: list[dict] = []
    for news in with_analysis:
        a = news["ai_analysis"]
        sentiment = a.get("sentiment", "中性")
        sentiment_stats[sentiment] = sentiment_stats.get(sentiment, 0) + 1
        sentiment_total += 1
        if a.get("bullish_bearish"):
            bullish_bearish_list.append({
                "title": news.get("title", ""),
                "bullish_bearish": a["bullish_bearish"],
                "sentiment": a.get("sentiment", "中性"),
                "risk_level": a.get("risk_level", "低"),
            })

    def _pct(count):
        return round(count / sentiment_total * 100, 1) if sentiment_total > 0 else 0

    positive_pct = _pct(sentiment_stats["利好"])
    negative_pct = _pct(sentiment_stats["利空"])
    neutral_pct = _pct(sentiment_stats["中性"])
    net_bias = positive_pct - negative_pct

    sentiment_overview = {
        "positive": sentiment_stats["利好"],
        "neutral": sentiment_stats["中性"],
        "negative": sentiment_stats["利空"],
        "positive_pct": positive_pct,
        "neutral_pct": neutral_pct,
        "negative_pct": negative_pct,
        "total": sentiment_total,
        "net_bias": net_bias,
    }

    # ---- 影响力 TOP N (v3.0 增强) ----
    impact_ranked = sorted(
        with_analysis,
        key=lambda n: n.get("ai_analysis", {}).get("impact_score", 0),
        reverse=True,
    )
    impact_top = []
    for news in impact_ranked[:10]:
        a = news.get("ai_analysis", {})
        impact_score = a.get("impact_score", 0)
        credibility_score = a.get("credibility_score", _calc_credibility(news.get("source", "")))
        freshness_score = a.get("freshness_score", _calc_freshness(news.get("published_at", "")))
        final_impact = a.get("final_impact_score",
                             round(impact_score * (credibility_score / 100) * freshness_score, 1))
        impact_top.append({
            "title": news.get("title", ""),
            "impact_score": impact_score,
            "credibility_score": credibility_score,
            "freshness_score": round(freshness_score, 2),
            "final_impact_score": final_impact,
            "sentiment": a.get("sentiment", "中性"),
            "risk_level": a.get("risk_level", "低"),
            "summary": a.get("summary", ""),
        })

    # ---- 平均影响力 ----
    scores = [n.get("ai_analysis", {}).get("impact_score", 0) for n in with_analysis]
    avg_impact = round(sum(scores) / len(scores), 1) if scores else 0

    # ---- 板块轮动信号 ----
    rotation_signals: list[dict] = []
    for news in with_analysis:
        a = news["ai_analysis"]
        if a.get("sector_rotation") and a.get("rotation_detail"):
            rotation_signals.append({
                "title": news.get("title", ""),
                "rotation_detail": a["rotation_detail"],
                "risk_level": a.get("risk_level", "低"),
                "impact_score": a.get("impact_score", 5),
            })

    # ---- 趋势分布 ----
    trend_stats: dict[str, int] = {}
    for news in with_analysis:
        t = news.get("ai_analysis", {}).get("trend", "短期")
        trend_stats[t] = trend_stats.get(t, 0) + 1

    # ---- 按行业聚合 ----
    industry_map: dict[str, list[dict]] = {}
    for news in with_analysis:
        analysis = news["ai_analysis"]
        for ind in analysis.get("industries", []):
            if ind not in industry_map:
                industry_map[ind] = []
            industry_map[ind].append(news)

    industry_ranked = sorted(
        industry_map.items(),
        key=lambda kv: len(kv[1]),
        reverse=True,
    )

    # ---- 按公司聚合 ----
    company_map: dict[str, list[dict]] = {}
    for news in with_analysis:
        analysis = news["ai_analysis"]
        for comp in analysis.get("companies", []):
            if comp not in company_map:
                company_map[comp] = []
            company_map[comp].append(news)

    # ---- 关联股票聚合 ----
    stock_map: dict[str, dict] = {}
    for news in with_analysis:
        a = news["ai_analysis"]
        for stock in a.get("related_stocks", []):
            code = stock.get("code", "") or stock.get("name", "")
            if not code:
                continue
            if code not in stock_map:
                stock_map[code] = {
                    "name": stock.get("name", code),
                    "code": stock.get("code", ""),
                    "count": 0,
                    "sentiments": [],
                    "news_titles": [],
                }
            stock_map[code]["count"] += 1
            stock_map[code]["sentiments"].append(a.get("sentiment", "中性"))
            if len(stock_map[code]["news_titles"]) < 3:
                stock_map[code]["news_titles"].append(news.get("title", ""))

    for stock_info in stock_map.values():
        s_list = stock_info["sentiments"]
        pos = sum(1 for s in s_list if s == "利好")
        neg = sum(1 for s in s_list if s == "利空")
        stock_info["sentiment_label"] = "利好" if pos > neg else ("利空" if neg > pos else "中性")

    # ---- 来源统计 ----
    source_stats: dict[str, int] = {}
    total_analyzed = 0
    total_failed = 0
    total_skipped = 0
    for news in news_list:
        source = news.get("source", "未知")
        source_stats[source] = source_stats.get(source, 0) + 1
        if news.get("ai_analysis"):
            total_analyzed += 1
        elif news.get("ai_error"):
            total_failed += 1
        else:
            total_skipped += 1

    # ---- 今日概览（取前 5 条重要的） ----
    overview = []
    for news in with_analysis:
        if len(overview) >= 5:
            break
        a = news.get("ai_analysis", {})
        if a.get("risk_level") in ("高", "中"):
            overview.append({
                "title": news.get("title"),
                "summary": a.get("summary"),
                "risk_level": a.get("risk_level"),
                "sentiment": a.get("sentiment", "中性"),
                "impact_score": a.get("impact_score", 0),
            })

    # ---- 市场温度计算 (v3.0) ----
    # 40% × 净情绪值 + 30% × 平均影响力 + 20% × 利好占比 + 10% × 风险修正
    net_sentiment_value = (net_bias + 100) / 2  # net_bias(-100~100) -> 0~100
    avg_impact_normalized = (avg_impact / 10) * 100
    risk_correction = 100 - (_pct(len(high_risk)) * 2) if sentiment_total > 0 else 50
    risk_correction = max(0, min(100, risk_correction))

    market_temperature = round(
        0.40 * net_sentiment_value +
        0.30 * avg_impact_normalized +
        0.20 * positive_pct +
        0.10 * risk_correction
    )
    market_temperature = max(0, min(100, market_temperature))

    # ---- 今日核心事件 TOP 3 (v3.0) ----
    daily_focus = []
    for news in impact_ranked[:3]:
        a = news.get("ai_analysis", {})
        daily_focus.append({
            "rank": len(daily_focus) + 1,
            "title": news.get("title", ""),
            "impact_summary": a.get("summary", ""),
            "score": a.get("impact_score", 0),
        })

    # ---- 资金流向分析 (v3.0) ----
    capital_flow = []
    for sig in rotation_signals:
        detail = sig.get("rotation_detail", "")
        strength = sig.get("impact_score", 5)
        from_sector = ""
        to_sector = ""
        m = re.search(r'从(.+?)流向(.+)', detail)
        if m:
            from_sector = m.group(1).strip()
            to_sector = m.group(2).strip().rstrip('。，.')
        else:
            m2 = re.search(r'(.+?)→(.+)', detail)
            if m2:
                from_sector = m2.group(1).strip()
                to_sector = m2.group(2).strip().rstrip('。，.')
        if from_sector and to_sector:
            capital_flow.append({
                "from": from_sector,
                "to": to_sector,
                "strength": min(strength, 10),
            })
        elif detail:
            capital_flow.append({
                "from": "",
                "to": detail,
                "strength": min(strength, 10),
            })

    # ---- AI 投资观察名单 (v3.0) ----
    watchlist = []
    for ind_name, ind_news in industry_ranked[:5]:
        if len(ind_news) < 2:
            continue
        watchlist.append({
            "type": "sector",
            "name": ind_name,
            "reason": f"当日 {len(ind_news)} 条相关新闻，为最活跃板块之一",
            "trend": _watchlist_trend(ind_news),
            "risk": _watchlist_risk(ind_news),
        })

    # --- 温度等级标签 ---
    if market_temperature <= 20:
        temp_level = "极度悲观"
        temp_icon = "❄️"
    elif market_temperature <= 40:
        temp_level = "悲观"
        temp_icon = "☁️"
    elif market_temperature <= 60:
        temp_level = "中性"
        temp_icon = "😐"
    elif market_temperature <= 80:
        temp_level = "乐观"
        temp_icon = "🙂"
    else:
        temp_level = "极度乐观"
        temp_icon = "🔥"

    return {
        "high_risk": high_risk,
        "with_analysis": with_analysis,
        "without_analysis": without_analysis,
        "industry_map": industry_map,
        "industry_ranked": industry_ranked,
        "company_map": company_map,
        "stock_map": stock_map,
        "source_stats": source_stats,
        "total_analyzed": total_analyzed,
        "total_failed": total_failed,
        "total_skipped": total_skipped,
        "total_news": len(news_list),
        "overview": overview,
        # 新增分析维度
        "sentiment_overview": sentiment_overview,
        "impact_top": impact_top,
        "avg_impact": avg_impact,
        "rotation_signals": rotation_signals,
        "bullish_bearish_list": bullish_bearish_list,
        "trend_stats": trend_stats,
        # v3.0 新增
        "market_temperature": market_temperature,
        "temp_level": temp_level,
        "temp_icon": temp_icon,
        "daily_focus": daily_focus,
        "capital_flow": capital_flow,
        "watchlist": watchlist,
    }


# ---------- 渲染入口 ----------

def render_report(
    news_list: list[dict[str, Any]],
    report_config: dict,
    output_dir: str,
    source_stats: dict[str, int],
    errors: list[str],
) -> str:
    """渲染 HTML 报告，返回报告文件路径。"""
    today = datetime.now(timezone(timedelta(hours=8)))
    date_str = today.strftime("%Y-%m-%d")
    agg = _aggregate_for_report(news_list)

    context = {
        "report_title": report_config.get("title", "每日财经新闻分析报告"),
        "language": report_config.get("language", "zh-CN"),
        "date": date_str,
        "generated_at": today.strftime("%Y-%m-%d %H:%M:%S"),
        "overview": agg["overview"],
        "high_risk": agg["high_risk"],
        "industry_map": agg["industry_map"],
        "industry_ranked": agg["industry_ranked"],
        "company_map": agg["company_map"],
        "stock_map": agg["stock_map"],
        "source_stats": agg["source_stats"],
        "news_list": news_list,
        "total_news": agg["total_news"],
        "total_analyzed": agg["total_analyzed"],
        "total_failed": agg["total_failed"],
        "total_skipped": agg["total_skipped"],
        "errors": errors,
        "source_fetch_stats": source_stats,
        # 已有分析维度
        "sentiment_overview": agg["sentiment_overview"],
        "impact_top": agg["impact_top"],
        "avg_impact": agg["avg_impact"],
        "rotation_signals": agg["rotation_signals"],
        "bullish_bearish_list": agg["bullish_bearish_list"],
        "trend_stats": agg["trend_stats"],
        # v3.0 新增
        "market_temperature": agg["market_temperature"],
        "temp_level": agg["temp_level"],
        "temp_icon": agg["temp_icon"],
        "daily_focus": agg["daily_focus"],
        "capital_flow": agg["capital_flow"],
        "watchlist": agg["watchlist"],
    }

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        autoescape=False,
    )
    template = env.get_template("report.html")
    html = template.render(**context)

    filename = f"{date_str}-finance-news-report.html"
    filepath = os.path.abspath(os.path.join(output_dir, filename))
    os.makedirs(output_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("HTML 报告已生成: %s", filepath)
    return filepath
