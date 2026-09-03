# T0 Algorithm Analysis

## 项目目标

分析不同 T0 算法在不同交易环境下的表现，
建立清晰、可复验的算法评估数据流；预测模型暂不纳入当前阶段。

---

## 当前阶段

### 已完成

- trade_record 数据库
- StockDB 行情接入
- prepare
- analysis_record
- test
- analysis_account
- `market_environment`（包含分析日及 lag1 对齐所需前序交易日，17 个字段）
- `analysis_record` 扩充至 86 个字段
- 31 个统一采用 `lag1_` 前缀的上一市场交易日预测字段
- analysis_algo：Benchmark A/B/C/D、显著性检验与 FDR 校正
- analysis_algo 收益评价、置换检验和 Bootstrap 已统一为交易额加权口径
- analysis_algo 已增加独立股票共同覆盖分析：全量算法＋日期＋股票统计、固定股票/股票＋日期算法对排名及高覆盖股票组显著性检验
- 股票共同覆盖报告的显著性区段保留原始覆盖排名；共同交易日少于 5 天的小组会被跳过，因此显著性区段的 rank 可能不从 1 开始
- 已补充项目运行依赖及一键安装命令
- 完成模块精简：`database + importer → database.py`、`models + config → schema.py`
- 建立唯一总入口 `main.py`，默认全流程固定为 `import → market → prepare → algo`
- 将行情获取与计算从 `prepare.py` 分离；行情先落入 `stock_market_data` 与 `market_environment`

### 当前任务

- 检查和解释新版 `analysis_algo` 的算法表现及显著性结果
- 评估各 Benchmark 的共同环境覆盖率和结果稳定性
- 验证精简后 `market_environment → prepare` 流水线在新增 CSV 上的增量更新行为

### 下一阶段

1. 扩充交易日后复验时间滚动稳定性与样本外表现
2. 综合 Benchmark A/B/C/D 形成算法评分
3. 扩充历史交易日样本
4. 完成稳定差异评估后，再决定是否建立预测层及其训练数据定义

注意：ETF 的总市值含义可能与普通股票不同；统计和建模时至少保留
`security_type` 作为控制字段。

---

## 重要原则

不要为了新的分析需求随意修改数据库基础结构。

原始交易数据：
trade_record

分析基础数据：
analysis_record

算法统计分析：
analysis_algo

账户分析：
analysis_account

Codex：
每次读取 README 并完成任务后，都必须检查并更新“当前阶段”下的“已完成”、
“当前任务”和“下一阶段”三个部分，使其与实际进度一致；同时写入
`./log/codex_YYYYMMDD_HHMMSS.log`。

## 运行依赖

项目需要 Python 3.8 或更高版本。需要通过 PyPI 安装的第三方包为：

- `numpy`
- `pandas`
- `requests`

从项目依赖文件一次性安装全部公开依赖：

```powershell
python -m pip install -r requirements.txt
```

