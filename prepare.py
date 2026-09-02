"""
prepare.py

负责将 trade_record 转换为 analysis_record。

职责：
1. 从 SQLite trade_record 读取数据
2. 根据配置进行基础过滤
3. 根据 market_value 生成 market_value_group
4. 根据 actual_position 生成 actual_position_group
5. 读取 market_environment 阶段已落库的行情数据
6. 加工并保存 analysis_record

注意：
- 不修改 trade_record
- 分组阈值统一来自 schema.py
- 不负责下载或计算行情；运行前必须先执行 market_environment.py
- 后续分析模块直接读取 analysis_record
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from schema import (
    DB_PATH,
    MARKET_VALUE_GROUPS,
    ACTUAL_POSITION_GROUPS,
    STOCK_TOTAL_MV_GROUPS,
    STOCK_TURNOVER_GROUPS,
    STOCK_AMPLITUDE_GROUPS,
    STOCK_RETURN_STATE_GROUPS,
    MARKET_RETURN_GROUPS,
    MARKET_VOLATILITY_GROUPS,
    MARKET_BREADTH_GROUPS,
    MARKET_TREND_GROUPS,
    PREPARE_CONFIG,
)


STOCK_MARKET_COLUMNS = [
    "stock_open", "stock_high", "stock_low", "stock_close",
    "stock_volume", "stock_amount", "stock_pct_chg",
    "stock_amplitude", "stock_turnover", "stock_pre_close",
    "stock_total_mv", "stock_float_mv", "stock_pe_ttm", "stock_pb",
    "stock_is_st", "stock_vol_ratio",
]

LAG1_MARKET_COLUMNS = [
    "benchmark_open", "benchmark_high", "benchmark_low", "benchmark_close",
    "benchmark_volume", "market_return", "market_volatility",
    "market_breadth", "market_trend", "breadth_valid_count",
    "breadth_up_count", "breadth_down_count", "breadth_flat_count",
]


# ==========================================================
# 日志
# ==========================================================

LOG_DIR = Path("log")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(
            LOG_DIR / f"prepare_{datetime.now():%Y%m%d_%H%M%S}.log",
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)


# ==========================================================
# 分组函数
# ==========================================================

def classify_value(value, groups):
    """
    根据 config 中的分组区间进行分类。

    区间定义：
        min <= x < max

    当 min=None：
        x < max

    当 max=None：
        x >= min
    """

    if pd.isna(value):
        return None

    value = float(value)

    for group in groups:

        lower = group["min"]
        upper = group["max"]

        if lower is None and upper is not None:

            if value < upper:
                return group["name"]

        elif lower is not None and upper is None:

            if value >= lower:
                return group["name"]

        elif lower is not None and upper is not None:

            if lower <= value < upper:
                return group["name"]

    return None


# ==========================================================
# 数据读取
# ==========================================================

def load_trade_record():
    """读取 trade_record"""

    logging.info("开始读取 trade_record")

    conn = sqlite3.connect(DB_PATH)

    try:

        df = pd.read_sql_query(
            """
            SELECT *
            FROM trade_record
            """,
            conn
        )

    finally:

        conn.close()

    logging.info(
        "trade_record 读取完成：%d 行 × %d 列",
        len(df),
        len(df.columns)
    )

    return df


# ==========================================================
# 基础过滤
# ==========================================================

def apply_basic_filter(df):
    """
    应用 Prepare 的基础业务过滤条件。

    保留：
    1. 交易结果 = 已平
    2. 交易进度 > 0

    注意：
    - 不再排除 HXET0
    - HXET0 作为 ETF 算法保留
    - 不在此阶段处理行情数据
    """

    original_count = len(df)

    # ------------------------------------------------------
    # 1. 交易结果
    # ------------------------------------------------------

    df = df[
        df["trade_result"].astype(str).str.strip() == "已平"
    ].copy()

    logging.info(
        "筛选交易结果=已平：%d → %d",
        original_count,
        len(df)
    )

    # ------------------------------------------------------
    # 2. 交易进度 > 0
    # ------------------------------------------------------

    before = len(df)

    df["trade_progress"] = pd.to_numeric(
        df["trade_progress"],
        errors="coerce"
    )

    df = df[
        df["trade_progress"] > 0
    ].copy()

    logging.info(
        "筛选交易进度>0：%d → %d",
        before,
        len(df)
    )

    return df

def classify_security_type(stock_code):
    """
    根据统一股票代码判断证券类型。

    当前仅区分：
        STOCK
        ETF
        OTHER
    """

    if pd.isna(stock_code):
        return "OTHER"

    code = str(stock_code).strip().upper()

    if "." in code:
        number = code.split(".", 1)[0]
    else:
        number = code.zfill(6)

    # ------------------------------------------
    # ETF
    # ------------------------------------------

    if number.startswith("15"):
        return "ETF"

    if number.startswith(("51", "52", "56", "58")):
        return "ETF"

    # ------------------------------------------
    # 普通股票
    # ------------------------------------------

    if number.startswith(("00", "30", "60", "68", "69")):
        return "STOCK"

    # ------------------------------------------
    # 其他
    # ------------------------------------------

    return "OTHER"

def add_security_type(df):

    df = df.copy()

    df["security_type"] = (
        df["stock_code"]
        .apply(classify_security_type)
    )

    return df

def load_prepared_market_data():
    """读取 market_environment 阶段已保存的两张行情表。"""

    conn = sqlite3.connect(DB_PATH)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"stock_market_data", "market_environment"}
        missing = sorted(required - tables)
        if missing:
            raise RuntimeError(
                f"缺少行情表 {missing}；请先运行 python main.py market"
            )
        market_df = pd.read_sql_query("SELECT * FROM stock_market_data", conn)
        environment_df = pd.read_sql_query("SELECT * FROM market_environment", conn)
    finally:
        conn.close()

    for frame in (market_df, environment_df):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    if market_df.empty or environment_df.empty:
        raise RuntimeError("行情表为空；请先运行 python main.py market")
    return market_df, environment_df


def add_market_data(df):
    """将既有行情表连接到交易样本，不执行任何行情下载或计算。"""

    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    market_df, environment_df = load_prepared_market_data()
    df = df.merge(market_df, on=["trade_date", "stock_code"], how="left")
    df["stock_data_available"] = df["stock_close"].notna().astype(int)
    df["stock_data_source"] = df["stock_data_available"].map({1: "stockdb", 0: None})
    df = add_market_group_columns(df, environment_df)
    return add_lag1_features(df, market_df, environment_df)


def add_empty_lag1_columns(df):
    """行情整体不可用时仍生成稳定的 lag1_ 表结构。"""

    df = df.copy()
    for column in STOCK_MARKET_COLUMNS:
        df[f"lag1_{column}"] = None
    df["lag1_stock_data_available"] = 0
    for column in LAG1_MARKET_COLUMNS:
        df[f"lag1_{column}"] = None
    df["lag1_market_data_available"] = 0
    return df


def add_lag1_features(df, market_df, environment_df):
    """按前一市场交易日添加个股与市场 lag1_ 预测字段，不向更早日期回填。"""

    result = df.copy()
    calendar = pd.DatetimeIndex(
        pd.to_datetime(environment_df["trade_date"], errors="coerce")
        .dropna()
        .unique()
    ).sort_values()

    def previous_market_date(value):
        position = calendar.searchsorted(pd.Timestamp(value), side="left")
        return calendar[position - 1] if position > 0 else pd.NaT

    result["_lag1_trade_date"] = result["trade_date"].map(previous_market_date)

    stock_history = market_df[[
        "trade_date", "stock_code", *STOCK_MARKET_COLUMNS
    ]].copy()
    stock_history = stock_history.rename(columns={
        "trade_date": "_lag1_trade_date",
        **{column: f"lag1_{column}" for column in STOCK_MARKET_COLUMNS},
    })
    result = result.merge(
        stock_history,
        on=["_lag1_trade_date", "stock_code"],
        how="left",
        validate="many_to_one",
    )
    result["lag1_stock_data_available"] = (
        result["lag1_stock_close"].notna().astype(int)
    )

    market_history = environment_df[[
        "trade_date", *LAG1_MARKET_COLUMNS
    ]].copy()
    market_history = market_history.rename(columns={
        "trade_date": "_lag1_trade_date",
        **{column: f"lag1_{column}" for column in LAG1_MARKET_COLUMNS},
    })
    result = result.merge(
        market_history,
        on="_lag1_trade_date",
        how="left",
        validate="many_to_one",
    )
    result["lag1_market_data_available"] = (
        result["lag1_benchmark_close"].notna().astype(int)
    )

    logging.info(
        "lag1 特征已生成：个股匹配率 %.4f%%，市场匹配率 %.4f%%",
        result["lag1_stock_data_available"].mean() * 100,
        result["lag1_market_data_available"].mean() * 100,
    )
    return result.drop(columns="_lag1_trade_date")


def add_stock_group_columns(df):
    """根据 StockDB 个股行情生成四个固定阈值分组字段。"""

    df = df.copy()

    group_specs = [
        ("stock_total_mv", "stock_total_mv_group", STOCK_TOTAL_MV_GROUPS),
        ("stock_turnover", "stock_turnover_group", STOCK_TURNOVER_GROUPS),
        ("stock_amplitude", "stock_amplitude_group", STOCK_AMPLITUDE_GROUPS),
        ("stock_pct_chg", "stock_return_state", STOCK_RETURN_STATE_GROUPS),
    ]

    for source_column, group_column, groups in group_specs:
        values = pd.to_numeric(df[source_column], errors="coerce")
        df[source_column] = values
        df[group_column] = values.apply(lambda value: classify_value(value, groups))

    return df


def add_market_group_columns(df, environment_df):
    """按交易日把四个市场整体行情分组映射到 analysis_record。"""

    environment = environment_df.copy()
    group_specs = [
        ("market_return", "market_return_group", MARKET_RETURN_GROUPS),
        ("market_volatility", "market_volatility_group", MARKET_VOLATILITY_GROUPS),
        ("market_breadth", "market_breadth_group", MARKET_BREADTH_GROUPS),
        ("market_trend", "market_trend_group", MARKET_TREND_GROUPS),
    ]

    for source_column, group_column, groups in group_specs:
        values = pd.to_numeric(environment[source_column], errors="coerce")
        environment[group_column] = values.apply(
            lambda value: classify_value(value, groups)
        )

    group_columns = [group_column for _, group_column, _ in group_specs]
    return df.merge(
        environment[["trade_date", *group_columns]],
        on="trade_date",
        how="left",
        validate="many_to_one",
    )


# ==========================================================
# 生成规模分组
# ==========================================================

def add_group_columns(df):
    """
    添加：

        market_value_group
        actual_position_group
    """

    logging.info("开始生成规模分组")

    # ------------------------------------------------------
    # 类型转换
    # ------------------------------------------------------

    df["market_value"] = pd.to_numeric(
        df["market_value"],
        errors="coerce"
    )

    df["actual_position"] = pd.to_numeric(
        df["actual_position"],
        errors="coerce"
    )

    # ------------------------------------------------------
    # market value
    # ------------------------------------------------------

    df["market_value_group"] = df[
        "market_value"
    ].apply(
        lambda x: classify_value(
            x,
            MARKET_VALUE_GROUPS
        )
    )

    # ------------------------------------------------------
    # actual position
    # ------------------------------------------------------

    df["actual_position_group"] = df[
        "actual_position"
    ].apply(
        lambda x: classify_value(
            x,
            ACTUAL_POSITION_GROUPS
        )
    )

    return df


# ==========================================================
# 删除无法分类的数据
# ==========================================================

def remove_unclassified(df):
    """
    根据配置决定是否删除无法进行规模分组的数据。
    """

    if not PREPARE_CONFIG.get(
        "drop_unclassified",
        True
    ):
        return df

    before = len(df)

    df = df[
        df["market_value_group"].notna()
        & df["actual_position_group"].notna()
    ].copy()

    logging.info(
        "删除无法分组数据：%d → %d",
        before,
        len(df)
    )

    return df


# ==========================================================
# 保存 analysis_record
# ==========================================================

def save_analysis_record(df):
    """
    将准备后的数据保存为 analysis_record。

    使用 SQLite 表，而不是覆盖 trade_record。
    """

    conn = sqlite3.connect(DB_PATH)

    try:

        df.to_sql(
            "analysis_record",
            conn,
            if_exists="replace",
            index=False
        )

        # --------------------------------------------------
        # 建立常用索引
        # --------------------------------------------------

        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analysis_date
            ON analysis_record(trade_date)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analysis_market_group
            ON analysis_record(market_value_group)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analysis_position_group
            ON analysis_record(actual_position_group)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analysis_algo
            ON analysis_record(algo_type)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analysis_stock
            ON analysis_record(stock_code)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analysis_date_algo
            ON analysis_record(trade_date, algo_type)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analysis_date_stock
            ON analysis_record(trade_date, stock_code)
            """
        )

        conn.commit()

    finally:

        conn.close()

    logging.info(
        "analysis_record 已保存：%d 行",
        len(df)
    )


