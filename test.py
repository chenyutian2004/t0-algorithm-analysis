"""
test.py
用于检查SQLite数据库基本信息
"""

import sqlite3
from schema import (
    DB_PATH,
    STOCK_TOTAL_MV_GROUPS,
    STOCK_TURNOVER_GROUPS,
    STOCK_AMPLITUDE_GROUPS,
    STOCK_RETURN_STATE_GROUPS,
    MARKET_RETURN_GROUPS,
    MARKET_VOLATILITY_GROUPS,
    MARKET_BREADTH_GROUPS,
    MARKET_TREND_GROUPS,
)
from pathlib import Path
from datetime import datetime
import pandas as pd
import sys


STOCKDB_COLUMNS = [
    "stock_open", "stock_high", "stock_low", "stock_close",
    "stock_volume", "stock_amount", "stock_pct_chg",
    "stock_amplitude", "stock_turnover", "stock_pre_close",
    "stock_total_mv", "stock_float_mv", "stock_pe_ttm", "stock_pb",
    "stock_is_st", "stock_vol_ratio", "stock_data_available",
    "stock_data_source",
]

LAG1_STOCK_COLUMNS = [
    f"lag1_{column}" for column in STOCKDB_COLUMNS
    if column != "stock_data_source"
]

LAG1_MARKET_COLUMNS = [
    "lag1_benchmark_open", "lag1_benchmark_high", "lag1_benchmark_low",
    "lag1_benchmark_close", "lag1_benchmark_volume", "lag1_market_return",
    "lag1_market_volatility", "lag1_market_breadth", "lag1_market_trend",
    "lag1_breadth_valid_count", "lag1_breadth_up_count",
    "lag1_breadth_down_count", "lag1_breadth_flat_count",
    "lag1_market_data_available",
]

LEGACY_STOCKDB_COLUMNS = [
    column.replace("stock_", "market_", 1)
    for column in STOCKDB_COLUMNS
]


class Tee:
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()

    def flush(self):
        for f in self.files:
            f.flush()


log_dir = Path("log")
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f"test_{datetime.now():%Y%m%d_%H%M%S}.log"

log_fp = open(log_file, "w", encoding="utf-8")

sys.stdout = Tee(sys.__stdout__, log_fp)
sys.stderr = Tee(sys.__stderr__, log_fp)

def load_analysis_record():
    """读取 Prepare 后的 analysis_record。"""

    print()
    print("=" * 60)
    print("读取 analysis_record")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)

    try:
        df = pd.read_sql_query(
            """
            SELECT *
            FROM analysis_record
            """,
            conn
        )
    finally:
        conn.close()

    if df.empty:
        raise RuntimeError(
            "analysis_record 为空"
        )

    print(
        f"analysis_record："
        f"{len(df):,} 行 × "
        f"{len(df.columns)} 列"
    )

    return df


