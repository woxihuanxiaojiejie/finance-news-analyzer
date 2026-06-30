"""财经新闻分析器 - 主入口。

每日自动抓取财经新闻，调用 DeepSeek API 分析，生成 HTML 日报。

使用方式：
    python main.py
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

import yaml
from dotenv import load_dotenv

from src.pipeline import (
    fetch_all_news, deduplicate_news, batch_analyze,
    generate_sentiment_flow_recommendations, render_report,
)


def setup_logging(log_dir: str) -> None:
    """配置日志。"""
    os.makedirs(log_dir, exist_ok=True)
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"{today}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_config(config_path: str) -> dict:
    """加载 YAML 配置文件。"""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config or {}


def save_intermediate_data(data: dict, data_dir: str, name: str) -> None:
    """保存中间数据到 data 目录。"""
    try:
        os.makedirs(data_dir, exist_ok=True)
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        filename = f"{name}-{today}.json"
        filepath = os.path.join(data_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.getLogger(__name__).info("中间数据已保存: %s", filepath)
    except Exception:
        logging.getLogger(__name__).exception("保存中间数据失败: %s", name)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="财经新闻分析器")
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="配置文件路径（默认: config.yaml）",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="环境变量文件路径（默认: .env）",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="跳过 AI 分析，仅抓取和去重",
    )
    return parser.parse_args()


def main() -> int:
    """主流程。返回 0 表示成功，非 0 表示失败。"""
    args = parse_args()

    # 确定项目根目录（main.py 所在目录）
    root_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root_dir)

    # 加载配置
    config_path = os.path.join(root_dir, args.config)
    if not os.path.exists(config_path):
        print(f"[ERROR] 配置文件不存在: {config_path}")
        print("请复制 config.yaml 到项目根目录")
        return 1

    config = load_config(config_path)

    # 设置日志
    log_dir = os.path.join(root_dir, config.get("run", {}).get("log_dir", "logs"))
    setup_logging(log_dir)
    logger = logging.getLogger(__name__)

    # 加载环境变量
    env_path = os.path.join(root_dir, args.env)
    if os.path.exists(env_path):
        load_dotenv(env_path)
        logger.info("已加载环境变量文件: %s", env_path)
    else:
        logger.warning(".env 文件不存在: %s", env_path)

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        logger.error("DEEPSEEK_API_KEY 未设置")
        print("[ERROR] DEEPSEEK_API_KEY 未设置")
        print("请创建 .env 文件并在其中添加: DEEPSEEK_API_KEY=your_api_key")
        return 1

    logger.info("=" * 50)
    logger.info("财经新闻分析器启动")
    logger.info("=" * 50)

    # 配置目录
    data_dir = os.path.join(root_dir, config.get("run", {}).get("data_dir", "data"))
    output_dir = os.path.join(root_dir, config.get("run", {}).get("output_dir", "reports"))
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: 抓取新闻
    logger.info("阶段 1/4: 抓取新闻...")
    fetch_result = fetch_all_news(config)
    all_news = fetch_result["all_news"]
    errors = fetch_result["errors"]
    source_stats = fetch_result["source_stats"]
    logger.info("抓取完成：共 %d 条新闻", len(all_news))

    save_intermediate_data(all_news, data_dir, "raw-news")

    if not all_news:
        logger.warning("未抓取到任何新闻，生成空报告")

    # Step 2: 去重
    logger.info("阶段 2/4: 新闻去重...")
    deduped_news = deduplicate_news(all_news)
    save_intermediate_data(deduped_news, data_dir, "deduped-news")

    # Step 3: AI 分析
    logger.info("阶段 3/5: AI 分析...")
    if args.skip_ai:
        logger.info("已跳过 AI 分析")
        for news in deduped_news:
            news["ai_analysis"] = None
        sentiment_flow_recs = []
    else:
        ai_config = config.get("ai", {})
        analyzed_news = batch_analyze(deduped_news, ai_config, api_key, data_dir)
        save_intermediate_data(analyzed_news, data_dir, "analyzed-news")

        # Step 3.5: 情绪+资金流推荐 (v3.5)
        logger.info("阶段 3.5/5: 情绪+资金流推荐...")
        sentiment_flow_recs = generate_sentiment_flow_recommendations(
            deduped_news, ai_config, api_key, data_dir,
        )

    # Step 4: 生成报告
    logger.info("阶段 4/5: 生成 HTML 报告...")
    report_config = config.get("report", {})
    report_path = render_report(
        deduped_news, report_config, output_dir,
        source_stats=source_stats, errors=errors,
        sentiment_flow_recs=sentiment_flow_recs,
    )

    analyzed_count = sum(1 for n in deduped_news if n.get('ai_analysis'))
    failed_count = sum(1 for n in deduped_news if n.get('ai_error'))
    skipped_count = len(deduped_news) - analyzed_count - failed_count

    logger.info("=" * 50)
    logger.info("完成！")
    logger.info("报告路径: %s", report_path)
    logger.info("=" * 50)

    print(f"\n[DONE] 财经新闻分析日报已生成")
    print(f"   报告: {report_path}")
    print(f"   新闻总数: {len(deduped_news)}")
    print(f"   成功分析: {analyzed_count}")
    if failed_count:
        print(f"   分析失败: {failed_count}")
    if skipped_count:
        print(f"   分析跳过: {skipped_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
