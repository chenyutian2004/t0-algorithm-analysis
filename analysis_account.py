"""
analysis_demo.py

单账户近5个交易日交易表现分析。

分析逻辑：

1. 读取 analysis_record
2. 确定最近5个交易日
3. 输入 account_id，筛选账户交易
4. 按算法分析账户表现
5. 后续按照 Benchmark A1 /A2 / B1 / B2 分组

核心指标：
    1. 盈亏额比
    2. 胜负比
    3. 平均盈亏
    4. 收益率

最终报告同时保留：

    weighted_*
        各组结果按照账户组内交易额加权

    overall_*
        将所有交易合并后直接计算的总体结果
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from schema import DB_PATH


# ==========================================================
# 配置
# ==========================================================

REPORT_DIR = Path("report")
REPORT_DIR.mkdir(exist_ok=True)

LOG_DIR = Path("log")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = (
    LOG_DIR
    / f"analysis_demo_{datetime.now():%Y%m%d_%H%M%S}.log"
)

BENCHMARK_CONFIGS = {

    "a1": {

        "group_cols": [
            "trade_date",
            "market_value_group",
            "actual_position_group",
        ],

        "algorithm_compare": False,
    },

    "a2": {

        "group_cols": [
            "trade_date",
            "market_value_group",
            "actual_position_group",
        ],

        "algorithm_compare": True,
    },

    "b1": {

        "group_cols": [
            "trade_date",
            "stock_code",
        ],

        "algorithm_compare": False,
    },

    "b2": {

        "group_cols": [
            "trade_date",
            "stock_code",
        ],

        "algorithm_compare": True,
    },
}


# ==========================================================
# 日志
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(
            LOG_FILE,
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)


# ==========================================================
# 数据读取
# ==========================================================

def load_analysis_record():
    """
    从 SQLite 读取 analysis_record。

    注意：
    analysis_record 已经经过 prepare.py 处理，
    analysis_demo 不重复执行 Prepare。
    """

    logging.info(
        "开始读取 analysis_record：%s",
        DB_PATH
    )

    if not Path(DB_PATH).exists():
        raise FileNotFoundError(
            f"数据库不存在：{DB_PATH}"
        )

    conn = sqlite3.connect(DB_PATH)

    try:

        # 检查表
        tables = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            """,
            conn
        )

        if "analysis_record" not in (
            tables["name"].tolist()
        ):
            raise RuntimeError(
                "数据库中不存在 analysis_record，"
                "请先运行 prepare.py"
            )

        df = pd.read_sql_query(
            """
            SELECT *
            FROM analysis_record
            """,
            conn
        )

    finally:

        conn.close()

    # ------------------------------------------------------
    # 类型统一
    # ------------------------------------------------------

    df["trade_date"] = pd.to_datetime(
        df["trade_date"],
        errors="coerce"
    )

    numeric_cols = [
        "trade_progress",
        "buy_amount",
        "buy_price",
        "sell_amount",
        "sell_price",
        "turnover",
        "market_value",
        "profit",
        "return_rate",
    ]

    for col in numeric_cols:

        if col in df.columns:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    logging.info(
        "analysis_record 读取完成：%d 行 × %d 列",
        len(df),
        len(df.columns)
    )

    return df


# ==========================================================
# 最近5个交易日
# ==========================================================

def get_recent_trade_dates(
    df: pd.DataFrame,
    n: int = 5
):
    """
    获取 analysis_record 中最近 n 个实际交易日。

    不使用自然日。
    """

    dates = (
        df["trade_date"]
        .dropna()
        .drop_duplicates()
        .sort_values()
    )

    if dates.empty:
        raise RuntimeError(
            "analysis_record 中不存在有效交易日期"
        )

    return dates.tail(n).tolist()


# ==========================================================
# 账户数据
# ==========================================================

def get_account_data(
    df: pd.DataFrame,
    account_id,
    recent_dates
):
    """
    获取指定账户在最近交易日中的数据。
    """

    account_id = str(account_id)

    result = df[
        (df["account_id"].astype(str) == account_id)
        & (df["trade_date"].isin(recent_dates))
    ].copy()

    if result.empty:
        raise ValueError(
            f"账户 {account_id} "
            f"在最近 {len(recent_dates)} 个交易日内没有交易数据"
        )

    return result


# ==========================================================
# 核心指标
# ==========================================================

def calculate_profit_loss_ratio(
    df: pd.DataFrame
):
    """
    盈亏额比：

        盈利金额之和
        ----------------
        亏损金额绝对值之和

    Profit > 0：盈利
    Profit < 0：亏损
    Profit = 0：不计入盈亏两侧
    """

    profit = pd.to_numeric(
        df["profit"],
        errors="coerce"
    ).dropna()

    if profit.empty:
        return None

    positive = profit[profit > 0].sum()

    negative = -profit[profit < 0].sum()

    if negative == 0:

        if positive > 0:
            return None

        return None

    return float(
        positive / negative
    )


def calculate_win_loss_ratio(
    df: pd.DataFrame
):
    """
    胜负比：

        盈利交易笔数
        --------------
        亏损交易笔数

    Profit = 0 不计入胜负。
    """

    profit = pd.to_numeric(
        df["profit"],
        errors="coerce"
    ).dropna()

    win_count = int(
        (profit > 0).sum()
    )

    loss_count = int(
        (profit < 0).sum()
    )

    if loss_count == 0:

        if win_count > 0:
            return None

        return None

    return float(
        win_count / loss_count
    )

def performance_direction(value):
    """
    根据“账户 - Benchmark”的差值判断表现方向。
    """

    if value is None:
        return None

    if value > 0:
        return "better"

    if value < 0:
        return "worse"

    return "equal"


def calculate_basic_metrics(
    df: pd.DataFrame
):
    """
    计算一组交易的基础表现指标。

    指标：

    1. total_trade_count
        交易总数

    2. win_trade_count
        盈利交易数

    3. loss_trade_count
        亏损交易数

    4. zero_profit_trade_count
        盈亏为0的交易数

    5. total_profit
        盈亏额，即所有交易 profit 之和

    6. total_win_profit
        盈利交易盈亏额之和

    7. total_loss_profit
        亏损交易盈亏额之和，保持负数

    8. profit_loss_ratio
        盈亏额比

    9. win_loss_ratio
        胜负比

    10. average_profit
        平均单笔盈亏

    11. average_return_rate
        平均收益率
    """

    if df.empty:

        return {
            "total_trade_count": 0,
            "win_trade_count": 0,
            "loss_trade_count": 0,
            "zero_profit_trade_count": 0,

            "total_profit": 0.0,
            "total_win_profit": 0.0,
            "total_loss_profit": 0.0,

            "profit_loss_ratio": None,
            "win_loss_ratio": None,

            "average_profit": None,
            "average_return_rate": None,
        }

    profit = pd.to_numeric(
        df["profit"],
        errors="coerce"
    )

    return_rate = pd.to_numeric(
        df["return_rate"],
        errors="coerce"
    )

    valid_profit = profit.dropna()

    # ------------------------------------------------------
    # 交易数量
    # ------------------------------------------------------

    total_trade_count = int(
        len(df)
    )

    win_trade_count = int(
        (valid_profit > 0).sum()
    )

    loss_trade_count = int(
        (valid_profit < 0).sum()
    )

    zero_profit_trade_count = int(
        (valid_profit == 0).sum()
    )

    # ------------------------------------------------------
    # 盈亏额
    # ------------------------------------------------------

    total_profit = float(
        valid_profit.sum()
    )

    total_win_profit = float(
        valid_profit[
            valid_profit > 0
        ].sum()
    )

    total_loss_profit = float(
        valid_profit[
            valid_profit < 0
        ].sum()
    )

    # ------------------------------------------------------
    # 盈亏额比
    # ------------------------------------------------------

    if total_loss_profit < 0:

        profit_loss_ratio = float(
            total_win_profit
            / abs(total_loss_profit)
        )

    else:

        profit_loss_ratio = None

    # ------------------------------------------------------
    # 胜负比
    # ------------------------------------------------------

    if loss_trade_count > 0:

        win_loss_ratio = float(
            win_trade_count
            / loss_trade_count
        )

    else:

        win_loss_ratio = None

    # ------------------------------------------------------
    # 平均盈亏
    # ------------------------------------------------------

    average_profit = float(
        valid_profit.mean()
    ) if not valid_profit.empty else None

    # ------------------------------------------------------
    # 平均收益率
    # ------------------------------------------------------

    valid_return_rate = (
        return_rate.dropna()
    )

    average_return_rate = (
        float(valid_return_rate.mean())
        if not valid_return_rate.empty
        else None
    )

    return {

        # ==================================================
        # 交易数量
        # ==================================================

        "total_trade_count":
            total_trade_count,

        "win_trade_count":
            win_trade_count,

        "loss_trade_count":
            loss_trade_count,

        "zero_profit_trade_count":
            zero_profit_trade_count,

        # ==================================================
        # 盈亏额
        # ==================================================

        "total_profit":
            total_profit,

        "total_win_profit":
            total_win_profit,

        "total_loss_profit":
            total_loss_profit,

        # ==================================================
        # 核心指标
        # ==================================================

        "profit_loss_ratio":
            profit_loss_ratio,

        "win_loss_ratio":
            win_loss_ratio,

        # ==================================================
        # 辅助指标
        # ==================================================

        "average_profit":
            average_profit,

        "average_return_rate":
            average_return_rate,
    }


