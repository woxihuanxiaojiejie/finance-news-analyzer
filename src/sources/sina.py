import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import requests
from dateutil import parser as dateparser

from ._base import BaseAdapter

logger = logging.getLogger(__name__)

SINA_API = "https://feed.mix.sina.com.cn/api/roll/get"


class SinaAdapter(BaseAdapter):
    """新浪财经新闻适配器。"""

    name = "新浪财经"

    def fetch(self, max_items: int) -> list[dict[str, Any]]:
        params = {
            "pageid": 153,
            "lid": 2516,
            "k": "",
            "num": max_items,
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": "https://finance.sina.com.cn/",
        }

        resp = requests.get(SINA_API, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        items = []
        raw_list = data.get("result", {}).get("data", [])
        if not isinstance(raw_list, list):
            logger.warning("[新浪财经] 返回数据格式异常")
            return []

        for entry in raw_list:
            if not isinstance(entry, dict):
                continue

            title = (entry.get("title") or "").strip()
            if not title:
                continue

            url = (entry.get("url") or "").strip()
            content = (entry.get("content") or "").strip()
            pub_time_str = entry.get("ctime") or entry.get("intime") or ""
            published_at = self._parse_time(pub_time_str)
            tags_raw = entry.get("keyword") or entry.get("keywords") or ""
            tags = [t.strip() for t in tags_raw.replace("，", ",").split(",") if t.strip()]

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
    def _parse_time(time_str: str) -> str:
        if not time_str:
            return datetime.now(timezone(timedelta(hours=8))).isoformat()
        try:
            ts = int(time_str)
            dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
            return dt.isoformat()
        except (ValueError, TypeError):
            pass
        try:
            dt = dateparser.parse(time_str)
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
            return dt.isoformat() if dt else datetime.now(timezone(timedelta(hours=8))).isoformat()
        except Exception:
            return datetime.now(timezone(timedelta(hours=8))).isoformat()
