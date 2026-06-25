import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from ._base import BaseAdapter

logger = logging.getLogger(__name__)

WSCN_ARTICLES_API = "https://api-one.wallstcn.com/apiv1/content/articles"


class WallStreetCNAdapter(BaseAdapter):
    """华尔街见闻新闻适配器。"""

    name = "华尔街见闻"

    def fetch(self, max_items: int) -> list[dict[str, Any]]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://wallstreetcn.com/",
        }

        resp = requests.get(
            WSCN_ARTICLES_API,
            params={"channel": "global", "limit": max_items},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        raw_list = data.get("data", {}).get("items", [])
        if not isinstance(raw_list, list):
            return []

        items = []
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue

            title = (entry.get("title") or "").strip()
            if not title:
                continue

            content = self._clean_content(entry.get("content_short") or "")
            uri = (entry.get("uri") or "").strip()
            url = f"https://wallstreetcn.com/articles/{uri}" if uri else ""

            tags = []
            for t in entry.get("tags", []):
                if isinstance(t, dict):
                    tags.append(t.get("name", ""))
                elif isinstance(t, str):
                    tags.append(t)

            published_at = ""
            dt_val = entry.get("display_time")
            if dt_val:
                try:
                    dt = datetime.fromtimestamp(int(dt_val), tz=timezone(timedelta(hours=8)))
                    published_at = dt.isoformat()
                except (ValueError, TypeError, OSError):
                    pass
            if not published_at:
                published_at = datetime.now(timezone(timedelta(hours=8))).isoformat()

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
    def _clean_content(text: str) -> str:
        if not text:
            return ""
        import re
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