# ==========================================================
# 交易额
# ==========================================================

def calculate_turnover(
    df: pd.DataFrame
):
    """
    计算交易额。

    使用 analysis_record 中的 turnover。
    """

    turnover = pd.to_numeric(
        df["turnover"],
        errors="coerce"
    )

    turnover = turnover.dropna()

    if turnover.empty:
        return 0.0

    return float(
        turnover.sum()
    )


# ==========================================================
# JSON 转换
# ==========================================================

def json_convert(obj):
    """
    JSON 序列化辅助函数。
    """

    if obj is None:
        return None

    if isinstance(obj, (np.integer,)):
        return int(obj)

    if isinstance(obj, (np.floating,)):

        value = float(obj)

        if not np.isfinite(value):
            return None

        return value

    if isinstance(obj, float):

        if not np.isfinite(obj):
            return None

        return obj

    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    if isinstance(obj, Path):
        return str(obj)

    if isinstance(obj, pd.Series):
        return obj.to_dict()

    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(
            orient="records"
        )

    if pd.isna(obj):
        return None

    raise TypeError(
        f"无法JSON序列化：{type(obj).__name__}"
    )

# ==========================================================
# Benchmark 通用：单组计算
# ==========================================================

def calculate_benchmark_groups(
    account_df: pd.DataFrame,
    full_df: pd.DataFrame,
    group_cols,
):
    """
    根据指定分组条件，计算 Benchmark 单组结果。

    参数：
        account_df
            指定账户在最近5个交易日内的数据。

        full_df
            最近5个交易日全部账户的数据。

        group_cols
            Benchmark 环境分组字段。

    例如：

        A1 / A2：
            [
                "trade_date",
                "market_value_group",
                "actual_position_group",
            ]

        B1 / B2：
            [
                "trade_date",
                "stock_code",
            ]

    注意：

        group_cols 只定义“环境”。

        是否进一步按照 algo_type 拆分，
        由上层分析逻辑决定。

    返回：
        每一个环境组对应：

            {
                group_cols...,

                "account": {
                    ...
                },

                "benchmark": {
                    ...
                }
            }
    """

    results = []

    # ======================================================
    # 1. 按环境分组
    # ======================================================

    grouped = account_df.groupby(
        group_cols,
        dropna=False
    )

    # ======================================================
    # 2. 逐组计算
    # ======================================================

    for group_key, account_group_df in grouped:

        # --------------------------------------------------
        # groupby 单列时，统一转成 tuple
        # --------------------------------------------------

        if not isinstance(group_key, tuple):
            group_key = (group_key,)

        group_values = dict(
            zip(
                group_cols,
                group_key
            )
        )

        # --------------------------------------------------
        # 3. 找到 Benchmark 对应环境
        # --------------------------------------------------

        benchmark_group_df = full_df.copy()

        for col, value in group_values.items():

            if pd.isna(value):

                benchmark_group_df = (
                    benchmark_group_df[
                        benchmark_group_df[col].isna()
                    ]
                )

            else:

                benchmark_group_df = (
                    benchmark_group_df[
                        benchmark_group_df[col]
                        == value
                    ]
                )

        # --------------------------------------------------
        # 4. 基础指标
        # --------------------------------------------------

        account_metrics = (
            calculate_basic_metrics(
                account_group_df
            )
        )

        benchmark_metrics = (
            calculate_basic_metrics(
                benchmark_group_df
            )
        )

        # --------------------------------------------------
        # 5. 交易额
        # --------------------------------------------------

        account_turnover = (
            calculate_turnover(
                account_group_df
            )
        )

        benchmark_turnover = (
            calculate_turnover(
                benchmark_group_df
            )
        )

        # --------------------------------------------------
        # 6. 保存
        # --------------------------------------------------

        result = dict(group_values)

        result["account"] = {

            "record_count":
                int(len(account_group_df)),

            "turnover":
                account_turnover,

            **account_metrics,
        }

        result["benchmark"] = {

            "record_count":
                int(len(benchmark_group_df)),

            "turnover":
                benchmark_turnover,

            **benchmark_metrics,
        }

        results.append(result)

    return results

# ==========================================================
# Benchmark：环境组内算法拆分
# ==========================================================

def calculate_algorithm_benchmark_groups(
    account_df: pd.DataFrame,
    full_df: pd.DataFrame,
    environment_groups,
    environment_cols,
):
    """
    在 Benchmark 环境组内部进一步按照 algo_type 拆分。

    用于：

        A2：
            日期 + 市值组 + 底仓组
            → 不同算法

        B2：
            日期 + 股票
            → 不同算法

    参数
    ----
    account_df:
        当前账户最近5个交易日的数据。

    full_df:
        最近5个交易日全部交易数据。

    environment_groups:
        calculate_benchmark_groups() 生成的环境组。

    environment_cols:
        环境控制变量，例如：

        A2：
            [
                "trade_date",
                "market_value_group",
                "actual_position_group",
            ]

        B2：
            [
                "trade_date",
                "stock_code",
            ]

    核心逻辑
    --------
    对每一个账户实际经历的环境：

        1. 找到该环境下全部交易
        2. 找到该环境下实际出现的全部算法
        3. 对每一个算法分别计算：

            account
                = 账户在该环境 + 该算法下的交易

            benchmark
                = 全部交易中该环境 + 该算法的交易

    特殊情况
    --------
    如果账户在某环境中没有使用某算法：

        account = None

    但：

        benchmark
            = 该环境下该算法的全部交易

    这样可以支持：

        账户实际算法
        vs
        同一交易环境下其他算法

    注意
    ----
    本函数只负责“拆组”。

    不负责：

        - 交易额权重
        - Weighted 指标
        - Overall 指标
        - Difference

    这些统一由后续聚合函数完成。
    """

    results = []

    if not environment_groups:
        return results

    # ======================================================
    # 1. 遍历每一个环境组
    # ======================================================

    for environment in environment_groups:

        # --------------------------------------------------
        # 当前环境条件
        # --------------------------------------------------

        environment_values = {
            col: environment.get(col)
            for col in environment_cols
        }

        # --------------------------------------------------
        # 2. 找到该环境下全部交易
        # --------------------------------------------------

        environment_df = full_df.copy()

        for col, value in environment_values.items():

            if pd.isna(value):

                environment_df = (
                    environment_df[
                        environment_df[col].isna()
                    ]
                )

            else:

                environment_df = (
                    environment_df[
                        environment_df[col] == value
                    ]
                )

        # --------------------------------------------------
        # 3. 找到账户在该环境中的交易
        # --------------------------------------------------

        account_environment_df = account_df.copy()

        for col, value in environment_values.items():

            if pd.isna(value):

                account_environment_df = (
                    account_environment_df[
                        account_environment_df[col].isna()
                    ]
                )

            else:

                account_environment_df = (
                    account_environment_df[
                        account_environment_df[col] == value
                    ]
                )

        # --------------------------------------------------
        # 4. 找到该环境中的全部算法
        #
        # 注意：
        # 使用 full_df，而不是 account_df。
        #
        # 这样账户没有使用的算法，
        # 仍然可以作为 Benchmark 出现。
        # --------------------------------------------------

        algorithms = (
            environment_df["algo_type"]
            .drop_duplicates()
            .tolist()
        )

        algorithm_results = {}

        # ==================================================
        # 5. 逐算法计算
        # ==================================================

        for algo in algorithms:

            algo_name = (
                str(algo)
                if pd.notna(algo)
                else "UNKNOWN"
            )

            # --------------------------------------------------
            # Benchmark：
            #
            # 相同环境 + 当前算法
            # --------------------------------------------------

            benchmark_algo_df = (
                environment_df[
                    environment_df["algo_type"] == algo
                ]
                .copy()
            )

            benchmark_metrics = (
                calculate_basic_metrics(
                    benchmark_algo_df
                )
            )

            benchmark_turnover = (
                calculate_turnover(
                    benchmark_algo_df
                )
            )

            # --------------------------------------------------
            # Account：
            #
            # 相同环境 + 当前算法
            # --------------------------------------------------

            account_algo_df = (
                account_environment_df[
                    account_environment_df["algo_type"] == algo
                ]
                .copy()
            )

            if account_algo_df.empty:

                account_metrics = None
                account_turnover = None

            else:

                account_metrics = (
                    calculate_basic_metrics(
                        account_algo_df
                    )
                )

                account_turnover = (
                    calculate_turnover(
                        account_algo_df
                    )
                )

            # --------------------------------------------------
            # 保存
            # --------------------------------------------------

            algorithm_results[algo_name] = {

                "account": {

                    "has_trades":
                        not account_algo_df.empty,

                    "turnover":
                        account_turnover,

                    **(
                        account_metrics
                        if account_metrics is not None
                        else {}
                    ),
                },

                "benchmark": {

                    "record_count":
                        int(
                            len(
                                benchmark_algo_df
                            )
                        ),

                    "turnover":
                        benchmark_turnover,

                    **benchmark_metrics,
                },
            }

        # ==================================================
        # 6. 保存环境组
        # ==================================================

        result = dict(
            environment_values
        )

        # --------------------------------------------------
        # 环境整体账户交易额
        #
        # 后续 A2 权重使用：
        #
        #     账户该环境总交易额
        #     ------------------
        #     账户全部环境总交易额
        #
        # 而不是某个算法自己的交易额。
        #
        # 这样不同算法面对完全相同的环境权重。
        # --------------------------------------------------

        result["account"] = {

            "record_count":
                int(
                    len(
                        account_environment_df
                    )
                ),

            "turnover":
                calculate_turnover(
                    account_environment_df
                ),
        }

        result["algorithms"] = (
            algorithm_results
        )

        results.append(result)

    return results

