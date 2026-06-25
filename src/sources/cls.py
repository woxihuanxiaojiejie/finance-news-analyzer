import logging, re, requests
from datetime import datetime, timezone, timedelta
from typing import Any
from ._base import BaseAdapter

logger = logging.getLogger(__name__)

CLS_HOME = "https://www.cls.cn/"


class CLSAdapter(BaseAdapter):
    """财联社新闻适配器。

    通过解析财联社首页 HTML 获取新闻列表。
    仅在首页展示的新闻可见，不保证完整覆盖。
    """

    name = "财联社"

    def fetch(self, max_items: int) -> list[dict[str, Any]]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": CLS_HOME,
        }

        resp = requests.get(CLS_HOME, headers=headers, timeout=15)
        resp.raise_for_status()
        text = resp.text

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")

        items = []
        links = soup.find_all("a", href=True)

        for a in links:
            href = a["href"]
            if "/detail/" not in href:
                continue

            title = (a.get("title") or "").strip()
            if not title:
                title = a.get_text(strip=True)
            title = re.sub(r"\s+", " ", title).strip()
            if not title or len(title) < 5:
                continue

            url = href if href.startswith("http") else f"https://www.cls.cn{href}"

            # deduplicate by url
            if any(item["url"] == url for item in items):
                continue

            items.append({
                "id": self._make_id(url, title),
                "title": title,
                "content": "",
                "published_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "source": self.name,
                "url": url,
                "tags": ["财联社"],
            })

            if len(items) >= max_items:
                break

        return items[:max_items]
