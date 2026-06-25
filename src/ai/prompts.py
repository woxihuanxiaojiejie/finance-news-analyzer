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