def weighted_average(
    values,
    weights
):
    """
    按权重计算加权平均。

    自动忽略：
    - None
    - NaN
    - 权重 <= 0
    """

    valid = []

    for value, weight in zip(
        values,
        weights
    ):

        if value is None:
            continue

        if weight is None:
            continue

        try:
            value = float(value)
            weight = float(weight)
        except (TypeError, ValueError):
            continue

        if not np.isfinite(value):
            continue

        if not np.isfinite(weight):
            continue

        if weight <= 0:
            continue

        valid.append(
            (value, weight)
        )

    if not valid:
        return None

    total_weight = sum(
        weight
        for _, weight in valid
    )

    if total_weight <= 0:
        return None

    return float(
        sum(
            value * weight
            for value, weight in valid
        )
        / total_weight
    )


def calculate_group_weights(
    group_results
):
    """
    计算各组在账户该算法中的交易额权重。

    权重：

        账户该组交易额
        ----------------
        账户该算法总交易额
    """

    total_turnover = sum(
        float(
            group["account"]["turnover"]
        )
        for group in group_results
        if group["account"]["turnover"] is not None
    )

    if total_turnover <= 0:

        for group in group_results:
            group["account"]["turnover_weight"] = None

        return group_results

    for group in group_results:

        turnover = float(
            group["account"]["turnover"]
            or 0
        )

        group["account"][
            "turnover_weight"
        ] = float(
            turnover / total_turnover
        )

    return group_results

# ==========================================================
# Benchmark 通用聚合：A1 / B1
# ==========================================================

