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


# ---------- v3.1 股票交易推荐 ----------

def _get_board(code: str) -> tuple[str, str, str]:
    """根据股票代码识别所属板块。

    返回 (board_key, board_name, access_note)

    A 股板块分类：
    - 沪市主板: 600/601/603/605 开头
    - 深市主板: 000/001/002/003 开头
    - 创业板(GEM): 300/301 开头 — 需 10 万资产 + 2 年经验
    - 科创板(STAR): 688 开头 — 需 50 万资产 + 2 年经验
    - 北交所: 8 开头(非 8xxxxx.HK) — 需 50 万资产 + 2 年经验
    - 港股: .HK 后缀
    - 其他: 无法识别
    """
    if not code:
        return ("unknown", "其他", "")

    code_upper = code.upper().strip()

    # 港股（优先检查，因为 .HK 后缀很明确）
    if ".HK" in code_upper:
        return ("hk", "港股", "港股通")

    # 提取数字部分
    import re
    m = re.match(r'^(\d{5,6})', code_upper.replace(".SH", "").replace(".SZ", "").replace(".BJ", ""))
    if not m:
        return ("unknown", "其他", "")

    prefix = m.group(1)
    prefix_3 = prefix[:3]
    prefix_num = int(prefix_3) if prefix_3.isdigit() else 0

    # 科创板: 688xxx
    if prefix.startswith("688"):
        return ("star", "科创板", "需 50 万资产")

    # 创业板: 300xxx, 301xxx
    if prefix_3 in ("300", "301"):
        return ("gem", "创业板", "需 10 万资产")

    # 沪市主板: 600-605xxx
    if 600 <= prefix_num <= 605:
        return ("sh_main", "沪市主板", "无门槛")

    # 深市主板: 000-003xxx
    if 0 <= prefix_num <= 3:
        return ("sz_main", "深市主板", "无门槛")

    # 北交所: 8xxxxx (6位数字，排除港股)
    if prefix.startswith("8") and len(prefix) >= 5:
        return ("bse", "北交所", "需 50 万资产")

    return ("unknown", "其他", "")