此外，`market_environment.py` 依赖开源项目
[hello245m/free-stockdb](https://github.com/hello245m/free-stockdb) 提供的
本地行情服务和 `stock_sdk`。它不是本项目的 PyPI 依赖，需要按
`stockdb/README.md` 完成上游数据同步、服务启动和 Python SDK 配置。

## 当前数据流

```text
CSV → database.py → trade_record
                         ↓
                 market_environment.py
                         ↓
          stock_market_data + market_environment
                         ↓
                     prepare.py
                         ↓
                  analysis_record
                    ↙          ↘
       analysis_account.py   analysis_algo.py
```

`market_environment.py` 负责行情是什么、如何获取和计算；`prepare.py` 只负责
把数据库中已有的交易与行情加工成分析样本。二者不得重新合并。

## 项目结构与入口

核心代码固定为：

```text
main.py
database.py
schema.py
market_environment.py
prepare.py
analysis_account.py
analysis_algo.py
test.py
```

不建立 `analysis_record.py`；`analysis_record` 是数据库表。当前阶段也不纳入
XGBoost 或其他预测模块。

统一从 `main.py` 执行：

```powershell
python main.py all
python main.py import
python main.py market
python main.py prepare
python main.py algo
python main.py account --account-id <ACCOUNT_ID>
```

`all` 依次执行 `import → market → prepare → algo`。账户分析需要明确指定
`account_id`，不会被 `all` 强制执行。

项目成员的分支、提交、同步、Pull Request 和冲突处理约定见
[`Git协作流程.md`](Git协作流程.md)。

---

## 市场数据来源

个股行情统一来自 StockDB；市场基准行情使用已验证的新浪沪深300
日线接口。除这两个已确认来源外，不要引入其他数据。

本地接入方式见 `stockdb/README.md`；交易 CSV 的放置、字段和脱敏要求见
`data/README.md`。

本项目只读取 StockDB 中已有的市场数据；原始匹配行情先写入项目自己的
SQLite 数据库（`trade.db`）中的 `stock_market_data`，市场环境写入
`market_environment`，随后由 `prepare.py` 生成 `analysis_record`。StockDB 关于私有策略
数据写入 `rd + ./mydb` 的约束，不适用于本项目的交易与分析结果存储。

`market_environment` 按交易日唯一，核心口径为：

- `market_return`：沪深300日收益率，单位为百分点。
- `market_volatility`：沪深300近20个交易日日收益率标准差年化。
- `market_breadth`：（上涨家数－下跌家数）/ 有效证券数，单位为百分点。
- `market_trend`：沪深300收盘价相对20日均线的偏离，单位为百分点。

为避免起始日滚动指标缺失，指数数据额外读取此前60个自然日。市场宽度股票池
为本次 Prepare 中交易样本涉及且 StockDB 成功返回行情的证券；表中保留有效、
上涨、下跌和平盘家数用于审计。

---

## 原始csv数据

任务ID
- 长数字，并非primary key

客户号
- 长数字，客户标识

账号类型
- UM0
-- 普通资金账号，用于股票、基金等普通交易
- UMC
-- 统一保证金账户或信用相关账户，用于融资融券、衍生品或统一保证金业务

资金账号
- 长数字，客户资金账号标识，客户可有多个资金账号

算法类型
- HXET0
-- ETF交易算法，但并不完全只参与ETF交易，也纳入分析范围
- KFT0/YRT0/...
-- 其他股票交易算法，为主要分析类别

交易日期
- xxxx-xx-xx

买入类型
- string

证券代码
- string

证券名称
- string

交易结果
- string

交易进度
- 0-1的小数，表示订单实际完成比例

授权持仓量
- int

实际底仓
- int

总买量
- int

总买金额
- float

买入均价
- float

总卖量
- int

总卖金额
- float

卖出均价
- float

今日交易额
- int

实际底仓的市值
- float

当日盈亏金额
- float

日收益率%
- float，-100-1000，实际日收益率为3.32%时，记作3.320000

母单状态
- string

是否GRT
- string

---

## analysis_record

analysis_record 是 Prepare 阶段生成的分析基础表。

当前已有 86 个字段。

字段组成：

- 26 个原始交易字段：从 `trade_record` 保留。
- 3 个 Prepare 衍生字段：`market_value_group`、
  `actual_position_group`、`security_type`。
- 16 个当日 StockDB 个股日行情字段：`stock_open` 至 `stock_vol_ratio` 等 `stock_*` 字段。
- 2 个个股行情状态字段：`stock_data_available`、`stock_data_source`。
- 4 个个股行情分组字段：`stock_total_mv_group`、`stock_turnover_group`、
  `stock_amplitude_group`、`stock_return_state`。
- 4 个市场整体行情分组字段：`market_return_group`、
  `market_volatility_group`、`market_breadth_group`、`market_trend_group`。
- 17 个上一市场交易日个股行情字段：统一采用 `lag1_stock_*` 命名，
  包括 `lag1_stock_data_available`。
- 14 个上一市场交易日基准与市场环境字段：统一采用 `lag1_benchmark_*`、
  `lag1_market_*` 和 `lag1_breadth_*` 命名，包括
  `lag1_market_data_available`。

### 行情时点与用途

当前 `stock_*` 字段是交易当日的完整个股日行情（包括收盘、最高、最低、
成交额等），用于**算法评估**、事后归因与相同市场环境下的表现比较。
它们不得直接作为交易当日算法选择或预测的输入，以避免使用未来信息。

算法**预测/选择**必须使用截至预测时点已知的信息；对日频市场特征，
默认使用上一实际交易日的行情。后续在 `analysis_record` 或其派生分析
数据中加入上一交易日行情/滞后特征时，字段命名、交易日历对齐方式和
缺失值处理须明确记录，且不得改变当日 `stock_*` 字段的既有含义。

当前 `lag1_` 字段严格对应当前 `trade_date` 的前一个市场交易日，而不是
前一个自然日；个股在该日缺少行情时不向更早日期回填，并设置
`lag1_stock_data_available=0`。`market_environment` 会额外保留首个分析日
所需的前序市场交易日，以保证首日也能正确生成 lag1 市场特征。

### 已确认的数据口径

- `return_rate` 对应原始字段“日收益率%”，单位为百分点：实际 3.32% 记为
  `3.320000`，不是小数 `0.0332`。
- 个股行情是否可用仍由 `stock_close` 是否成功匹配标识；无需额外细分缺失原因。
- 当前 StockDB 代码映射规则和 `analysis_record` 的全量重建机制维持不变。

---

## analysis_account

analysis_account 用于单账户近5个交易日分析。

已经建立：

- account_overall
- Benchmark A
- Benchmark B

Benchmark：

A1:
trade_date + market_value_group + actual_position_group

A2:
trade_date + market_value_group + actual_position_group + algo_type

B1:
trade_date + stock_code

B2:
trade_date + stock_code + algo_type

基准样本**保留目标账户自身记录**；这是当前确认的总体环境比较口径，
不采用 leave-one-account-out 排除规则。

---

## analysis_algo

analysis_algo 专注于算法类型之间的比较。

当前已建立 `analysis_algo.py`，从全局算法视角实现 Benchmark A/B/C/D。
主要指标包括胜率、盈利额占盈利与亏损绝对额之和的比例、交易额加权收益率；
其中交易额加权收益率定义为 `Σ(return_rate × turnover) / Σturnover`。
未加权平均收益率仅作为收益分布诊断字段，不参与算法排名和显著性结论。

四种 Benchmark 的环境分组参考字段固定如下，字段均直接来自
`analysis_record`：

- Benchmark A（持仓规模环境）：`trade_date`、`market_value_group`、
  `actual_position_group`。
- Benchmark B（同日同证券）：`trade_date`、`stock_code`。
- Benchmark C（个股行情特征环境）：`trade_date`、`security_type`、
  `stock_total_mv_group`、`stock_turnover_group`、`stock_amplitude_group`、
  `stock_return_state`。
- Benchmark D（市场整体行情环境）：`market_return_group`、
  `market_volatility_group`、`market_breadth_group`、`market_trend_group`、
  `security_type`。

上述列表与 `analysis_algo.py` 中 `BENCHMARKS[*]["group_cols"]` 完全一致。
显著性检验的聚合单元始终包含 `trade_date`：A/B/C 已直接包含该字段；D 在
构造显著性单元时由程序自动补入 `trade_date`，但 D 的环境分组字段本身不变。

基本思路：

继承/复用 analysis_account 的交易环境控制思想，
再加入市场数据控制变量，
比较不同算法在相同环境下的表现。

其中，当日 `stock_*` 及市场环境字段用于评估环境控制；预测特征须使用上一交易日或更早
的可得行情。

算法之间使用共同环境配对、leave-one-algorithm-out、日期聚类 Bootstrap、
配对置换检验和 BH-FDR 多重检验校正。共同环境差值、置换统计量和 Bootstrap
均使用交易额权重，不使用环境等权均值形成主要结论。报告写入
`report/analysis_algo_*.json`，
每个 Benchmark 末尾包含 `summary`，整份报告末尾包含 `final_summary`。

股票共同覆盖功能可独立运行：

```powershell
python analysis_algo.py --mode stock-overlap
```

结果单独写入 `report/analysis_algo_stock_overlap_*.json`，包含：

- 所有算法＋日期＋股票聚合统计；
- 固定股票算法对的共同交易日、共同记录条数与占比排名；
- 股票＋日期算法对的共同记录条数与占比排名；
- 排名靠前且至少有 5 个共同交易日的固定股票小组配对显著性检验。

共同记录占比定义为 `2 × Σmin(nA, nB) / (ΣnA + ΣnB)`。股票＋日期只有
一个独立日期，因此只输出覆盖统计，不执行日期配对显著性检验。

---