def aggregate_benchmark(
    account_df: pd.DataFrame,
    benchmark_groups,
    full_df: pd.DataFrame,
    group_cols,
):
    """
    通用 Benchmark 聚合函数。

    用于：

        A1：
            日期 + 市值组 + 底仓组

        B1：
            日期 + 股票

    benchmark_groups 中每个元素结构：

        {
            group_col_1: ...,
            group_col_2: ...,

            "account": {
                ...
            },

            "benchmark": {
                ...
            }
        }

    ------------------------------------------------------
    Weighted
    ------------------------------------------------------

    权重统一为：

        账户该环境组交易额
        ------------------
        账户全部环境组交易额

    Benchmark 与账户使用完全相同的环境权重。

    ------------------------------------------------------
    盈亏额比
    ------------------------------------------------------

        加权盈利额
        ----------------
        加权亏损额绝对值

    而不是：

        Σ(组盈亏额比 × 权重)

    ------------------------------------------------------
    胜负比
    ------------------------------------------------------

        加权胜数
        ----------------
        加权负数

    ------------------------------------------------------
    Overall
    ------------------------------------------------------

    Account：

        account_df 全部交易直接计算。

    Benchmark：

        full_df 中所有“账户实际环境组”
        对应的交易合并后直接计算。

    ------------------------------------------------------
    参数 group_cols
    ------------------------------------------------------

    仅用于从 full_df 构造 Overall Benchmark。

    """

    if not benchmark_groups:

        return {}

    # ======================================================
    # 1. 计算账户环境组权重
    # ======================================================

    total_turnover = sum(
        float(
            group["account"]["turnover"]
            or 0.0
        )
        for group in benchmark_groups
    )

    if total_turnover > 0:

        for group in benchmark_groups:

            turnover = float(
                group["account"]["turnover"]
                or 0.0
            )

            group["account"][
                "turnover_weight"
            ] = (
                turnover
                / total_turnover
            )

    else:

        for group in benchmark_groups:

            group["account"][
                "turnover_weight"
            ] = None

    weights = [
        group["account"]["turnover_weight"]
        for group in benchmark_groups
    ]

    # ======================================================
    # 2. 通用：加权比率
    # ======================================================

    def weighted_ratio(
        side,
        numerator_col,
        denominator_col,
    ):
        weighted_numerator = 0.0
        weighted_denominator = 0.0

        for group in benchmark_groups:

            weight = (
                group["account"][
                    "turnover_weight"
                ]
            )

            if weight is None:
                continue

            weight = float(weight)

            data = group[side]

            numerator = float(
                data.get(
                    numerator_col,
                    0.0
                )
                or 0.0
            )

            denominator = float(
                data.get(
                    denominator_col,
                    0.0
                )
                or 0.0
            )

            weighted_numerator += (
                numerator
                * weight
            )

            weighted_denominator += (
                denominator
                * weight
            )

        if weighted_denominator == 0:

            return None

        return float(
            weighted_numerator
            /
            weighted_denominator
        )

    # ======================================================
    # 3. Weighted：盈亏额比
    # ======================================================

    weighted_account_profit_loss_ratio = (
        weighted_ratio(
            "account",
            "total_win_profit",
            "_weighted_loss_profit",
        )
    )

    weighted_benchmark_profit_loss_ratio = (
        weighted_ratio(
            "benchmark",
            "total_win_profit",
            "_weighted_loss_profit",
        )
    )

    # ------------------------------------------------------
    # 注意：
    # total_loss_profit 本身保持负数。
    #
    # 所以不能直接作为 denominator。
    # ------------------------------------------------------

    def weighted_profit_loss_ratio(
        side
    ):

        weighted_win = 0.0
        weighted_loss = 0.0

        for group in benchmark_groups:

            weight = (
                group["account"][
                    "turnover_weight"
                ]
            )

            if weight is None:
                continue

            data = group[side]

            weighted_win += (
                float(
                    data.get(
                        "total_win_profit",
                        0.0
                    )
                    or 0.0
                )
                * weight
            )

            weighted_loss += (
                abs(
                    float(
                        data.get(
                            "total_loss_profit",
                            0.0
                        )
                        or 0.0
                    )
                )
                * weight
            )

        if weighted_loss == 0:
            return None

        return float(
            weighted_win
            / weighted_loss
        )

    weighted_account_profit_loss_ratio = (
        weighted_profit_loss_ratio(
            "account"
        )
    )

    weighted_benchmark_profit_loss_ratio = (
        weighted_profit_loss_ratio(
            "benchmark"
        )
    )

    # ======================================================
    # 4. Weighted：胜负比
    # ======================================================

    def weighted_win_loss_ratio(
        side
    ):

        weighted_win = 0.0
        weighted_loss = 0.0

        for group in benchmark_groups:

            weight = (
                group["account"][
                    "turnover_weight"
                ]
            )

            if weight is None:
                continue

            data = group[side]

            weighted_win += (
                float(
                    data.get(
                        "win_trade_count",
                        0
                    )
                    or 0
                )
                * weight
            )

            weighted_loss += (
                float(
                    data.get(
                        "loss_trade_count",
                        0
                    )
                    or 0
                )
                * weight
            )

        if weighted_loss == 0:
            return None

        return float(
            weighted_win
            / weighted_loss
        )

    weighted_account_win_loss_ratio = (
        weighted_win_loss_ratio(
            "account"
        )
    )

    weighted_benchmark_win_loss_ratio = (
        weighted_win_loss_ratio(
            "benchmark"
        )
    )

    # ======================================================
    # 5. Weighted：平均盈亏
    # ======================================================

    weighted_account_average_profit = (
        weighted_average(
            [
                group["account"].get(
                    "average_profit"
                )
                for group in benchmark_groups
            ],
            weights
        )
    )

    weighted_benchmark_average_profit = (
        weighted_average(
            [
                group["benchmark"].get(
                    "average_profit"
                )
                for group in benchmark_groups
            ],
            weights
        )
    )

    # ======================================================
    # 6. Weighted：平均收益率
    # ======================================================

    weighted_account_average_return_rate = (
        weighted_average(
            [
                group["account"].get(
                    "average_return_rate"
                )
                for group in benchmark_groups
            ],
            weights
        )
    )

    weighted_benchmark_average_return_rate = (
        weighted_average(
            [
                group["benchmark"].get(
                    "average_return_rate"
                )
                for group in benchmark_groups
            ],
            weights
        )
    )

    # ======================================================
    # 7. Overall Account
    # ======================================================

    overall_account_metrics = (
        calculate_basic_metrics(
            account_df
        )
    )

    overall_account_turnover = (
        calculate_turnover(
            account_df
        )
    )

    # ======================================================
    # 8. Overall Benchmark
    #
    # 根据账户实际出现的环境组，
    # 从 full_df 中取对应全部交易。
    # ======================================================

    benchmark_frames = []

    for group in benchmark_groups:

        mask = pd.Series(
            True,
            index=full_df.index
        )

        for col in group_cols:

            value = group.get(col)

            if pd.isna(value):

                mask &= (
                    full_df[col].isna()
                )

            else:

                mask &= (
                    full_df[col] == value
                )

        benchmark_group_df = (
            full_df[mask].copy()
        )

        if not benchmark_group_df.empty:

            benchmark_frames.append(
                benchmark_group_df
            )

    if benchmark_frames:

        overall_benchmark_df = pd.concat(
            benchmark_frames,
            ignore_index=True
        )

    else:

        overall_benchmark_df = (
            full_df.iloc[0:0].copy()
        )

    overall_benchmark_metrics = (
        calculate_basic_metrics(
            overall_benchmark_df
        )
    )

    overall_benchmark_turnover = (
        calculate_turnover(
            overall_benchmark_df
        )
    )

    # ======================================================
    # 9. Difference
    # ======================================================

    weighted_profit_loss_ratio_difference = (
        None
        if (
            weighted_account_profit_loss_ratio is None
            or
            weighted_benchmark_profit_loss_ratio is None
        )
        else
        (
            weighted_account_profit_loss_ratio
            -
            weighted_benchmark_profit_loss_ratio
        )
    )

    weighted_win_loss_ratio_difference = (
        None
        if (
            weighted_account_win_loss_ratio is None
            or
            weighted_benchmark_win_loss_ratio is None
        )
        else
        (
            weighted_account_win_loss_ratio
            -
            weighted_benchmark_win_loss_ratio
        )
    )

    weighted_average_profit_difference = (
        None
        if (
            weighted_account_average_profit is None
            or
            weighted_benchmark_average_profit is None
        )
        else
        (
            weighted_account_average_profit
            -
            weighted_benchmark_average_profit
        )
    )

    weighted_average_return_rate_difference = (
        None
        if (
            weighted_account_average_return_rate is None
            or
            weighted_benchmark_average_return_rate is None
        )
        else
        (
            weighted_account_average_return_rate
            -
            weighted_benchmark_average_return_rate
        )
    )

    overall_profit_loss_ratio_difference = (
        None
        if (
            overall_account_metrics[
                "profit_loss_ratio"
            ] is None
            or
            overall_benchmark_metrics[
                "profit_loss_ratio"
            ] is None
        )
        else
        (
            overall_account_metrics[
                "profit_loss_ratio"
            ]
            -
            overall_benchmark_metrics[
                "profit_loss_ratio"
            ]
        )
    )

    overall_win_loss_ratio_difference = (
        None
        if (
            overall_account_metrics[
                "win_loss_ratio"
            ] is None
            or
            overall_benchmark_metrics[
                "win_loss_ratio"
            ] is None
        )
        else
        (
            overall_account_metrics[
                "win_loss_ratio"
            ]
            -
            overall_benchmark_metrics[
                "win_loss_ratio"
            ]
        )
    )

    overall_average_profit_difference = (
        None
        if (
            overall_account_metrics[
                "average_profit"
            ] is None
            or
            overall_benchmark_metrics[
                "average_profit"
            ] is None
        )
        else
        (
            overall_account_metrics[
                "average_profit"
            ]
            -
            overall_benchmark_metrics[
                "average_profit"
            ]
        )
    )

    overall_average_return_rate_difference = (
        None
        if (
            overall_account_metrics[
                "average_return_rate"
            ] is None
            or
            overall_benchmark_metrics[
                "average_return_rate"
            ] is None
        )
        else
        (
            overall_account_metrics[
                "average_return_rate"
            ]
            -
            overall_benchmark_metrics[
                "average_return_rate"
            ]
        )
    )

    # ======================================================
    # 10. 返回
    # ======================================================

    return {

        # --------------------------------------------------
        # Weighted
        # --------------------------------------------------

        "weighted_account_profit_loss_ratio":
            weighted_account_profit_loss_ratio,

        "weighted_benchmark_profit_loss_ratio":
            weighted_benchmark_profit_loss_ratio,

        "weighted_profit_loss_ratio_difference":
            weighted_profit_loss_ratio_difference,

        "weighted_account_win_loss_ratio":
            weighted_account_win_loss_ratio,

        "weighted_benchmark_win_loss_ratio":
            weighted_benchmark_win_loss_ratio,

        "weighted_win_loss_ratio_difference":
            weighted_win_loss_ratio_difference,

        "weighted_account_average_profit":
            weighted_account_average_profit,

        "weighted_benchmark_average_profit":
            weighted_benchmark_average_profit,

        "weighted_average_profit_difference":
            weighted_average_profit_difference,

        "weighted_account_average_return_rate":
            weighted_account_average_return_rate,

        "weighted_benchmark_average_return_rate":
            weighted_benchmark_average_return_rate,

        "weighted_average_return_rate_difference":
            weighted_average_return_rate_difference,

        # --------------------------------------------------
        # Overall Account
        # --------------------------------------------------

        "overall_account_total_trade_count":
            overall_account_metrics[
                "total_trade_count"
            ],

        "overall_account_win_trade_count":
            overall_account_metrics[
                "win_trade_count"
            ],

        "overall_account_loss_trade_count":
            overall_account_metrics[
                "loss_trade_count"
            ],

        "overall_account_zero_profit_trade_count":
            overall_account_metrics[
                "zero_profit_trade_count"
            ],

        "overall_account_total_profit":
            overall_account_metrics[
                "total_profit"
            ],

        "overall_account_total_win_profit":
            overall_account_metrics[
                "total_win_profit"
            ],

        "overall_account_total_loss_profit":
            overall_account_metrics[
                "total_loss_profit"
            ],

        "overall_account_profit_loss_ratio":
            overall_account_metrics[
                "profit_loss_ratio"
            ],

        "overall_account_win_loss_ratio":
            overall_account_metrics[
                "win_loss_ratio"
            ],

        "overall_account_average_profit":
            overall_account_metrics[
                "average_profit"
            ],

        "overall_account_average_return_rate":
            overall_account_metrics[
                "average_return_rate"
            ],

        "overall_account_turnover":
            overall_account_turnover,

        # --------------------------------------------------
        # Overall Benchmark
        # --------------------------------------------------

        "overall_benchmark_total_trade_count":
            overall_benchmark_metrics[
                "total_trade_count"
            ],

        "overall_benchmark_win_trade_count":
            overall_benchmark_metrics[
                "win_trade_count"
            ],

        "overall_benchmark_loss_trade_count":
            overall_benchmark_metrics[
                "loss_trade_count"
            ],

        "overall_benchmark_zero_profit_trade_count":
            overall_benchmark_metrics[
                "zero_profit_trade_count"
            ],

        "overall_benchmark_total_profit":
            overall_benchmark_metrics[
                "total_profit"
            ],

        "overall_benchmark_total_win_profit":
            overall_benchmark_metrics[
                "total_win_profit"
            ],

        "overall_benchmark_total_loss_profit":
            overall_benchmark_metrics[
                "total_loss_profit"
            ],

        "overall_benchmark_profit_loss_ratio":
            overall_benchmark_metrics[
                "profit_loss_ratio"
            ],

        "overall_benchmark_win_loss_ratio":
            overall_benchmark_metrics[
                "win_loss_ratio"
            ],

        "overall_benchmark_average_profit":
            overall_benchmark_metrics[
                "average_profit"
            ],

        "overall_benchmark_average_return_rate":
            overall_benchmark_metrics[
                "average_return_rate"
            ],

        "overall_benchmark_turnover":
            overall_benchmark_turnover,

        # --------------------------------------------------
        # Overall Difference
        # --------------------------------------------------

        "overall_profit_loss_ratio_difference":
            overall_profit_loss_ratio_difference,

        "overall_win_loss_ratio_difference":
            overall_win_loss_ratio_difference,

        "overall_average_profit_difference":
            overall_average_profit_difference,

        "overall_average_return_rate_difference":
            overall_average_return_rate_difference,
    }

