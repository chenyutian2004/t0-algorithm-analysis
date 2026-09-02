# StockDB 本地接入说明

`market_environment.py` 使用私有模块 `stock_sdk` 中的 `rd` 接口读取个股日行情。
StockDB SDK 不属于本项目的公开 PyPI 依赖，也不随 Git 仓库分发。

## 本地准备

请通过项目所属组织批准的渠道取得以下文件，并确认其版本与本机环境匹配：

- `stock_sdk.py`；
- 与操作系统、CPU 架构及 Python 版本匹配的 `stockdb.pyd`；
- 必要的连接配置或内部服务访问权限。

将 SDK 配置到 Python 可导入路径后，先验证：

```powershell
python -c "from stock_sdk import rd; print('StockDB import OK')"
```

验证成功后，可以在项目根目录更新行情：

```powershell
python main.py market
```

完整流水线为：

```powershell
python main.py all
```

执行顺序是 `import → market → prepare → algo`。

## 数据边界

- `market_environment.py` 负责获取并计算个股行情和市场环境数据。
- 个股行情写入本地 `trade.db` 的 `stock_market_data` 表。
- 市场环境写入本地 `trade.db` 的 `market_environment` 表。
- `prepare.py` 只读取这些既有表并构造 `analysis_record`，不直接调用 StockDB。

## 安全要求

- 不要提交 `stock_sdk.py`、`stockdb.pyd`、访问密码、令牌或内部服务地址。
- 不要通过公开渠道转发私有 SDK 或内部接口文档。
- `.gitignore` 默认忽略 `stockdb/` 内除本 README 外的全部内容。
- 若模块导入或连接失败，请通过组织内部的 StockDB 支持渠道确认授权和版本，不要将凭据写进源代码。
