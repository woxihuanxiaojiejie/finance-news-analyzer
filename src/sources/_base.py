import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """所有新闻源适配器的基类。"""

    name = "base"

    @abstractmethod
    def fetch(self, max_items: int) -> list[dict[str, Any]]:
        """抓取新闻列表。

        返回的每条记录应包含：
            id:        新闻唯一标识（哈希值）
            title:     标题
            content:   正文（可能为空）
            published_at: 发布时间 (ISO 格式字符串)
            source:    来源名称
            url:       原文链接
            tags:      标签列表
        """
        ...

    def _make_id(self, url: str, title: str) -> str:
        raw = f"{url}|{title}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def safe_fetch(self, max_items: int) -> list[dict[str, Any]]:
        """带异常保护的抓取。"""
        try:
            items = self.fetch(max_items)
            logger.info("[%s] 成功抓取 %d 条新闻", self.name, len(items))
            return items
        except Exception:
            logger.exception("[%s] 抓取失败", self.name)
            return []