# ==========================================================
# 分组统计
# ==========================================================

def print_group_summary(df):
    """
    输出分组后的数据量，
    用于检查分组是否合理。
    """

    print()
    print("=" * 60)
    print("market_value_group")
    print("=" * 60)

    mv_summary = (
        df["market_value_group"]
        .value_counts()
        .sort_index()
    )

    for group, count in mv_summary.items():

        ratio = count / len(df)

        print(
            f"{group:<25}"
            f"{count:>10,}"
            f"  {ratio:>8.2%}"
        )

    print()
    print("=" * 60)
    print("actual_position_group")
    print("=" * 60)

    pos_summary = (
        df["actual_position_group"]
        .value_counts()
        .sort_index()
    )

    for group, count in pos_summary.items():

        ratio = count / len(df)

        print(
            f"{group:<25}"
            f"{count:>10,}"
            f"  {ratio:>8.2%}"
        )


# ==========================================================
# 主流程
# ==========================================================

def prepare():

    start_time = datetime.now()

    logging.info("=" * 60)
    logging.info("开始 Prepare")
    logging.info("=" * 60)

    # 1. 读取原始交易数据
    df = load_trade_record()

    # 2. 基础业务过滤
    df = apply_basic_filter(df)

    # 3. 规模分组
    df = add_group_columns(df)

    # 4. 删除无法进行 Benchmark A 分组的数据
    df = remove_unclassified(df)

    # 5. 证券类型
    df = add_security_type(df)

    # 6. StockDB 行情
    df = add_market_data(df)

    # 7. StockDB 个股行情分组
    df = add_stock_group_columns(df)

    # 8. 输出检查
    print_group_summary(df)

    print()
    print("=" * 60)
    print("证券类型")
    print("=" * 60)

    print(
        df["security_type"]
        .value_counts(dropna=False)
        .to_string()
    )

    print()
    print("=" * 60)
    print("行情匹配情况")
    print("=" * 60)

    available = (
        df["stock_data_available"]
        .sum()
    )

    missing = (
        len(df) - available
    )

    print(
        f"有行情：{available:,}"
    )

    print(
        f"无行情：{missing:,}"
    )

    print(
        f"匹配率："
        f"{available / len(df):.4%}"
    )

    # 9. 保存
    save_analysis_record(df)

    elapsed = (
        datetime.now() - start_time
    ).total_seconds()

    logging.info("=" * 60)

    logging.info(
        "Prepare 完成：%d 行，耗时 %.3f 秒",
        len(df),
        elapsed
    )

    logging.info("=" * 60)

    return df

# ==========================================================
# main
# ==========================================================

if __name__ == "__main__":
    prepare()