# ==========================================================
# Benchmark 通用算法聚合：A2 / B2
# ==========================================================

def aggregate_algorithm_benchmark(
    account_df: pd.DataFrame,
    benchmark_groups,
    full_df: pd.DataFrame,
    environment_cols,
):
    """
    通用算法 Benchmark 聚合函数。

    用于：

        A2：
            日期 + 市值组 + 底仓组
            → 比较不同算法

        B2：
            日期 + 股票
            → 比较不同算法

    benchmark_groups 的结构：

        [
            {
                environment_col_1: ...,
                environment_col_2: ...,

                "account": {
                    "turnover": ...
                },

                "algorithms": {

                    "YRT0": {
                        "account": {...},
                        "benchmark": {...}
                    },

                    "KFT0": {
                        "account": {...},
                        "benchmark": {...}
                    }
                }
            }
        ]

    ------------------------------------------------------
    权重
    ------------------------------------------------------

    权重来自：

        账户在该环境组的总交易额
        ----------------------
        账户全部环境组总交易额

    注意：

        不是某个算法自己的交易额。

    因此：

        A2-YRT0
        A2-KFT0
        A2-其他算法

    使用完全相同的环境权重。

    B2 同理。

    ------------------------------------------------------
    未使用算法
    ------------------------------------------------------

    如果账户没有使用某算法：

        account = None / 无指标

    benchmark 仍然保留。

    ------------------------------------------------------
    返回
    ------------------------------------------------------

    {
        "YRT0": {...},
        "KFT0": {...},
        ...
    }
    """

    if not benchmark_groups:
        return {}

    # ======================================================
    # 1. 计算环境组权重
    # ======================================================

    total_turnover = sum(
        float(
            group["account"].get(
                "turnover",
                0.0
            )
            or 0.0
        )
        for group in benchmark_groups
    )

    if total_turnover > 0:

        weights = []

        for group in benchmark_groups:

            turnover = float(
                group["account"].get(
                    "turnover",
                    0.0
                )
                or 0.0
            )

            weight = (
                turnover
                / total_turnover
            )

            group["account"][
                "turnover_weight"
            ] = weight

            weights.append(weight)

    else:

        weights = []

        for group in benchmark_groups:

            group["account"][
                "turnover_weight"
            ] = None

            weights.append(None)

    # ======================================================
    # 2. 收集所有算法
    #
    # 必须来自 Benchmark 环境，而不是账户。
    #
    # 这样账户未使用的算法仍然保留。
    # ======================================================

    all_algorithms = set()

    for group in benchmark_groups:

        all_algorithms.update(
            group.get(
                "algorithms",
                {}
            ).keys()
        )

    algorithm_summaries = {}

    # ======================================================
    # 3. 逐算法聚合
    # ======================================================

    for algo_type in sorted(
        all_algorithms
    ):

        # --------------------------------------------------
        # 当前算法存在的环境组
        # --------------------------------------------------

        algorithm_groups = []

        for group in benchmark_groups:

            algorithm_data = (
                group.get(
                    "algorithms",
                    {}
                ).get(
                    algo_type
                )
            )

            if algorithm_data is None:

                # --------------------------------------------------
                # 该环境中根本没有该算法。
                #
                # 不能创造一个 Benchmark = 0 的虚拟交易组。
                # 这里只跳过该算法组。
                #
                # 但该环境的账户权重仍然存在，
                # 后续 Weighted 时保持统一环境权重。
                # --------------------------------------------------

                algorithm_groups.append(
                    (
                        group,
                        None
                    )
                )

            else:

                algorithm_groups.append(
                    (
                        group,
                        algorithm_data
                    )
                )

        # ==================================================
        # 4. Weighted 指标
        # ==================================================

        weighted_account_win_profit = 0.0
        weighted_account_loss_profit = 0.0

        weighted_benchmark_win_profit = 0.0
        weighted_benchmark_loss_profit = 0.0

        weighted_account_win_count = 0.0
        weighted_account_loss_count = 0.0

        weighted_benchmark_win_count = 0.0
        weighted_benchmark_loss_count = 0.0

        account_average_profit_values = []
        benchmark_average_profit_values = []

        account_average_return_values = []
        benchmark_average_return_values = []

        valid_weights = []

        for group, algorithm_data in algorithm_groups:

            weight = (
                group["account"].get(
                    "turnover_weight"
                )
            )

            if weight is None:
                continue

            weight = float(weight)

            # --------------------------------------------------
            # 该环境没有该算法
            #
            # Benchmark 不存在该算法交易，
            # 因此不能产生该算法指标。
            #
            # 但不能修改环境权重。
            # --------------------------------------------------

            if algorithm_data is None:
                continue

            account = (
                algorithm_data["account"]
            )

            benchmark = (
                algorithm_data["benchmark"]
            )

            valid_weights.append(weight)

            # --------------------------------------------------
            # 盈利 / 亏损额
            # --------------------------------------------------

            weighted_account_win_profit += (
                float(
                    account.get(
                        "total_win_profit",
                        0.0
                    )
                    or 0.0
                )
                * weight
            )

            weighted_account_loss_profit += (
                abs(
                    float(
                        account.get(
                            "total_loss_profit",
                            0.0
                        )
                        or 0.0
                    )
                )
                * weight
            )

            weighted_benchmark_win_profit += (
                float(
                    benchmark.get(
                        "total_win_profit",
                        0.0
                    )
                    or 0.0
                )
                * weight
            )

            weighted_benchmark_loss_profit += (
                abs(
                    float(
                        benchmark.get(
                            "total_loss_profit",
                            0.0
                        )
                        or 0.0
                    )
                )
                * weight
            )

            # --------------------------------------------------
            # 胜负数
            # --------------------------------------------------

            weighted_account_win_count += (
                float(
                    account.get(
                        "win_trade_count",
                        0
                    )
                    or 0
                )
                * weight
            )

            weighted_account_loss_count += (
                float(
                    account.get(
                        "loss_trade_count",
                        0
                    )
                    or 0
                )
                * weight
            )

            weighted_benchmark_win_count += (
                float(
                    benchmark.get(
                        "win_trade_count",
                        0
                    )
                    or 0
                )
                * weight
            )

            weighted_benchmark_loss_count += (
                float(
                    benchmark.get(
                        "loss_trade_count",
                        0
                    )
                    or 0
                )
                * weight
            )

            # --------------------------------------------------
            # 平均盈亏 / 收益率
            # --------------------------------------------------

            account_average_profit_values.append(
                account.get(
                    "average_profit"
                )
            )

            benchmark_average_profit_values.append(
                benchmark.get(
                    "average_profit"
                )
            )

            account_average_return_values.append(
                account.get(
                    "average_return_rate"
                )
            )

            benchmark_average_return_values.append(
                benchmark.get(
                    "average_return_rate"
                )
            )

        # ==================================================
        # 5. Weighted 盈亏额比
        # ==================================================

        if weighted_account_loss_profit > 0:

            weighted_account_profit_loss_ratio = (
                weighted_account_win_profit
                /
                weighted_account_loss_profit
            )

        else:

            weighted_account_profit_loss_ratio = None

        if weighted_benchmark_loss_profit > 0:

            weighted_benchmark_profit_loss_ratio = (
                weighted_benchmark_win_profit
                /
                weighted_benchmark_loss_profit
            )

        else:

            weighted_benchmark_profit_loss_ratio = None

        # ==================================================
        # 6. Weighted 胜负比
        # ==================================================

        if weighted_account_loss_count > 0:

            weighted_account_win_loss_ratio = (
                weighted_account_win_count
                /
                weighted_account_loss_count
            )

        else:

            weighted_account_win_loss_ratio = None

        if weighted_benchmark_loss_count > 0:

            weighted_benchmark_win_loss_ratio = (
                weighted_benchmark_win_count
                /
                weighted_benchmark_loss_count
            )

        else:

            weighted_benchmark_win_loss_ratio = None

        # ==================================================
        # 7. Weighted 平均盈亏
        #
        # 注意：
        # 这里仍然使用账户环境权重。
        #
        # 但某环境不存在该算法时，
        # 该算法在该环境没有 Benchmark，
        # 因此只对实际存在该算法的环境进行加权。
        #
        # 权重不重新归一化。
        # ==================================================

        weighted_account_average_profit = (
            weighted_average(
                account_average_profit_values,
                valid_weights
            )
        )

        weighted_benchmark_average_profit = (
            weighted_average(
                benchmark_average_profit_values,
                valid_weights
            )
        )

        # ==================================================
        # 8. Weighted 平均收益率
        # ==================================================

        weighted_account_average_return_rate = (
            weighted_average(
                account_average_return_values,
                valid_weights
            )
        )

        weighted_benchmark_average_return_rate = (
            weighted_average(
                benchmark_average_return_values,
                valid_weights
            )
        )

        # ==================================================
        # 9. 收集账户该算法全部交易
        # ==================================================

        account_algo_df = account_df[
            account_df["algo_type"].astype(str)
            == str(algo_type)
        ].copy()

        if account_algo_df.empty:

            overall_account_metrics = None
            overall_account_turnover = None

        else:

            overall_account_metrics = (
                calculate_basic_metrics(
                    account_algo_df
                )
            )

            overall_account_turnover = (
                calculate_turnover(
                    account_algo_df
                )
            )

        # ==================================================
        # 10. 构造 Benchmark Overall
        #
        # 固定账户实际环境池，
        # 再取该算法的全部交易。
        # ==================================================

        benchmark_frames = []

        for group in benchmark_groups:

            # --------------------------------------------------
            # 当前环境
            # --------------------------------------------------

            mask = pd.Series(
                True,
                index=full_df.index
            )

            for col in environment_cols:

                value = group.get(col)

                if pd.isna(value):

                    mask &= (
                        full_df[col].isna()
                    )

                else:

                    mask &= (
                        full_df[col] == value
                    )

            # --------------------------------------------------
            # 当前环境 + 当前算法
            # --------------------------------------------------

            mask &= (
                full_df["algo_type"].astype(str)
                == str(algo_type)
            )

            benchmark_df = (
                full_df[mask].copy()
            )

            if not benchmark_df.empty:

                benchmark_frames.append(
                    benchmark_df
                )

        if benchmark_frames:

            overall_benchmark_df = pd.concat(
                benchmark_frames,
                ignore_index=True
            )

        else:

            overall_benchmark_df = (
                full_df.iloc[0:0].copy()
            )

        overall_benchmark_metrics = (
            calculate_basic_metrics(
                overall_benchmark_df
            )
        )

        overall_benchmark_turnover = (
            calculate_turnover(
                overall_benchmark_df
            )
        )

        # ==================================================
        # 11. Weighted Difference
        # ==================================================

        weighted_profit_loss_ratio_difference = (
            None
            if (
                weighted_account_profit_loss_ratio is None
                or
                weighted_benchmark_profit_loss_ratio is None
            )
            else
            (
                weighted_account_profit_loss_ratio
                -
                weighted_benchmark_profit_loss_ratio
            )
        )

        weighted_win_loss_ratio_difference = (
            None
            if (
                weighted_account_win_loss_ratio is None
                or
                weighted_benchmark_win_loss_ratio is None
            )
            else
            (
                weighted_account_win_loss_ratio
                -
                weighted_benchmark_win_loss_ratio
            )
        )

        weighted_average_profit_difference = (
            None
            if (
                weighted_account_average_profit is None
                or
                weighted_benchmark_average_profit is None
            )
            else
            (
                weighted_account_average_profit
                -
                weighted_benchmark_average_profit
            )
        )

        weighted_average_return_rate_difference = (
            None
            if (
                weighted_account_average_return_rate is None
                or
                weighted_benchmark_average_return_rate is None
            )
            else
            (
                weighted_account_average_return_rate
                -
                weighted_benchmark_average_return_rate
            )
        )

        # ==================================================
        # 12. Overall Difference
        # ==================================================

        if overall_account_metrics is None:

            overall_profit_loss_ratio_difference = None
            overall_win_loss_ratio_difference = None
            overall_average_profit_difference = None
            overall_average_return_rate_difference = None

        else:

            overall_profit_loss_ratio_difference = (
                None
                if (
                    overall_account_metrics[
                        "profit_loss_ratio"
                    ] is None
                    or
                    overall_benchmark_metrics[
                        "profit_loss_ratio"
                    ] is None
                )
                else
                (
                    overall_account_metrics[
                        "profit_loss_ratio"
                    ]
                    -
                    overall_benchmark_metrics[
                        "profit_loss_ratio"
                    ]
                )
            )

            overall_win_loss_ratio_difference = (
                None
                if (
                    overall_account_metrics[
                        "win_loss_ratio"
                    ] is None
                    or
                    overall_benchmark_metrics[
                        "win_loss_ratio"
                    ] is None
                )
                else
                (
                    overall_account_metrics[
                        "win_loss_ratio"
                    ]
                    -
                    overall_benchmark_metrics[
                        "win_loss_ratio"
                    ]
                )
            )

            overall_average_profit_difference = (
                None
                if (
                    overall_account_metrics[
                        "average_profit"
                    ] is None
                    or
                    overall_benchmark_metrics[
                        "average_profit"
                    ] is None
                )
                else
                (
                    overall_account_metrics[
                        "average_profit"
                    ]
                    -
                    overall_benchmark_metrics[
                        "average_profit"
                    ]
                )
            )

            overall_average_return_rate_difference = (
                None
                if (
                    overall_account_metrics[
                        "average_return_rate"
                    ] is None
                    or
                    overall_benchmark_metrics[
                        "average_return_rate"
                    ] is None
                )
                else
                (
                    overall_account_metrics[
                        "average_return_rate"
                    ]
                    -
                    overall_benchmark_metrics[
                        "average_return_rate"
                    ]
                )
            )

        # ==================================================
        # 13. 保存算法结果
        # ==================================================

        algorithm_summaries[algo_type] = {

            # --------------------------------------------------
            # Weighted
            # --------------------------------------------------

            "weighted_account_profit_loss_ratio":
                weighted_account_profit_loss_ratio,

            "weighted_benchmark_profit_loss_ratio":
                weighted_benchmark_profit_loss_ratio,

            "weighted_profit_loss_ratio_difference":
                weighted_profit_loss_ratio_difference,

            "weighted_account_win_loss_ratio":
                weighted_account_win_loss_ratio,

            "weighted_benchmark_win_loss_ratio":
                weighted_benchmark_win_loss_ratio,

            "weighted_win_loss_ratio_difference":
                weighted_win_loss_ratio_difference,

            "weighted_account_average_profit":
                weighted_account_average_profit,

            "weighted_benchmark_average_profit":
                weighted_benchmark_average_profit,

            "weighted_average_profit_difference":
                weighted_average_profit_difference,

            "weighted_account_average_return_rate":
                weighted_account_average_return_rate,

            "weighted_benchmark_average_return_rate":
                weighted_benchmark_average_return_rate,

            "weighted_average_return_rate_difference":
                weighted_average_return_rate_difference,

            # --------------------------------------------------
            # Overall Account
            # --------------------------------------------------

            "overall_account_total_trade_count":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "total_trade_count"
                    ]
                ),

            "overall_account_win_trade_count":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "win_trade_count"
                    ]
                ),

            "overall_account_loss_trade_count":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "loss_trade_count"
                    ]
                ),

            "overall_account_zero_profit_trade_count":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "zero_profit_trade_count"
                    ]
                ),

            "overall_account_total_profit":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "total_profit"
                    ]
                ),

            "overall_account_total_win_profit":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "total_win_profit"
                    ]
                ),

            "overall_account_total_loss_profit":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "total_loss_profit"
                    ]
                ),

            "overall_account_profit_loss_ratio":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "profit_loss_ratio"
                    ]
                ),

            "overall_account_win_loss_ratio":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "win_loss_ratio"
                    ]
                ),

            "overall_account_average_profit":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "average_profit"
                    ]
                ),

            "overall_account_average_return_rate":
                (
                    None
                    if overall_account_metrics is None
                    else
                    overall_account_metrics[
                        "average_return_rate"
                    ]
                ),

            "overall_account_turnover":
                overall_account_turnover,

            # --------------------------------------------------
            # Overall Benchmark
            # --------------------------------------------------

            "overall_benchmark_total_trade_count":
                overall_benchmark_metrics[
                    "total_trade_count"
                ],

            "overall_benchmark_win_trade_count":
                overall_benchmark_metrics[
                    "win_trade_count"
                ],

            "overall_benchmark_loss_trade_count":
                overall_benchmark_metrics[
                    "loss_trade_count"
                ],

            "overall_benchmark_zero_profit_trade_count":
                overall_benchmark_metrics[
                    "zero_profit_trade_count"
                ],

            "overall_benchmark_total_profit":
                overall_benchmark_metrics[
                    "total_profit"
                ],

            "overall_benchmark_total_win_profit":
                overall_benchmark_metrics[
                    "total_win_profit"
                ],

            "overall_benchmark_total_loss_profit":
                overall_benchmark_metrics[
                    "total_loss_profit"
                ],

            "overall_benchmark_profit_loss_ratio":
                overall_benchmark_metrics[
                    "profit_loss_ratio"
                ],

            "overall_benchmark_win_loss_ratio":
                overall_benchmark_metrics[
                    "win_loss_ratio"
                ],

            "overall_benchmark_average_profit":
                overall_benchmark_metrics[
                    "average_profit"
                ],

            "overall_benchmark_average_return_rate":
                overall_benchmark_metrics[
                    "average_return_rate"
                ],

            "overall_benchmark_turnover":
                overall_benchmark_turnover,

            # --------------------------------------------------
            # Overall Difference
            # --------------------------------------------------

            "overall_profit_loss_ratio_difference":
                overall_profit_loss_ratio_difference,

            "overall_win_loss_ratio_difference":
                overall_win_loss_ratio_difference,

            "overall_average_profit_difference":
                overall_average_profit_difference,

            "overall_average_return_rate_difference":
                overall_average_return_rate_difference,
        }

    return algorithm_summaries

