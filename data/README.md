# 数据目录说明

本目录用于放置本地待导入的交易 CSV。真实交易数据不得提交到 GitHub。

## 本地数据放置

将待导入 CSV 直接放在 `data/` 根层，例如：

```text
data/
├── README.md
├── algo_20260901.csv       # 本地真实数据，不提交
└── sample/
    └── algo_sample.csv     # 可选的脱敏协作样例
```

`database.py` 默认只扫描 `data/` 根层的 `*.csv`；不会递归导入
`data/sample/` 或其他子目录。

增量导入命令：

```powershell
python main.py import
```

完整流水线命令：

```powershell
python main.py all
```

## CSV 必需字段

CSV 需要包含以下中文列名：

```text
任务ID
客户号
账号类型
资金账号
算法类型
交易日期
买入类型
证券代码
证券名称
交易结果
交易进度
授权持仓量
实际底仓
总买量
总买金额
买入均价
总卖量
总卖金额
卖出均价
今日交易额
实际底仓的市值
当日盈亏金额
日收益率%
母单状态
是否GRT
```

字段映射和基础类型清洗统一定义在 `schema.py`；导入及 SQLite 增量写入由
`database.py` 完成。

## Git 与脱敏要求

`.gitignore` 默认忽略 `data/` 下的所有内容，只允许提交：

- `data/README.md`；
- `data/sample/` 下经过确认的脱敏样例。

脱敏样例至少应满足：

- 替换 `task_id`、`customer_id`、`account_id` 等标识符；
- 不包含姓名、联系方式或其他身份信息；
- 缩减交易条数和日期范围；
- 保留字段结构、数据类型和必要边界情况；
- 经项目负责人确认不存在客户或交易策略泄露风险后再提交。

GitHub 仓库不是本项目真实交易数据的共享渠道。真实数据应通过所属组织批准的
受控存储或内部数据服务提供。
