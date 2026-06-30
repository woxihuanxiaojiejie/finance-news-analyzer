"""AI 分析提示词管理。"""

SYSTEM_PROMPT = """你是一位资深的财经新闻分析师，拥有 15 年以上的股票市场研究经验。
你的分析风格注重数据驱动、逻辑清晰、观点鲜明。

请严格遵循以下要求：
1. 输出必须是合法的 JSON 数组，不要包含任何 markdown 代码块标记。
2. 数组中的每个元素对应一条新闻的分析结果，顺序与输入一致。
3. 不要添加任何额外的说明文字。
4. 使用中文进行分析和回复。
5. 情绪判断要有依据，不要盲目乐观或悲观。
6. 关联股票务必使用 A 股标准代码格式（如 600519.SH，000001.SZ）或港股（00700.HK），如果新闻未提及具体代码，可标注主要关联公司名称。
7. **关联股票覆盖度（v3.4 新增）**：分析每条新闻时，请尽可能全面地识别受影响的股票，包括：
   a. 直接提及的上市公司
   b. 同行业/同概念板块中可能受连带影响的其他股票
   c. 产业链上下游的关键公司
   d. 尽量覆盖不同板块：主板（600/601/603、000/001/002）、创业板（300/301）、科创板（688），不要只关注单一板块
   e. 每类至少尝试识别 1-2 只股票，但只推荐真正相关的，不要虚构
"""

USER_PROMPT_TEMPLATE = """请分析以下 {count} 条财经新闻，对每条新闻返回以下字段：

--- 基础分析 ---
- summary: 一句话新闻摘要（50 字以内）
- market_impact: 市场影响分析（100 字以内）

--- 定量评估 ---
- risk_level: 风险等级，"高"/"中"/"低" 三档
  * 高：可能引发明显市场波动、监管冲击、行业重估或公司重大变化
  * 中：对相关行业或公司有一定影响，但范围或确定性有限
  * 低：信息偏常规，短期市场影响有限
- risk_reason: 风险等级原因（30 字以内）
- impact_score: 影响力评分，1-10 之间的整数
  * 1-3 低影响力（日常消息）
  * 4-6 中等影响力（需关注）
  * 7-8 高影响力（重要事件）
  * 9-10 极高影响力（市场转折级别）

--- 情绪与方向 ---
- sentiment: 情绪倾向，值为 "利好"/"中性"/"利空"
- sentiment_strength: 情绪强度，1-10 之间的整数（1=极弱，10=极强）
- bullish_bearish: 对相关板块的多空判断，用一句话给出结论和建议方向（50 字以内）

--- 投资关联 ---
- related_stocks: 关联股票列表（数组），每项包含 name（股票名称）和 code（股票代码，如 600519.SH）
- industries: 涉及行业列表（数组，如 ["半导体", "新能源"]）
- companies: 涉及公司列表（数组，如 ["阿里巴巴", "腾讯"]）

--- 策略信号 ---
- sector_rotation: 板块轮动信号，值为 true/false，判断该新闻是否可能触发板块轮动
- rotation_detail: 若 sector_rotation 为 true，说明资金可能从哪个板块流向哪个板块（30 字以内）；若为 false，填空字符串
- trend: 趋势判断，值为 "短期"/"中期"/"长期"
  * 短期：主要影响 1-5 个交易日内
  * 中期：影响持续数周至数月
  * 长期：影响持续半年以上，可能改变行业格局

--- 可信度与时效性评估 (v3.0 新增) ---
- credibility_score: 来源可信度评分，0-100 之间的整数。根据以下规则评估：
  * 官方公告 = 100，监管机构 = 95，交易所公告 = 95
  * 主流财经媒体 = 85，券商研报 = 80，行业媒体 = 70，自媒体 = 40
- freshness_score: 时效性评分，0-1 之间的小数。公式为 e^(-t/24)，t=发布距今小时数。不到1小时为1.0，24小时约0.37，48小时约0.14。
- final_impact_score: 综合影响力，0-10 之间的小数。公式：(impact_score / 10) × (credibility_score / 100) × freshness_score × 10

新闻列表：
---
{news_items}

请直接输出 JSON 数组，不要包含其他任何内容。"""


def format_news_for_prompt(news_list: list[dict]) -> str:
    """将新闻列表格式化为提示词中可读的文本。"""
    parts = []
    for i, news in enumerate(news_list, 1):
        parts.append(
            f"[新闻 {i}]\n"
            f"标题：{news.get('title', '')}\n"
            f"正文：{news.get('content', '')[:500]}\n"
            f"来源：{news.get('source', '')}\n"
            f"时间：{news.get('published_at', '')}\n"
        )
    return "\n".join(parts)


def build_user_prompt(news_list: list[dict]) -> str:
    """构建完整的用户提示词。"""
    news_text = format_news_for_prompt(news_list)
    return USER_PROMPT_TEMPLATE.format(count=len(news_list), news_items=news_text)


# ==================== v3.5 情绪+资金流推荐 ====================

