"""新闻去重模块。"""

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 源优先级（数字越小优先级越高）
SOURCE_PRIORITY = {
    "新浪财经": 1,
    "财联社": 2,
    "华尔街见闻": 3,
    "Bloomberg": 4,
    "Reuters": 5,
}


def deduplicate_news(news_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对新闻列表进行去重。

    去重策略：
    1. 相同链接视为重复
    2. 标题相似度高于 90% 视为重复（简单版：归一化后完全匹配）
    3. 重复时保留信息更完整或来源优先级更高的记录
    """
    if not news_list:
        return []

    seen_urls: dict[str, dict] = {}
    seen_titles: dict[str, list[dict]] = {}

    for news in news_list:
        url = (news.get("url") or "").strip()
        title = (news.get("title") or "").strip()

        # URL 去重
        if url:
            existing = seen_urls.get(url)
            if existing:
                keeper = _pick_better(existing, news)
                seen_urls[url] = keeper
                continue
            seen_urls[url] = news

        # 标题归一化去重
        norm_title = _normalize_title(title)
        if norm_title:
            similar_group = seen_titles.get(norm_title, [])
            similar_group.append(news)
            seen_titles[norm_title] = similar_group

    # 对标题相似组做去重
    result: list[dict] = []
    handled: set[str] = set()

    # 先添加 URL 已去重的
    for url, news in seen_urls.items():
        nid = news.get("id", "")
        if nid not in handled:
            result.append(news)
            handled.add(nid)

    # 处理无 URL 但有标题的
    for norm_title, group in seen_titles.items():
        if len(group) <= 1:
            continue

        # 从组中选择最好的
        best = group[0]
        for item in group[1:]:
            best = _pick_better(best, item)

        nid = best.get("id", "")
        if nid not in handled:
            result.append(best)
            handled.add(nid)

    logger.info(
        "去重: %d -> %d (去除 %d 条)",
        len(news_list), len(result), len(news_list) - len(result),
    )
    return result


def _normalize_title(title: str) -> str:
    """归一化标题用于去重比较。"""
    import re
    text = title.strip().lower()
    # 移除标点符号和空格
    text = re.sub(r"[^\u4e00-\u9fff\w]", "", text)
    return text


def _pick_better(a: dict, b: dict) -> dict:
    """在两条重复新闻中挑选信息更完整的一条。"""
    # 1. 比较 content 长度
    a_content = len((a.get("content") or "").strip())
    b_content = len((b.get("content") or "").strip())
    if a_content != b_content:
        return a if a_content > b_content else b

    # 2. 比较来源优先级
    a_prio = SOURCE_PRIORITY.get(a.get("source", ""), 99)
    b_prio = SOURCE_PRIORITY.get(b.get("source", ""), 99)
    if a_prio != b_prio:
        return a if a_prio < b_prio else b

    # 3. 默认保留第一条
    return a