# ==========================================================
# 第11部分：Benchmark 综合比较
# ==========================================================

def build_benchmark_comparison(
    account_overall,
    benchmark_a1_summary,
    benchmark_a2_algorithm_summaries,
    benchmark_b1_summary,
    benchmark_b2_algorithm_summaries,
):
    """
    构建最终 Benchmark 综合比较表。

    比较对象：

        1. Account
           账户实际表现

        2. Benchmark A1
           日期 + 市值组 + 底仓组
           同股票池整体表现

        3. Benchmark A2 - 各算法
           日期 + 市值组 + 底仓组
           固定账户股票池后，
           分别比较不同算法

        4. Benchmark B1
           日期 + 股票
           同股票池整体表现

        5. Benchmark B2 - 各算法
           日期 + 股票
           固定账户股票池后，
           分别比较不同算法

    ------------------------------------------------------
    最终比较指标
    ------------------------------------------------------

    1. 平均收益率
    2. 平均盈亏额
    3. 盈亏额比
    4. 胜负比

    Benchmark 比较统一采用 Weighted 口径。

    原因：

        Benchmark A1 / A2 / B1 / B2 的 Benchmark
        都可能包含远多于账户自身的交易。

        因此不直接比较 Benchmark 的
        total_profit。

        Weighted 指标按照账户实际交易结构
        对 Benchmark 进行标准化，更适合横向比较。

    ------------------------------------------------------
    Account
    ------------------------------------------------------

    Account 没有 Benchmark 权重，
    因此直接使用账户实际总体指标。

    ------------------------------------------------------
    B2
    ------------------------------------------------------

    每个算法单独作为一行。

    如果账户没有使用该算法：

        account 指标 = None

    Benchmark 指标仍然保留。

    ------------------------------------------------------
    返回
    ------------------------------------------------------

    {
        "metrics": [
            ...
        ]
    }
    """

    rows = []

    # ======================================================
    # 1. Account
    #
    # 账户实际总体表现
    # ======================================================

    rows.append({

        "benchmark":
            "account",

        "benchmark_name":
            "账户实际表现",

        "algorithm":
            None,

        "average_return_rate":
            account_overall.get(
                "average_return_rate"
            ),

        "average_profit":
            account_overall.get(
                "average_profit"
            ),

        "profit_loss_ratio":
            account_overall.get(
                "profit_loss_ratio"
            ),

        "win_loss_ratio":
            account_overall.get(
                "win_loss_ratio"
            ),
    })

    # ======================================================
    # 2. Benchmark A1
    #
    # 同交易环境整体表现
    # ======================================================

    rows.append({

        "benchmark":
            "benchmark_a1",

        "benchmark_name":
            "Benchmark A1：同交易环境整体",

        "algorithm":
            None,

        "average_return_rate":
            benchmark_a1_summary.get(
                "weighted_benchmark_average_return_rate"
            ),

        "average_profit":
            benchmark_a1_summary.get(
                "weighted_benchmark_average_profit"
            ),

        "profit_loss_ratio":
            benchmark_a1_summary.get(
                "weighted_benchmark_profit_loss_ratio"
            ),

        "win_loss_ratio":
            benchmark_a1_summary.get(
                "weighted_benchmark_win_loss_ratio"
            ),
    })

    # ======================================================
    # 3. Benchmark A2
    #
    # 同交易环境 + 不同算法
    # ======================================================

    for algo_type in sorted(
        benchmark_a2_algorithm_summaries.keys()
    ):

        summary = (
            benchmark_a2_algorithm_summaries[
                algo_type
            ]
        )

        rows.append({

            "benchmark":
                "benchmark_a2",

            "benchmark_name":
                "Benchmark A2：同交易环境算法",

            "algorithm":
                algo_type,

            "average_return_rate":
                summary.get(
                    "weighted_benchmark_average_return_rate"
                ),

            "average_profit":
                summary.get(
                    "weighted_benchmark_average_profit"
                ),

            "profit_loss_ratio":
                summary.get(
                    "weighted_benchmark_profit_loss_ratio"
                ),

            "win_loss_ratio":
                summary.get(
                    "weighted_benchmark_win_loss_ratio"
                ),
        })

    # ======================================================
    # 4. Benchmark B1
    #
    # 同股票池整体表现
    # ======================================================

    rows.append({

        "benchmark":
            "benchmark_b1",

        "benchmark_name":
            "Benchmark B1：同股票池整体",

        "algorithm":
            None,

        "average_return_rate":
            benchmark_b1_summary.get(
                "weighted_benchmark_average_return_rate"
            ),

        "average_profit":
            benchmark_b1_summary.get(
                "weighted_benchmark_average_profit"
            ),

        "profit_loss_ratio":
            benchmark_b1_summary.get(
                "weighted_benchmark_profit_loss_ratio"
            ),

        "win_loss_ratio":
            benchmark_b1_summary.get(
                "weighted_benchmark_win_loss_ratio"
            ),
    })

    # ======================================================
    # 5. Benchmark B2
    #
    # 同股票池 + 不同算法
    # ======================================================

    for algo_type in sorted(
        benchmark_b2_algorithm_summaries.keys()
    ):

        summary = (
            benchmark_b2_algorithm_summaries[
                algo_type
            ]
        )

        rows.append({

            "benchmark":
                "benchmark_b2",

            "benchmark_name":
                "Benchmark B2：同股票池算法",

            "algorithm":
                algo_type,

            "average_return_rate":
                summary.get(
                    "weighted_benchmark_average_return_rate"
                ),

            "average_profit":
                summary.get(
                    "weighted_benchmark_average_profit"
                ),

            "profit_loss_ratio":
                summary.get(
                    "weighted_benchmark_profit_loss_ratio"
                ),

            "win_loss_ratio":
                summary.get(
                    "weighted_benchmark_win_loss_ratio"
                ),
        })

    return {

        "metrics":
            rows
    }