def _compute_stock_recommendations(stock_map: dict[str, dict]) -> list[dict]:
    """基于 AI 分析数据计算每只股票的交易推荐信号。

    返回推荐列表，按 |avg_signal| * confidence 降序排列。
    """
    SENTIMENT_MAP = {"利好": 1, "中性": 0, "利空": -1}

    recommendations = []
    for code, info in stock_map.items():
        mentions = info.get("mentions", [])
        count = info["count"]
        if not mentions or count < 1:
            continue

        # 1. signal_score = sum(sentiment_value * impact_score)
        signal_score = 0.0
        for m in mentions:
            sv = SENTIMENT_MAP.get(m["sentiment"], 0)
            signal_score += sv * m.get("impact_score", 0)

        # 2. avg_signal（按提及次数归一化）
        avg_signal = round(signal_score / count, 2)

        # 3. 一致性：主导方向占比
        pos_count = sum(1 for m in mentions if SENTIMENT_MAP.get(m["sentiment"], 0) > 0)
        neg_count = sum(1 for m in mentions if SENTIMENT_MAP.get(m["sentiment"], 0) < 0)
        neu_count = count - pos_count - neg_count
        dominant = max(pos_count, neg_count, neu_count)
        consensus = round(dominant / count, 2)

        # 4. 推荐等级（基于 avg_signal 阈值）
        if avg_signal >= 5.0:
            recommendation = "买入"
        elif avg_signal >= 2.0:
            recommendation = "增持"
        elif avg_signal > -2.0:
            recommendation = "观望"
        elif avg_signal >= -5.0:
            recommendation = "减持"
        else:
            recommendation = "卖出"

        # 5. 信号强度 = min(count * 2, 10) + 一致性加分（上限 10）
        base_confidence = min(count * 2, 10)
        consensus_bonus = 2 if consensus >= 0.8 else (1 if consensus >= 0.6 else 0)
        confidence = min(base_confidence + consensus_bonus, 10)

        # 6. 关键理由：取影响力最高的 bullish_bearish
        best_mention = max(mentions, key=lambda m: m.get("impact_score", 0))
        key_reason = best_mention.get("bullish_bearish", "")

        # 7. 主导周期
        trend_counts: dict[str, int] = {}
        for m in mentions:
            t = m.get("trend", "短期")
            trend_counts[t] = trend_counts.get(t, 0) + 1
        dominant_trend = max(trend_counts, key=trend_counts.get)

        # 8. 主导风险等级
        risk_counts: dict[str, int] = {}
        for m in mentions:
            r = m.get("risk_level", "低")
            risk_counts[r] = risk_counts.get(r, 0) + 1
        dominant_risk = max(risk_counts, key=risk_counts.get)

        # 9. 聚合情绪标签
        s_list = info.get("sentiments", [])
        pos = sum(1 for s in s_list if s == "利好")
        neg = sum(1 for s in s_list if s == "利空")
        sentiment_label = "利好" if pos > neg else ("利空" if neg > pos else "中性")

        # 10. 新闻链接列表（含 url）
        news_links = info.get("news_links", [])

        # 11. 板块分类
        board_key, board_name, access_note = _get_board(code)

        recommendations.append({
            "name": info["name"],
            "code": info["code"],
            "count": count,
            "recommendation": recommendation,
            "avg_signal": avg_signal,
            "confidence": confidence,
            "consensus": consensus,
            "sentiment_label": sentiment_label,
            "positive_count": pos_count,
            "negative_count": neg_count,
            "neutral_count": neu_count,
            "risk_level": dominant_risk,
            "trend": dominant_trend,
            "key_reason": key_reason,
            "news_titles": info.get("news_titles", []),
            "news_links": news_links,   # v3.2: 新闻标题+链接
            "board": board_key,         # v3.4: 板块标识
            "board_name": board_name,   # v3.4: 板块中文名
            "access_note": access_note, # v3.4: 交易门槛说明
        })

    # 按 |avg_signal| * confidence 降序排列（最强信号在前）
    recommendations.sort(
        key=lambda r: abs(r["avg_signal"]) * r["confidence"],
        reverse=True,
    )

    return recommendations


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
                "url": news.get("url", ""),
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

    # ---- 多空观点分类 (v3.2) ----
    bullish_bearish_bullish = []
    bullish_bearish_bearish = []
    bullish_bearish_neutral = []
    for item in bullish_bearish_list:
        s = item.get("sentiment", "中性")
        if s == "利好":
            bullish_bearish_bullish.append(item)
        elif s == "利空":
            bullish_bearish_bearish.append(item)
        else:
            bullish_bearish_neutral.append(item)

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
            "url": news.get("url", ""),
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

    # ---- 关联股票聚合 + 分类 (v3.2) ----
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
                    "news_links": [],   # v3.2: 保存新闻标题+链接
                    "mentions": [],
                }
            stock_map[code]["count"] += 1
            stock_map[code]["sentiments"].append(a.get("sentiment", "中性"))
            if len(stock_map[code]["news_titles"]) < 5:
                stock_map[code]["news_titles"].append(news.get("title", ""))
            if len(stock_map[code]["news_links"]) < 5:
                stock_map[code]["news_links"].append({
                    "title": news.get("title", ""),
                    "url": news.get("url", ""),
                })
            stock_map[code]["mentions"].append({
                "sentiment": a.get("sentiment", "中性"),
                "impact_score": a.get("impact_score", 0),
                "bullish_bearish": a.get("bullish_bearish", ""),
                "trend": a.get("trend", "短期"),
                "risk_level": a.get("risk_level", "低"),
                "url": news.get("url", ""),
            })

    # ---- 关联股票分类：利好/利空/中性 ----
    stock_bullish = {}
    stock_bearish = {}
    stock_neutral = {}
    for code, info in stock_map.items():
        s_list = info["sentiments"]
        pos = sum(1 for s in s_list if s == "利好")
        neg = sum(1 for s in s_list if s == "利空")
        neu = sum(1 for s in s_list if s == "中性")
        if pos > neg and pos > neu:
            stock_bullish[code] = info
        elif neg > pos and neg > neu:
            stock_bearish[code] = info
        else:
            stock_neutral[code] = info

    for stock_info in stock_map.values():
        s_list = stock_info["sentiments"]
        pos = sum(1 for s in s_list if s == "利好")
        neg = sum(1 for s in s_list if s == "利空")
        stock_info["sentiment_label"] = "利好" if pos > neg else ("利空" if neg > pos else "中性")

    # ---- v3.1 股票交易推荐 ----
    stock_recommendations = _compute_stock_recommendations(stock_map)

    # ---- v3.4 按板块分组 ----
    # 板块显示顺序: 主板(可以交易) → 创业板(10万门槛) → 科创板(50万) → 北交所 → 港股 → 其他
    BOARD_ORDER = ["sh_main", "sz_main", "gem", "star", "bse", "hk", "unknown"]
    BOARD_LABELS = {
        "sh_main": ("沪市主板", "🏛️", "#3b82f6", "无门槛，可交易"),
        "sz_main": ("深市主板", "🏛️", "#6366f1", "无门槛，可交易"),
        "gem": ("创业板", "🔬", "#f59e0b", "需 10 万资产"),
        "star": ("科创板", "🚀", "#ef4444", "需 50 万资产"),
        "bse": ("北交所", "📊", "#8b5cf6", "需 50 万资产"),
        "hk": ("港股", "🇭🇰", "#ec4899", "港股通"),
        "unknown": ("其他", "❓", "#6b7280", ""),
    }
    recommendations_by_board: dict[str, list[dict]] = {}
    for rec in stock_recommendations:
        board_key = rec.get("board", "unknown")
        if board_key not in recommendations_by_board:
            recommendations_by_board[board_key] = []
        recommendations_by_board[board_key].append(rec)

    # 按 BOARD_ORDER 排序，保持每个板块内部按信号强度排序
    board_summary = []
    for bk in BOARD_ORDER:
        if bk in recommendations_by_board:
            label, icon, color, note = BOARD_LABELS.get(bk, (bk, "", "#6b7280", ""))
            recs = recommendations_by_board[bk]
            # 统计该板块的推荐操作分布
            buy_count = sum(1 for r in recs if r["recommendation"] in ("买入", "增持"))
            sell_count = sum(1 for r in recs if r["recommendation"] in ("卖出", "减持"))
            board_summary.append({
                "key": bk,
                "label": label,
                "icon": icon,
                "color": color,
                "note": note,
                "count": len(recs),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "recommendations": recs,
            })

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

    # ---- AI 投资观察名单 (v3.2) ----
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
            "news_links": [{"title": n.get("title", ""), "url": n.get("url", "")} for n in ind_news[:5]],
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
        "stock_bullish": stock_bullish,    # v3.2: 利好分类
        "stock_bearish": stock_bearish,    # v3.2: 利空分类
        "stock_neutral": stock_neutral,    # v3.2: 中性分类
        "source_stats": source_stats,
        "total_analyzed": total_analyzed,
        "total_failed": total_failed,
        "total_skipped": total_skipped,
        "total_news": len(news_list),
        # 新增分析维度
        "sentiment_overview": sentiment_overview,
        "impact_top": impact_top,
        "avg_impact": avg_impact,
        "rotation_signals": rotation_signals,
        "bullish_bearish_list": bullish_bearish_list,
        "bullish_bearish_bullish": bullish_bearish_bullish,  # v3.2
        "bullish_bearish_bearish": bullish_bearish_bearish,  # v3.2
        "bullish_bearish_neutral": bullish_bearish_neutral,  # v3.2
        "trend_stats": trend_stats,
        # v3.0 新增
        "market_temperature": market_temperature,
        "temp_level": temp_level,
        "temp_icon": temp_icon,
        "daily_focus": daily_focus,
        "capital_flow": capital_flow,
        "watchlist": watchlist,
        "stock_recommendations": stock_recommendations,  # v3.1
        "stock_recommendations_by_board": board_summary,  # v3.4: 按板块分组
    }


