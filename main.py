"""T0 数据与分析工作流的唯一总入口。"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

from schema import DATA_DIR, LOG_DIR


def configure_logging():
    Path(LOG_DIR).mkdir(exist_ok=True)
    log_path = Path(LOG_DIR) / f"main_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    logging.info("日志文件：%s", log_path)
    return log_path


def run_import(data_dir=DATA_DIR):
    from database import import_all, initialize_database

    initialize_database()
    inserted = import_all(data_dir)
    logging.info("trade_record 导入完成：新增 %d 行", inserted)
    return inserted


def run_market_environment():
    from market_environment import run_market_environment as update_market

    return update_market()


def run_prepare():
    from prepare import prepare

    return prepare()


def run_algo():
    from analysis_algo import run_analysis

    return run_analysis()


def run_account(account_id):
    from analysis_account import main as analyze_account

    return analyze_account(account_id)


def run_analysis():
    """默认分析只执行全局算法分析；账户分析必须显式指定账户。"""

    return run_algo()


def run_all(data_dir=DATA_DIR):
    run_import(data_dir)
    run_market_environment()
    run_prepare()
    return run_analysis()


def parse_args():
    parser = argparse.ArgumentParser(description="T0 数据准备与分析工作流")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("all", "import", "market", "prepare", "algo"):
        subparsers.add_parser(command)
    account_parser = subparsers.add_parser("account")
    account_parser.add_argument("--account-id", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    configure_logging()
    actions = {
        "all": run_all,
        "import": run_import,
        "market": run_market_environment,
        "prepare": run_prepare,
        "algo": run_algo,
    }
    if args.command == "account":
        return run_account(args.account_id)
    return actions[args.command]()


if __name__ == "__main__":
    main()