def analyze_account_basic(
    df: pd.DataFrame,
    account_id
):
    """
    对指定账户进行近5个交易日分析。

    输出：

        account_overall
            账户整体表现

        benchmark_a
            A1：
            日期 + 市值组 + 底仓组

            A2：
            日期 + 市值组 + 底仓组 + 算法

        benchmark_b
            B1：
            日期 + 股票

            B2：
            日期 + 股票 + 算法

        benchmark_comparison
            下一阶段生成。
    """

    # ======================================================
    # 1. 最近5个交易日
    # ======================================================

    recent_dates = get_recent_trade_dates(
        df,
        n=5
    )

    # ======================================================
    # 2. 最近5日全部数据
    # ======================================================

    recent_df = df[
        df["trade_date"].isin(
            recent_dates
        )
    ].copy()

    # ======================================================
    # 3. 账户近5日数据
    # ======================================================

    account_df = get_account_data(
        df,
        account_id,
        recent_dates
    )

    # ======================================================
    # 4. account_overall
    # ======================================================

    overall_metrics = (
        calculate_basic_metrics(
            account_df
        )
    )

    overall_metrics[
        "total_turnover"
    ] = calculate_turnover(
        account_df
    )

    # ======================================================
    # Benchmark A1
    #
    # 日期
    # + 市值组
    # + 底仓组
    #
    # 不区分算法
    # ======================================================

    benchmark_a1_groups = (
        calculate_benchmark_groups(
            account_df=account_df,
            full_df=recent_df,
            group_cols=BENCHMARK_CONFIGS["a1"]["group_cols"],
        )
    )

    benchmark_a1_summary = (
        aggregate_benchmark(
            account_df=account_df,
            benchmark_groups=benchmark_a1_groups,
            full_df=recent_df,
            group_cols=BENCHMARK_CONFIGS["a1"]["group_cols"],
        )
    )

    # ======================================================
    # 6. Benchmark A2
    #
    # 第一层环境：
    #
    # 日期
    # + 市值组
    # + 底仓组
    #
    # 第二层：
    #
    # + 算法
    #
    # 用于比较：
    #
    # 同一交易环境下，
    # 不同算法的表现。
    # ======================================================

    benchmark_a2_environment_groups = (
        calculate_benchmark_groups(
            account_df=account_df,
            full_df=recent_df,
            group_cols=BENCHMARK_CONFIGS["a2"]["group_cols"],
        )
    )

    benchmark_a2_groups = (
        calculate_algorithm_benchmark_groups(
            account_df=account_df,
            full_df=recent_df,
            environment_groups=benchmark_a2_environment_groups,
            environment_cols=BENCHMARK_CONFIGS["a2"]["group_cols"],
        )
    )

    benchmark_a2_algorithm_summaries = (
        aggregate_algorithm_benchmark(
            account_df=account_df,
            benchmark_groups=benchmark_a2_groups,
            full_df=recent_df,
            environment_cols=BENCHMARK_CONFIGS["a2"]["group_cols"],
        )
    )

    # ======================================================
    # Benchmark B1
    #
    # 日期
    # + 股票
    #
    # 不区分算法
    # ======================================================

    benchmark_b1_groups = (
        calculate_benchmark_groups(
            account_df=account_df,
            full_df=recent_df,
            group_cols=BENCHMARK_CONFIGS["b1"]["group_cols"],
        )
    )

    benchmark_b1_summary = (
        aggregate_benchmark(
            account_df=account_df,
            benchmark_groups=benchmark_b1_groups,
            full_df=recent_df,
            group_cols=BENCHMARK_CONFIGS["b1"]["group_cols"],
        )
    )

    # ======================================================
    # Benchmark B2
    #
    # 第一层环境：
    #
    # 日期
    # + 股票
    #
    # 第二层：
    #
    # + 算法
    #
    # 算法比较限定在账户实际股票池内。
    # ======================================================

    benchmark_b2_environment_groups = (
        calculate_benchmark_groups(
            account_df=account_df,
            full_df=recent_df,
            group_cols=BENCHMARK_CONFIGS["b2"]["group_cols"],
        )
    )

    benchmark_b2_groups = (
        calculate_algorithm_benchmark_groups(
            account_df=account_df,
            full_df=recent_df,
            environment_groups=
                benchmark_b2_environment_groups,
            environment_cols=
                BENCHMARK_CONFIGS["b2"]["group_cols"],
        )
    )

    benchmark_b2_algorithm_summaries = (
        aggregate_algorithm_benchmark(
            account_df=account_df,
            benchmark_groups=benchmark_b2_groups,
            full_df=recent_df,
            environment_cols=
                BENCHMARK_CONFIGS["b2"]["group_cols"],
        )
    )

    # ======================================================
    # 8. Benchmark 综合比较
    # ======================================================

    benchmark_comparison = (
        build_benchmark_comparison(
            account_overall=overall_metrics,

            benchmark_a1_summary=
                benchmark_a1_summary,

            benchmark_a2_algorithm_summaries=
                benchmark_a2_algorithm_summaries,

            benchmark_b1_summary=
                benchmark_b1_summary,

            benchmark_b2_algorithm_summaries=
                benchmark_b2_algorithm_summaries,
        )
    )

    # ======================================================
    # 9. 返回
    # ======================================================

    return {

        # ==================================================
        # 基础信息
        # ==================================================

        "account_id":
            str(account_id),

        "date_range": {

            "start":
                recent_dates[0],

            "end":
                recent_dates[-1],
        },

        "trading_days": [

            d.strftime("%Y-%m-%d")
            for d in recent_dates
        ],

        # ==================================================
        # 账户总体
        # ==================================================

        "account_overall":
            overall_metrics,

        # ==================================================
        # Benchmark A
        # ==================================================

        "benchmark_a": {

            # ------------------------------------------------
            # A1：同交易环境整体表现
            # ------------------------------------------------

            "a1": {

                "groups":
                    benchmark_a1_groups,

                "summary":
                    benchmark_a1_summary,
            },

            # ------------------------------------------------
            # A2：同交易环境不同算法
            # ------------------------------------------------

            "a2": {

                "groups":
                    benchmark_a2_groups,

                "algorithm_summaries":
                    benchmark_a2_algorithm_summaries,
            },
        },

        # ==================================================
        # Benchmark B
        # ==================================================

        "benchmark_b": {

            # ------------------------------------------------
            # B1：同股票池整体表现
            # ------------------------------------------------

            "b1": {

                "groups":
                    benchmark_b1_groups,

                "summary":
                    benchmark_b1_summary,
            },

            # ------------------------------------------------
            # B2：同股票池不同算法
            # ------------------------------------------------

            "b2": {

                "groups":
                    benchmark_b2_groups,

                "algorithm_summaries":
                    benchmark_b2_algorithm_summaries,
            },
        },

        # ==================================================
        # 第11部分
        #
        # 下一阶段生成
        # ==================================================

        "benchmark_comparison":
            benchmark_comparison,
    }

