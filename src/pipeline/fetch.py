"""新闻抓取模块。"""

import logging

from src.sources import ADAPTER_MAP

logger = logging.getLogger(__name__)


def fetch_all_news(config: dict) -> dict[str, list[dict]]:
    """从所有启用的新闻源抓取新闻。

    返回结构: { "success": bool, "sources": { source_name: [news...] }, "errors": [source_names...] }
    """
    sources_config = config.get("sources", {})
    max_total = config.get("run", {}).get("max_total_news", 100)

    all_news: list[dict] = []
    source_results: dict[str, list[dict]] = {}
    errors: list[str] = []

    for source_name, adapter_cls in ADAPTER_MAP.items():
        source_cfg = sources_config.get(source_name, {})
        if not source_cfg.get("enabled", False):
            logger.info("[%s] 未启用，跳过", source_name)
            continue

        max_items = source_cfg.get("max_items", 30)
        adapter = adapter_cls()

        # 对 bloomberg 和 reuters 传入 feed_url
        if source_name in ("bloomberg", "reuters") and source_cfg.get("feed_url"):
            adapter = adapter_cls(feed_url=source_cfg["feed_url"])

        try:
            news = adapter.safe_fetch(max_items)
            source_results[adapter.name] = news
            all_news.extend(news)
            logger.info("[%s] 抓取到 %d 条新闻", adapter.name, len(news))
        except Exception:
            logger.exception("[%s] 抓取异常", adapter.name)
            errors.append(adapter.name)
            source_results[adapter.name] = []

    # 按发布时间排序，最新的在前
    all_news.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    # 限制总数量
    if len(all_news) > max_total:
        all_news = all_news[:max_total]

    return {
        "success": len(errors) == 0,
        "all_news": all_news,
        "sources": source_results,
        "errors": errors,
        "source_stats": {
            name: len(news) for name, news in source_results.items()
        },
    }
