"""DeepSeek API 客户端。"""

import json
import logging
import time
from typing import Any

import requests

from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


def _safe_int(value, min_val: int, max_val: int, default: int) -> int:
    """安全转换整数，限定在 [min_val, max_val] 范围内。"""
    try:
        v = int(value)
        return max(min_val, min(v, max_val))
    except (ValueError, TypeError):
        return default


def _safe_sentiment(value: str) -> str:
    """安全校验情绪值，只允许 利好/中性/利空。"""
    if value in ("利好", "中性", "利空"):
        return value
    v = str(value).strip()
    if "利好" in v or "积极" in v or "positive" in v.lower():
        return "利好"
    if "利空" in v or "消极" in v or "negative" in v.lower():
        return "利空"
    return "中性"


def _safe_trend(value: str) -> str:
    """安全校验趋势值，只允许 短期/中期/长期。"""
    if value in ("短期", "中期", "长期"):
        return value
    v = str(value).strip()
    if "短期" in v or "short" in v.lower():
        return "短期"
    if "长期" in v or "long" in v.lower():
        return "长期"
    return "中期"


class DeepSeekClient:
    """DeepSeek OpenAI 兼容 API 客户端。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        temperature: float = 0.2,
        max_retries: int = 3,
        retry_delay: int = 5,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.chat_url = f"{self.base_url}/v1/chat/completions"

    def analyze_news(
        self, news_batch: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """分析一批新闻，返回每条新闻的 AI 分析结果。

        返回结构：{ "success": bool, "results": list[dict] | None, "error": str | None }
        """
        if not news_batch:
            return {"success": True, "results": [], "error": None}

        user_prompt = build_user_prompt(news_batch)

        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._call_api(user_prompt)
                if result["success"]:
                    parsed = self._parse_result(result["text"], len(news_batch))
                    return {"success": True, "results": parsed, "error": None}

                logger.warning(
                    "AI 调用失败（第 %d/%d 次）: %s",
                    attempt, self.max_retries, result.get("error"),
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

            except Exception:
                logger.exception(
                    "AI 调用异常（第 %d/%d 次）", attempt, self.max_retries
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        return {
            "success": False,
            "results": None,
            "error": f"AI 调用失败，已重试 {self.max_retries} 次",
        }

    def _call_api(self, user_prompt: str) -> dict[str, Any]:
        """调用 API 并返回原始响应文本。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "stream": False,
        }

        resp = requests.post(
            self.chat_url, headers=headers, json=payload, timeout=60
        )
        resp.raise_for_status()
        body = resp.json()

        choices = body.get("choices", [])
        if not choices:
            return {
                "success": False,
                "text": "",
                "error": "API 返回空 choices",
            }

        text = choices[0].get("message", {}).get("content", "").strip()
        if not text:
            return {
                "success": False,
                "text": "",
                "error": "API 返回空内容",
            }

        return {"success": True, "text": text, "error": None}

    def _parse_result(
        self, raw_text: str, expected_count: int
    ) -> list[dict[str, Any]]:
        """解析 AI 返回的 JSON 结果。"""
        text = raw_text.strip()

        # 移除可能的 markdown 代码块标记
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if "```" in text:
                text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            results = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("AI 返回非标准 JSON，尝试修复...")
            results = self._try_fix_json(text)

        if not isinstance(results, list):
            logger.error("AI 返回结果不是数组")
            return []

        # 验证每条结果
        validated = []
        for item in results:
            if isinstance(item, dict):
                # 处理关联股票：可能是字符串数组或对象数组
                related_stocks = item.get("related_stocks", [])
                if isinstance(related_stocks, list):
                    normalized_stocks = []
                    for s in related_stocks:
                        if isinstance(s, dict):
                            normalized_stocks.append({
                                "name": s.get("name", ""),
                                "code": s.get("code", ""),
                            })
                        elif isinstance(s, str):
                            normalized_stocks.append({"name": s, "code": ""})
                    related_stocks = normalized_stocks
                else:
                    related_stocks = []

                validated.append({
                    # 基础分析
                    "summary": item.get("summary", ""),
                    "market_impact": item.get("market_impact", ""),
                    # 定量评估
                    "risk_level": item.get("risk_level", "低"),
                    "risk_reason": item.get("risk_reason", ""),
                    "impact_score": _safe_int(item.get("impact_score", 5), 1, 10, 5),
                    # 情绪与方向
                    "sentiment": _safe_sentiment(item.get("sentiment", "中性")),
                    "sentiment_strength": _safe_int(item.get("sentiment_strength", 5), 1, 10, 5),
                    "bullish_bearish": item.get("bullish_bearish", ""),
                    # 投资关联
                    "related_stocks": related_stocks,
                    "industries": item.get("industries", []),
                    "companies": item.get("companies", []),
                    # 策略信号
                    "sector_rotation": bool(item.get("sector_rotation", False)),
                    "rotation_detail": item.get("rotation_detail", ""),
                    "trend": _safe_trend(item.get("trend", "短期")),
                })
            else:
                validated.append(None)

        # 补齐或截断到预期数量
        while len(validated) < expected_count:
            validated.append(None)

        return validated[:expected_count]

    def recommend_by_sentiment_flow(self, prompt: str) -> dict[str, Any]:
        """基于市场情绪和资金流向推荐股票。

        返回结构：{ "success": bool, "results": list[dict] | None, "error": str | None }
        """
        if not prompt:
            return {"success": True, "results": [], "error": None}

        from .prompts import SENTIMENT_FLOW_SYSTEM_PROMPT

        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._call_api_with_system(SENTIMENT_FLOW_SYSTEM_PROMPT, prompt)
                if result["success"]:
                    parsed = self._parse_sentiment_flow_result(result["text"])
                    return {"success": True, "results": parsed, "error": None}

                logger.warning(
                    "情绪推荐调用失败（第 %d/%d 次）: %s",
                    attempt, self.max_retries, result.get("error"),
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

            except Exception:
                logger.exception(
                    "情绪推荐调用异常（第 %d/%d 次）", attempt, self.max_retries
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        return {
            "success": False,
            "results": None,
            "error": f"情绪推荐调用失败，已重试 {self.max_retries} 次",
        }

    def _call_api_with_system(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """使用自定义 system prompt 调用 API。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "stream": False,
        }

        resp = requests.post(
            self.chat_url, headers=headers, json=payload, timeout=90
        )
        resp.raise_for_status()
        body = resp.json()

        choices = body.get("choices", [])
        if not choices:
            return {"success": False, "text": "", "error": "API 返回空 choices"}

        text = choices[0].get("message", {}).get("content", "").strip()
        if not text:
            return {"success": False, "text": "", "error": "API 返回空内容"}

        return {"success": True, "text": text, "error": None}

    @staticmethod
    def _parse_sentiment_flow_result(raw_text: str) -> list[dict]:
        """解析情绪推荐结果。"""
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if "```" in text:
                text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            results = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("情绪推荐返回非标准 JSON，尝试修复...")
            # Try extracting array
            import re
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    results = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(results, list):
            return []

        validated = []
        valid_directions = {"看多", "看空"}
        for item in results:
            if not isinstance(item, dict):
                continue
            direction = item.get("direction", "")
            if direction not in valid_directions:
                continue
            validated.append({
                "name": item.get("name", ""),
                "code": item.get("code", ""),
                "board": item.get("board", ""),
                "direction": direction,
                "confidence": min(max(int(item.get("confidence", 50)), 0), 100),
                "reason": item.get("reason", ""),
                "key_catalyst": item.get("key_catalyst", ""),
                "risk_note": item.get("risk_note", ""),
            })

        return validated

    @staticmethod
    def _try_fix_json(text: str) -> list:
        """尝试修复常见的 JSON 格式错误。"""
        # 尝试提取 [...] 数组部分
        import re

        # 找第一个 [ 和最后一个 ]
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        return []