# ---------- 渲染入口 ----------

def render_report(
    news_list: list[dict[str, Any]],
    report_config: dict,
    output_dir: str,
    source_stats: dict[str, int],
    errors: list[str],
    sentiment_flow_recs: list[dict[str, Any]] | None = None,
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
        "high_risk": agg["high_risk"],
        "industry_map": agg["industry_map"],
        "industry_ranked": agg["industry_ranked"],
        "company_map": agg["company_map"],
        "stock_map": agg["stock_map"],
        "stock_bullish": agg["stock_bullish"],    # v3.2
        "stock_bearish": agg["stock_bearish"],    # v3.2
        "stock_neutral": agg["stock_neutral"],    # v3.2
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
        "bullish_bearish_bullish": agg["bullish_bearish_bullish"],  # v3.2
        "bullish_bearish_bearish": agg["bullish_bearish_bearish"],  # v3.2
        "bullish_bearish_neutral": agg["bullish_bearish_neutral"],  # v3.2
        "trend_stats": agg["trend_stats"],
        # v3.0 新增
        "market_temperature": agg["market_temperature"],
        "temp_level": agg["temp_level"],
        "temp_icon": agg["temp_icon"],
        "daily_focus": agg["daily_focus"],
        "capital_flow": agg["capital_flow"],
        "watchlist": agg["watchlist"],
        "stock_recommendations": agg["stock_recommendations"],
        "stock_recommendations_by_board": agg["stock_recommendations_by_board"],  # v3.4
        "sentiment_flow_recs": sentiment_flow_recs or [],  # v3.5: 情绪+资金流推荐
    }

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        autoescape=False,
    )
    template = env.get_template("report.html")
    html = template.render(**context)

    import time
    filename = f"{date_str}-finance-news-report.html"
    filepath = os.path.abspath(os.path.join(output_dir, filename))
    os.makedirs(output_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("HTML 报告已生成: %s", filepath)
    return filepath