# ==========================================================
# 主函数
# ==========================================================

def main(account_id):

    start_time = datetime.now()

    logging.info("=" * 60)
    logging.info(
        "开始 Analysis Demo"
    )
    logging.info(
        "account_id = %s",
        account_id
    )
    logging.info("=" * 60)

    # ------------------------------------------------------
    # 1. 读取
    # ------------------------------------------------------

    df = load_analysis_record()

    # ------------------------------------------------------
    # 2. 基础分析
    # ------------------------------------------------------

    report = analyze_account_basic(
        df,
        account_id
    )

    # ------------------------------------------------------
    # 3. 输出
    # ------------------------------------------------------

    report["metadata"] = {
        "report_type":
            "account_analysis_demo",

        "version":
            "0.1",

        "generated_at":
            datetime.now(),

        "database":
            str(DB_PATH),

        "table":
            "analysis_record",

        "elapsed_seconds":
            round(
                (
                    datetime.now()
                    - start_time
                ).total_seconds(),
                3
            ),
    }

    output_path = (
        REPORT_DIR
        / f"account_analysis_{account_id}.json"
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=4,
            default=json_convert
        )

    logging.info(
        "报告已保存：%s",
        output_path
    )

    logging.info("=" * 60)
    logging.info(
        "Analysis Demo 完成"
    )
    logging.info("=" * 60)

    return report


# ==========================================================
# main
# ==========================================================

if __name__ == "__main__":

    # 示例：
    #
    # python analysis_demo.py 123456789
    #
    import sys

    if len(sys.argv) < 2:

        print(
            "用法：python analysis_demo.py <account_id>"
        )

        sys.exit(1)

    main(
        sys.argv[1]
    )