SENTIMENT_FLOW_SYSTEM_PROMPT = """你是一位资深的量化策略分析师，擅长基于市场情绪和资金流向进行股票推荐。
你的分析结合宏观情绪指标、板块轮动信号和个股基本面，给出明确的交易建议。

请严格遵循以下要求：
1. 输出必须是合法的 JSON 数组，不要包含任何 markdown 代码块标记。
2. 每个元素是一个股票推荐对象，字段齐全。
3. 不要添加任何额外的说明文字。
4. 使用中文进行分析和回复。
5. 推荐的股票必须真实存在，代码格式正确（如 600519.SH，000001.SZ，300750.SZ，688981.SH）。
6. 必须覆盖多个板块：主板(600/601/603/000/001/002)、创业板(300/301)、科创板(688)。
7. 每个板块至少推荐 4-5 只股票，总共推荐 20-30 只。尽量多推荐，宁多勿少。
8. 推荐逻辑：看多情绪+资金流入的板块选龙头股和潜力股，看空情绪+资金流出的板块选弱势股。每个板块应同时包含看多和看空标的。
"""

SENTIMENT_FLOW_USER_PROMPT = """你是一位量化策略分析师。请基于以下市场数据，推荐各板块的看多和看空标的。

## 市场情绪总览
- 利好占比: {positive_pct}%
- 中性占比: {neutral_pct}%
- 利空占比: {negative_pct}%
- 净情绪偏向: {net_bias}%（正值=偏乐观，负值=偏悲观）
- 市场温度: {market_temperature}°C（0=极度悲观，100=极度乐观）
- 平均影响力评分: {avg_impact}/10
- 总分析新闻数: {total_analyzed} 条

## 热点行业（按新闻数量排名）
{top_industries}

## 板块轮动信号
{rotation_signals}

## 今日高影响力新闻摘要
{high_impact_news}

## 当前新闻中已识别的关联股票（仅供参考，你可以推荐此列表之外的股票）
{already_mentioned_stocks}

---

请基于以上数据，结合你的市场知识，按以下板块分别推荐看多和看空的股票：

1. **沪市主板** (600/601/603 开头)：推荐 3-4 只看多 + 2-3 只看空
2. **深市主板** (000/001/002 开头)：推荐 3-4 只看多 + 2-3 只看空
3. **创业板** (300/301 开头)：推荐 3-4 只看多 + 2-3 只看空
4. **科创板** (688 开头)：推荐 3-4 只看多 + 2-3 只看空
5. 如有明显的港股机会，补充 2-3 只港股（看多或看空均可）

对每只股票返回以下 JSON 字段：
- name: 股票名称
- code: 股票代码（如 600519.SH）
- board: 所属板块，"沪市主板"/"深市主板"/"创业板"/"科创板"/"港股"
- direction: "看多" 或 "看空"
- confidence: 信心评分 (0-100)，基于情绪和资金流的确定性
- reason: 推荐理由（80 字以内），必须关联具体的情绪指标或资金流向信号
- key_catalyst: 关键催化剂（30 字以内），最核心的驱动事件
- risk_note: 风险提示（30 字以内）

请直接输出 JSON 数组，格式示例：
[
  {{
    "name": "贵州茅台",
    "code": "600519.SH",
    "board": "沪市主板",
    "direction": "看多",
    "confidence": 85,
    "reason": "消费板块情绪回暖，北向资金持续流入白酒板块，茅台作为龙头率先受益",
    "key_catalyst": "消费复苏+北向资金流入",
    "risk_note": "短期涨幅较大注意回调风险"
  }}
]

共推荐 12-20 只股票，确保覆盖至少 4 个板块。
请直接输出 JSON 数组，不要包含其他任何内容。"""


def build_sentiment_flow_prompt(
    sentiment_overview: dict,
    market_temperature: int,
    avg_impact: float,
    total_analyzed: int,
    industry_ranked: list,
    rotation_signals: list,
    high_impact_news: list,
    existing_stocks: list,
) -> str:
    """构建情绪+资金流推荐提示词。"""
    # 热点行业
    top_industries = "\n".join(
        f"- {ind}：{len(news_list)} 条相关新闻"
        for ind, news_list in industry_ranked[:8]
    ) if industry_ranked else "（无）"

    # 轮动信号
    if rotation_signals:
        rotation_text = "\n".join(
            f"- {sig['rotation_detail']}（影响力: {sig.get('impact_score', 'N/A')}/10）"
            for sig in rotation_signals[:5]
        )
    else:
        rotation_text = "（当日无明显板块轮动信号）"

    # 高影响力新闻
    high_impact_text = "\n".join(
        f"- [{news.get('ai_analysis', {}).get('sentiment', '中性')}] {news.get('title', '')}"
        for news in high_impact_news[:5]
    ) if high_impact_news else "（无）"

    # 已识别的股票
    existing_text = "、".join(existing_stocks[:30]) if existing_stocks else "（无）"

    return SENTIMENT_FLOW_USER_PROMPT.format(
        positive_pct=sentiment_overview.get("positive_pct", 0),
        neutral_pct=sentiment_overview.get("neutral_pct", 0),
        negative_pct=sentiment_overview.get("negative_pct", 0),
        net_bias=sentiment_overview.get("net_bias", 0),
        market_temperature=market_temperature,
        avg_impact=avg_impact,
        total_analyzed=total_analyzed,
        top_industries=top_industries,
        rotation_signals=rotation_text,
        high_impact_news=high_impact_text,
        already_mentioned_stocks=existing_text,
    )
