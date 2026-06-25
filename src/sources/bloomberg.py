import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser

from ._base import BaseAdapter

logger = logging.getLogger(__name__)


class BloombergAdapter(BaseAdapter):
    """Bloomberg 新闻适配器。

    使用 Bloomberg 公开 RSS feed。需要用户配置有效的 feed_url。
    默认不启用。
    """

    name = "Bloomberg"

    def __init__(self, feed_url: str = "https://feeds.bloomberg.com/markets/news.rss"):
        self.feed_url = feed_url

    def fetch(self, max_items: int) -> list[dict[str, Any]]:
        if not self.feed_url:
            logger.warning("[Bloomberg] feed_url 未配置，跳过")
            return []

        feed = feedparser.parse(self.feed_url)
        if feed.bozo and not feed.entries:
            logger.warning("[Bloomberg] RSS 解析失败: %s", feed.bozo_exception)
            return []

        items = []
        for entry in feed.entries[:max_items]:
            title = (entry.get("title") or "").strip()
            if not title:
                continue

            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary or ""
            content = self._clean_html(content)

            url = (entry.get("link") or "").strip()

            # 解析时间
            published_at = ""
            pub_parsed = entry.get("published_parsed")
            if pub_parsed:
                try:
                    import time
                    ts = time.mktime(pub_parsed)
                    dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
                    published_at = dt.isoformat()
                except Exception:
                    pass

            if not published_at:
                published_at = datetime.now(timezone(timedelta(hours=8))).isoformat()

            tags = []
            if hasattr(entry, "tags"):
                tags = [t.get("term", "") for t in entry.tags if t.get("term")]

            items.append({
                "id": self._make_id(url, title),
                "title": title,
                "content": content,
                "published_at": published_at,
                "source": self.name,
                "url": url,
                "tags": tags,
            })

        return items[:max_items]

    @staticmethod
    def _clean_html(text: str) -> str:
        import re
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