def load_market_environment():
    """读取市场整体行情表。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(
            "SELECT * FROM market_environment ORDER BY trade_date", conn
        )
    finally:
        conn.close()


def validate_market_environment_table(df, analysis_df):
    """检查市场整体行情表结构、日期覆盖和基本数值范围。"""
    print()
    print("=" * 60)
    print("market_environment 检查")
    print("=" * 60)

    print(f"行列数：{len(df):,} 行 × {len(df.columns):,} 列")
    print("字段：", ", ".join(df.columns))
    print("数据类型：")
    print(df.dtypes.astype(str).to_string())
    print("缺失值：")
    print(df.isna().sum().to_string())

    required = [
        "trade_date", "benchmark_symbol", "benchmark_close",
        "market_return", "market_volatility", "market_breadth", "market_trend",
        "breadth_valid_count", "breadth_up_count", "breadth_down_count",
        "breadth_flat_count", "data_source",
    ]
    missing = [column for column in required if column not in df.columns]
    errors = []
    if missing:
        errors.append(f"缺少字段：{missing}")
    if df.empty:
        errors.append("数据表为空")
    if "trade_date" in df and df["trade_date"].duplicated().any():
        errors.append("存在重复交易日")

    if not missing and not df.empty:
        core = ["market_return", "market_volatility", "market_breadth", "market_trend"]
        nulls = df[core].isna().sum()
        if nulls.any():
            errors.append(f"核心字段存在缺失：{nulls.to_dict()}")
        if not pd.to_numeric(df["market_breadth"], errors="coerce").between(-100, 100).all():
            errors.append("market_breadth 超出 [-100, 100]")
        if (pd.to_numeric(df["market_volatility"], errors="coerce") < 0).any():
            errors.append("market_volatility 存在负数")

        environment_dates = set(pd.to_datetime(df["trade_date"]).dt.normalize())
        analysis_dates = set(pd.to_datetime(analysis_df["trade_date"]).dt.normalize())
        uncovered = sorted(analysis_dates - environment_dates)
        if uncovered:
            errors.append(f"未覆盖 analysis_record 交易日：{uncovered}")

        counts = (
            pd.to_numeric(df["breadth_up_count"], errors="coerce")
            + pd.to_numeric(df["breadth_down_count"], errors="coerce")
            + pd.to_numeric(df["breadth_flat_count"], errors="coerce")
        )
        valid = pd.to_numeric(df["breadth_valid_count"], errors="coerce")
        if (counts != valid).any():
            errors.append("市场宽度分项家数之和与有效家数不一致")

    if errors:
        raise AssertionError("；".join(errors))
    print(f"[PASS] {len(df):,} 个交易日，核心指标完整且日期覆盖正确")


def validate_market_groups(analysis_df, environment_df):
    """逐交易日检查四个市场分组与 market_environment 原值一致。"""

    print()
    print("=" * 60)
    print("analysis_record 市场整体行情分组检查")
    print("=" * 60)

    specs = [
        ("market_return", "market_return_group", MARKET_RETURN_GROUPS),
        ("market_volatility", "market_volatility_group", MARKET_VOLATILITY_GROUPS),
        ("market_breadth", "market_breadth_group", MARKET_BREADTH_GROUPS),
        ("market_trend", "market_trend_group", MARKET_TREND_GROUPS),
    ]
    errors = []

    if len(analysis_df.columns) != 86:
        errors.append(f"analysis_record 应为 86 列，实际为 {len(analysis_df.columns)} 列")

    actual_by_date = analysis_df[[
        "trade_date", *[target for _, target, _ in specs]
    ]].drop_duplicates()
    if actual_by_date["trade_date"].duplicated().any():
        errors.append("同一交易日存在多个市场分组值")

    expected = environment_df[[
        "trade_date", *[source for source, _, _ in specs]
    ]].copy()
    analysis_dates = set(pd.to_datetime(analysis_df["trade_date"]))
    expected = expected[
        pd.to_datetime(expected["trade_date"]).isin(analysis_dates)
    ].copy()
    for source, target, groups in specs:
        def classify(value):
            if pd.isna(value):
                return None
            for group in groups:
                lower, upper = group["min"], group["max"]
                if (lower is None or value >= lower) and (upper is None or value < upper):
                    return group["name"]
            return None
        expected[target] = pd.to_numeric(expected[source], errors="coerce").apply(classify)

    comparison = actual_by_date.merge(
        expected[["trade_date", *[target for _, target, _ in specs]]],
        on="trade_date", how="outer", suffixes=("_actual", "_expected"),
        indicator=True,
    )
    if (comparison["_merge"] != "both").any():
        errors.append("analysis_record 与 market_environment 日期无法完整对应")

    for _, target, _ in specs:
        actual = comparison[f"{target}_actual"].fillna("<NULL>")
        expected_values = comparison[f"{target}_expected"].fillna("<NULL>")
        mismatch = (actual != expected_values).sum()
        if mismatch:
            errors.append(f"{target} 有 {mismatch:,} 个交易日映射错误")

    if errors:
        raise AssertionError("；".join(errors))
    print("[PASS] analysis_record 为 86 列，四个市场分组逐日映射正确")

def check_analysis_structure(df):
    """检查 analysis_record 的基本结构。"""

    print()
    print("=" * 60)
    print("analysis_record 基本结构")
    print("=" * 60)

    print(
        f"行数：{len(df):,}"
    )

    print(
        f"列数：{len(df.columns):,}"
    )

    print()
    print("字段：")

    for i, col in enumerate(
        df.columns,
        start=1
    ):
        print(
            f"{i:>2}. {col}"
        )

def check_analysis_dtypes(df):
    """检查 analysis_record 数据类型。"""

    print()
    print("=" * 60)
    print("analysis_record 数据类型")
    print("=" * 60)

    dtype_df = pd.DataFrame({
        "column": df.columns,
        "dtype": [
            str(df[col].dtype)
            for col in df.columns
        ]
    })

    print(
        dtype_df.to_string(index=False)
    )

def check_analysis_missing(df):
    """检查 analysis_record 缺失值。"""

    print()
    print("=" * 60)
    print("analysis_record 缺失值")
    print("=" * 60)

    rows = []

    for col in df.columns:

        missing = int(
            df[col].isna().sum()
        )

        rows.append({
            "column": col,
            "missing": missing,
            "missing_ratio":
                missing / len(df)
                if len(df) > 0
                else None
        })

    result = pd.DataFrame(rows)

    result = result[
        result["missing"] > 0
    ].sort_values(
        "missing",
        ascending=False
    )

    if result.empty:

        print("无缺失值")

    else:

        result["missing_ratio"] = (
            result["missing_ratio"]
            .map(lambda x: f"{x:.4%}")
        )

        print(
            result.to_string(
                index=False
            )
        )

def check_analysis_key_fields(df):
    """检查 analysis_record 关键字段。"""

    print()
    print("=" * 60)
    print("analysis_record 关键字段")
    print("=" * 60)

    # ------------------------------------------------------
    # 日期
    # ------------------------------------------------------

    if "trade_date" in df.columns:

        dates = pd.to_datetime(
            df["trade_date"],
            errors="coerce"
        )

        print(
            "日期范围：",
            dates.min(),
            "~",
            dates.max()
        )

        print(
            "交易日期数量：",
            dates.nunique()
        )

    # ------------------------------------------------------
    # 账户
    # ------------------------------------------------------

    if "account_id" in df.columns:

        print(
            "账户数量：",
            df["account_id"].nunique()
        )

    # ------------------------------------------------------
    # 客户
    # ------------------------------------------------------

    if "customer_id" in df.columns:

        print(
            "客户数量：",
            df["customer_id"].nunique()
        )

    # ------------------------------------------------------
    # 股票
    # ------------------------------------------------------

    if "stock_code" in df.columns:

        print(
            "证券数量：",
            df["stock_code"].nunique()
        )

    # ------------------------------------------------------
    # 算法
    # ------------------------------------------------------

    if "algo_type" in df.columns:

        print()
        print("算法分布：")

        print(
            df["algo_type"]
            .value_counts(
                dropna=False
            )
            .to_string()
        )

def check_hxet0(df):
    """检查 HXET0 是否被正确保留。"""

    print()
    print("=" * 60)
    print("HXET0 检查")
    print("=" * 60)

    if "algo_type" not in df.columns:

        print("不存在 algo_type")
        return

    algo = (
        df["algo_type"]
        .astype(str)
        .str.strip()
    )

    hxet0 = df[
        algo == "HXET0"
    ]

    print(
        f"HXET0 记录数：{len(hxet0):,}"
    )

    if not hxet0.empty:

        print(
            f"HXET0 证券数量："
            f"{hxet0['stock_code'].nunique():,}"
        )

        if "security_type" in hxet0.columns:

            print()
            print(
                "HXET0 证券类型："
            )

            print(
                hxet0["security_type"]
                .value_counts(
                    dropna=False
                )
                .to_string()
            )

def check_security_type(df):
    """检查证券类型。"""

    print()
    print("=" * 60)
    print("证券类型")
    print("=" * 60)

    if "security_type" not in df.columns:

        print("不存在 security_type")
        return

    summary = (
        df["security_type"]
        .value_counts(
            dropna=False
        )
    )

    total = len(df)

    for security_type, count in summary.items():

        print(
            f"{str(security_type):<15}"
            f"{count:>10,}"
            f"  {count / total:>8.2%}"
        )

def check_market_data(df):
    """检查 StockDB 行情匹配情况。"""

    print()
    print("=" * 60)
    print("市场行情")
    print("=" * 60)

    if "stock_data_available" not in df.columns:

        print(
            "不存在 stock_data_available"
        )
        return

    available = int(
        (
            df["stock_data_available"]
            == 1
        ).sum()
    )

    missing = int(
        (
            df["stock_data_available"]
            == 0
        ).sum()
    )

    total = len(df)

    print(
        f"有行情：{available:,}"
    )

    print(
        f"无行情：{missing:,}"
    )

    print(
        f"匹配率："
        f"{available / total:.4%}"
    )

    # ------------------------------------------
    # 缺失行情的证券
    # ------------------------------------------

    missing_df = df[
        df["stock_data_available"] == 0
    ]

    if not missing_df.empty:

        print()
        print("无行情证券：")

        print(
            missing_df[
                [
                    "stock_code",
                    "security_type"
                ]
            ]
            .drop_duplicates()
            .to_string(index=False)
        )


def validate_stockdb_columns(df):
    """检查 StockDB 的 18 个字段已统一采用 stock_* 命名。"""

    print()
    print("=" * 60)
    print("StockDB 字段命名检查")
    print("=" * 60)

    missing = [col for col in STOCKDB_COLUMNS if col not in df.columns]
    legacy = [col for col in LEGACY_STOCKDB_COLUMNS if col in df.columns]

    errors = []
    if missing:
        errors.append(f"缺少 stock_* 字段：{missing}")
    if legacy:
        errors.append(f"仍存在旧 market_* 字段：{legacy}")

    if not missing:
        available = pd.to_numeric(
            df["stock_data_available"], errors="coerce"
        )
        expected = df["stock_close"].notna().astype(int)

        invalid_flag = (~available.isin([0, 1])).sum()
        inconsistent = (available != expected).sum()

        if invalid_flag:
            errors.append(f"stock_data_available 有 {invalid_flag:,} 个非 0/1 值")
        if inconsistent:
            errors.append(
                f"stock_data_available 与 stock_close 有 {inconsistent:,} 行不一致"
            )

    if errors:
        raise AssertionError("；".join(errors))

    print("[PASS] 18 个 stock_* 字段齐全，旧 market_* 行情字段不存在")
    print("[PASS] stock_data_available 与 stock_close 一致")


def validate_lag1_features(df, environment_df):
    """检查31个 lag1_ 字段及上一市场交易日的严格对齐。"""

    print()
    print("=" * 60)
    print("lag1 预测特征检查")
    print("=" * 60)

    required = [*LAG1_STOCK_COLUMNS, *LAG1_MARKET_COLUMNS]
    errors = []
    missing = [column for column in required if column not in df.columns]
    if missing:
        errors.append(f"缺少 lag1_ 字段：{missing}")

    if not missing:
        stock_flag = pd.to_numeric(
            df["lag1_stock_data_available"], errors="coerce"
        )
        market_flag = pd.to_numeric(
            df["lag1_market_data_available"], errors="coerce"
        )
        if (~stock_flag.isin([0, 1])).any():
            errors.append("lag1_stock_data_available 存在非 0/1 值")
        if (~market_flag.isin([0, 1])).any():
            errors.append("lag1_market_data_available 存在非 0/1 值")
        if (stock_flag != df["lag1_stock_close"].notna().astype(int)).any():
            errors.append("lag1_stock_data_available 与 lag1_stock_close 不一致")
        if (market_flag != df["lag1_benchmark_close"].notna().astype(int)).any():
            errors.append("lag1_market_data_available 与 lag1_benchmark_close 不一致")

        environment = environment_df.copy()
        environment["trade_date"] = pd.to_datetime(
            environment["trade_date"], errors="coerce"
        )
        environment = environment.sort_values("trade_date")
        calendar = pd.DatetimeIndex(environment["trade_date"].dropna().unique())

        actual = df[[
            "trade_date", "lag1_benchmark_close", "lag1_market_return",
            "lag1_market_data_available",
        ]].drop_duplicates()
        if actual["trade_date"].duplicated().any():
            errors.append("同一交易日存在多个 lag1 市场特征值")
        else:
            actual["trade_date"] = pd.to_datetime(actual["trade_date"])
            expected_rows = []
            env_by_date = environment.set_index("trade_date")
            for trade_date in actual["trade_date"]:
                position = calendar.searchsorted(trade_date, side="left")
                previous = calendar[position - 1] if position > 0 else pd.NaT
                if pd.isna(previous):
                    expected_rows.append((trade_date, None, None, 0))
                else:
                    row = env_by_date.loc[previous]
                    expected_rows.append((
                        trade_date, row["benchmark_close"],
                        row["market_return"], 1,
                    ))
            expected = pd.DataFrame(expected_rows, columns=[
                "trade_date", "expected_close", "expected_return", "expected_flag"
            ])
            comparison = actual.merge(expected, on="trade_date", how="left")
            for actual_col, expected_col in [
                ("lag1_benchmark_close", "expected_close"),
                ("lag1_market_return", "expected_return"),
            ]:
                left = pd.to_numeric(comparison[actual_col], errors="coerce")
                right = pd.to_numeric(comparison[expected_col], errors="coerce")
                mismatch = ~((left.isna() & right.isna()) | (left == right))
                if mismatch.any():
                    errors.append(f"{actual_col} 未严格匹配上一市场交易日")
            if (
                comparison["lag1_market_data_available"]
                != comparison["expected_flag"]
            ).any():
                errors.append("lag1_market_data_available 日期对齐错误")

    if errors:
        raise AssertionError("；".join(errors))

    print("[PASS] 31 个 lag1_ 字段齐全")
    print("[PASS] lag1 市场字段严格对应前一市场交易日")
    print(
        "[PASS] lag1 个股行情匹配率 "
        f"{df['lag1_stock_data_available'].mean():.4%}"
    )

def check_analysis_groups(df):
    """检查分析分组。"""

    for col in [
        "market_value_group",
        "actual_position_group",
        "stock_total_mv_group",
        "stock_turnover_group",
        "stock_amplitude_group",
        "stock_return_state",
        "market_return_group",
        "market_volatility_group",
        "market_breadth_group",
        "market_trend_group",
    ]:

        if col not in df.columns:
            continue

        print()
        print("=" * 60)
        print(col)
        print("=" * 60)

        summary = (
            df[col]
            .value_counts(
                dropna=False
            )
            .sort_index()
        )

        total = len(df)

        for group, count in summary.items():

            print(
                f"{str(group):<25}"
                f"{count:>10,}"
                f"  {count / total:>8.2%}"
            )


def validate_stock_groups(df):
    """检查四个个股行情分组字段的取值与缺失传递。"""

    print()
    print("=" * 60)
    print("StockDB 个股行情分组检查")
    print("=" * 60)

    specs = [
        ("stock_total_mv", "stock_total_mv_group", STOCK_TOTAL_MV_GROUPS),
        ("stock_turnover", "stock_turnover_group", STOCK_TURNOVER_GROUPS),
        ("stock_amplitude", "stock_amplitude_group", STOCK_AMPLITUDE_GROUPS),
        ("stock_pct_chg", "stock_return_state", STOCK_RETURN_STATE_GROUPS),
    ]
    errors = []

    for source, target, groups in specs:
        if target not in df.columns:
            errors.append(f"缺少字段 {target}")
            continue

        allowed = {group["name"] for group in groups}
        actual = set(df[target].dropna().unique())
        invalid = actual - allowed
        if invalid:
            errors.append(f"{target} 存在非法取值：{sorted(invalid)}")

        source_missing = pd.to_numeric(df[source], errors="coerce").isna()
        inconsistent = (source_missing != df[target].isna()).sum()
        if inconsistent:
            errors.append(f"{target} 有 {inconsistent:,} 行未正确传递缺失值")

    if errors:
        raise AssertionError("；".join(errors))

    print("[PASS] 四个个股行情分组字段及其取值、缺失传递均正确")

def check_market_extended_data(df):

    print()
    print("=" * 60)
    print("扩展市场数据")
    print("=" * 60)

    cols = [
        "stock_pre_close",
        "stock_total_mv",
        "stock_float_mv",
        "stock_pe_ttm",
        "stock_pb",
        "stock_is_st",
        "stock_vol_ratio",
    ]

    for col in cols:

        if col not in df.columns:
            print(f"[FAIL] 缺少字段：{col}")
            continue

        missing = df[col].isna().sum()

        print(
            f"{col:<25}"
            f"missing={missing:,}"
            f"  available={len(df)-missing:,}"
        )

def validate_analysis_record(df):
    """
    检查 analysis_record 是否满足 Prepare 的基本业务约束。
    """

    print()
    print("=" * 60)
    print("analysis_record 业务约束检查")
    print("=" * 60)

    errors = []

    # ------------------------------------------------------
    # 1. 交易结果
    # ------------------------------------------------------

    if "trade_result" in df.columns:

        invalid = (
            df["trade_result"]
            .astype(str)
            .str.strip()
            != "已平"
        ).sum()

        if invalid > 0:

            errors.append(
                f"存在 {invalid:,} 条交易结果不是“已平”"
            )

        print(
            f"交易结果=已平："
            f"{len(df) - invalid:,} / {len(df):,}"
        )

    # ------------------------------------------------------
    # 2. 交易进度
    # ------------------------------------------------------

    if "trade_progress" in df.columns:

        progress = pd.to_numeric(
            df["trade_progress"],
            errors="coerce"
        )

        invalid = (
            progress.isna()
            | (progress <= 0)
        ).sum()

        if invalid > 0:

            errors.append(
                f"存在 {invalid:,} 条交易进度 <= 0 或无效"
            )

        print(
            f"交易进度>0："
            f"{len(df) - invalid:,} / {len(df):,}"
        )

    # ------------------------------------------------------
    # 3. 行情缺失不作为错误
    # ------------------------------------------------------

    if "stock_data_available" in df.columns:

        missing = (
            df["stock_data_available"]
            == 0
        ).sum()

        print(
            f"行情缺失："
            f"{missing:,} 条（允许）"
        )

    # ------------------------------------------------------
    # 最终
    # ------------------------------------------------------

    print()

    if errors:

        print("[FAIL] 发现问题：")

        for error in errors:
            print(
                " -",
                error
            )

    else:

        print(
            "[PASS] analysis_record "
            "业务约束全部通过"
        )

def check_basic_info():
    print(f"日志文件：{log_file}")
    print()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("=" * 60)
    print("数据库信息")
    print("=" * 60)
    print(f"数据库路径：{DB_PATH}")

    # SQLite版本
    cursor.execute("SELECT sqlite_version();")
    print(f"SQLite版本：{cursor.fetchone()[0]}")

    # 数据表
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        ORDER BY name;
    """)

    tables = [x[0] for x in cursor.fetchall()]
    print(f"\n数据表：{tables}")

    if "trade_record" not in tables:
        print("\n未发现 trade_record 表！")
        return

    # 总记录数
    cursor.execute("SELECT COUNT(*) FROM trade_record;")
    total = cursor.fetchone()[0]

    print("\n" + "=" * 60)
    print("trade_record")
    print("=" * 60)
    print(f"总记录数：{total:,}")

    # 日期范围
    cursor.execute("""
        SELECT
            MIN(trade_date),
            MAX(trade_date)
        FROM trade_record;
    """)

    start, end = cursor.fetchone()

    print(f"日期范围：{start} ~ {end}")

    # 不同客户数量
    cursor.execute("""
        SELECT COUNT(DISTINCT customer_id)
        FROM trade_record;
    """)

    print(f"客户数：{cursor.fetchone()[0]:,}")

    # 不同账户数量
    cursor.execute("""
        SELECT COUNT(DISTINCT account_id)
        FROM trade_record;
    """)

    print(f"账户数：{cursor.fetchone()[0]:,}")

    # 股票数量
    cursor.execute("""
        SELECT COUNT(DISTINCT stock_code)
        FROM trade_record;
    """)

    print(f"股票数：{cursor.fetchone()[0]:,}")

    # 算法数量
    cursor.execute("""
        SELECT COUNT(DISTINCT algo_type)
        FROM trade_record;
    """)

    print(f"算法类型数：{cursor.fetchone()[0]}")

    # 空值统计
    print("\n空值统计")

    cols = [
        "task_id",
        "customer_id",
        "account_id",
        "algo_type",
        "trade_date",
        "stock_code",
        "profit",
        "return_rate"
    ]

    for col in cols:
        cursor.execute(f"""
            SELECT COUNT(*)
            FROM trade_record
            WHERE {col} IS NULL;
        """)
        print(f"{col:<20}{cursor.fetchone()[0]}")

    # 每日记录数
    print("\n每日数据量")

    cursor.execute("""
        SELECT trade_date, COUNT(*)
        FROM trade_record
        GROUP BY trade_date
        ORDER BY trade_date;
    """)

    for d, n in cursor.fetchall():
        print(f"{d} : {n:,}")

    # 算法类型统计
    print("\n算法类型统计")

    cursor.execute("""
        SELECT algo_type, COUNT(*)
        FROM trade_record
        GROUP BY algo_type
        ORDER BY COUNT(*) DESC;
    """)

    for algo, n in cursor.fetchall():
        print(f"{algo:<25}{n:,}")

    conn.close()

    print("\n数据库检查完成。")


def main():

    # ======================================================
    # 1. 原 trade_record 检查
    # ======================================================

    check_basic_info()

    # ======================================================
    # 2. analysis_record
    # ======================================================

    analysis_df = load_analysis_record()

    environment_df = load_market_environment()

    validate_market_environment_table(
        environment_df,
        analysis_df,
    )

    validate_market_groups(
        analysis_df,
        environment_df,
    )

    check_analysis_structure(
        analysis_df
    )

    check_analysis_dtypes(
        analysis_df
    )

    check_analysis_missing(
        analysis_df
    )

    check_analysis_key_fields(
        analysis_df
    )

    check_hxet0(
        analysis_df
    )

    check_security_type(
        analysis_df
    )

    check_analysis_groups(
        analysis_df
    )

    validate_stockdb_columns(
        analysis_df
    )

    validate_lag1_features(
        analysis_df,
        environment_df,
    )

    validate_stock_groups(
        analysis_df
    )

    check_market_data(
        analysis_df
    )

    check_market_extended_data(
        analysis_df
    )

    validate_analysis_record(
        analysis_df
    )


if __name__ == "__main__":
    main()
