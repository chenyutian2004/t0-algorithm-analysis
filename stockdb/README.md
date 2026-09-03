# free-stockdb 接入说明

本项目使用 [hello245m/free-stockdb](https://github.com/hello245m/free-stockdb)
提供的本地行情引擎和 Python SDK。上游软件仓库采用 MIT License；行情数据的
版权、使用授权和再分发条件仍由各数据源及权利人决定，不能因为代码开源而默认
数据也可以上传或转发。

## 1. 上游能力与本项目用法

free-stockdb 将行情数据同步、清洗、复权并保存在本机，查询阶段通过本地服务
读取，不依赖逐次远程 API 请求。上游支持日/周/月及多周期分钟行情、批量查询、
复权和多种调用方式。

本 `_T0` 项目只使用其中的 Python 日线查询能力：

```python
from stock_sdk import rd

data = rd.get_data(
    codes,
    start="20260801",
    end="20260807",
    frequency="1d",
    fq=None,
)
```

实际调用位于 `market_environment.py`。项目不会使用 free-stockdb 的私有数据
写入接口保存交易分析结果；本项目数据仍写入自己的 `trade.db`。

## 2. 推荐安装方式

### 方式 A：使用上游 Release（推荐）

1. 打开 [free-stockdb Releases](https://github.com/hello245m/free-stockdb/releases)。
2. 下载与操作系统、CPU 架构和 Python 版本匹配的发行包。
3. 解压到 `_T0` 仓库之外，例如 `C:\Users\65128\Desktop\free-stockdb`。
4. 按上游发行包说明运行数据更新工具，将行情同步到其本地 `./data`。
5. 启动 stockdb 本地服务。
6. 配置 Python SDK，使 `stock_sdk` 可以被当前 Python 解释器导入。

不要把完整 free-stockdb、发行包或行情数据复制进 `_T0/stockdb/`。该目录只保留
本项目的接入说明，并由 `.gitignore` 排除其他本地内容。

### 方式 B：从上游源码配置 Python SDK

上游仓库的 `pybao/` 目录包含 `stock_sdk.py` 和 `安装.py`。`安装.py` 会在
Python 的 site-packages 中创建 `.pth` 文件，把 `pybao` 目录加入 Python
搜索路径。操作前应先阅读脚本，并确保执行脚本的 Python 与运行 `_T0` 的 Python
是同一个解释器。

示例：

```powershell
Set-Location 'C:\Users\65128\Desktop\free-stockdb\pybao'
python 安装.py
```

安装脚本提示完成后，重启终端或 IDE，使 `.pth` 配置生效。

源码中的 Python SDK 仍需要一个已经启动且兼容的 stockdb 本地服务。仅复制
`stock_sdk.py` 并不能替代数据同步和服务启动。

## 3. 启动顺序

根据上游说明，首次使用顺序为：

```text
下载并解压发行包
    ↓
运行数据更新工具，同步数据到 free-stockdb 自己的 ./data
    ↓
启动 stockdb 本地服务
    ↓
验证 Python SDK
    ↓
运行 _T0 的 market 或 all
```

上游说明的默认服务监听地址为 `127.0.0.1:7899`。如使用不同端口或局域网
服务，以实际的上游配置为准；不要把密码、令牌或内部地址写入 Git 仓库。

## 4. Python 环境验证

先确认当前解释器：

```powershell
python -c "import sys; print(sys.executable); print(sys.version)"
```

再验证 SDK 导入：

```powershell
python -c "from stock_sdk import rd; print('stock_sdk import OK')"
```

最后执行一个小范围只读查询。证券代码、日期应替换为本地已经同步的数据范围：

```powershell
python -c "from stock_sdk import rd; print(rd.get_data(['600000'], start='20260801', end='20260807', frequency='1d', fq=None))"
```

预期结果应是以证券代码为键、行情记录列表为值的字典。若返回为空，应依次检查：

- stockdb 服务是否已经启动；
- 本地数据是否已同步到所查询的日期；
- 证券代码是否使用六位纯数字格式；
- SDK 与服务版本是否匹配；
- 当前 Python 是否读取到了正确的 `.pth` 和 `stock_sdk.py`。

## 5. 在 `_T0` 中运行

只更新行情环境：

```powershell
Set-Location 'C:\Users\65128\Desktop\_T0'
python main.py market
```

完整流程：

```powershell
python main.py all
```

执行顺序固定为：

```text
import → market → prepare → algo
```

`market` 阶段会：

1. 从 `trade_record` 确定待查询的证券和日期范围；
2. 证券代码转换成 StockDB 使用的六位纯数字格式；
3. 通过 `rd.get_data(..., frequency="1d", fq=None)` 分批读取行情；
4. 将个股行情保存到本项目 `trade.db` 的 `stock_market_data`；
5. 结合沪深300数据计算并保存 `market_environment`。

随后 `prepare.py` 只读取 `trade_record`、`stock_market_data` 和
`market_environment`，构造 `analysis_record`，不直接调用 StockDB。

## 6. 两套 `data` 目录不要混淆

- `free-stockdb/data`：上游行情引擎的本地行情存储，由上游更新工具维护。
- `_T0/data`：本项目待导入的交易 CSV，由 `database.py` 扫描。

两者用途完全不同。不要把 free-stockdb 的行情数据复制进 `_T0/data`，也不要把
真实交易 CSV 放进 free-stockdb 的行情目录。

## 7. 版本与安全要求

- 优先从上游 Releases 获取发行包，并按上游发布说明核对版本和校验信息。
- 上游说明支持 Windows、macOS、Alpine 和 manylinux；具体资产以 Releases 当前内容为准。
- 不提交 free-stockdb 的本地行情数据、二进制运行文件、配置密码或内部地址。
- 不提交本项目的 `trade.db`、真实交易 CSV、日志和分析报告。
- 团队成员应分别在本机安装并启动 free-stockdb，或使用经过授权的局域网服务。
- 数据许可与软件许可证分开判断；对行情数据的共享和再分发必须遵守数据源条款。

## 8. 上游参考

- [free-stockdb 主仓库](https://github.com/hello245m/free-stockdb)
- [free-stockdb Releases](https://github.com/hello245m/free-stockdb/releases)
- [Python SDK 目录](https://github.com/hello245m/free-stockdb/tree/main/pybao)
- [Python 调用示例](https://github.com/hello245m/free-stockdb/tree/main/%E8%B0%83%E7%94%A8%E6%96%B9%E5%BC%8F/python)
- [MIT License](https://github.com/hello245m/free-stockdb/blob/main/LICENSE)
