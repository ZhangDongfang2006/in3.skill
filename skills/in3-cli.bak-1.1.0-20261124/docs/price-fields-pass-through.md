# IN3-CLI 价格字段原样输出

## 当前行为

从调度器 v1.3.0 开始，`exec` 不再检查 `price_viewer`（价格查看角色），也不再对模块返回结果做价格字段删除。

- `fn` 财务模块直接执行。
- `mm info-record`、`mm quotation`、`sd sd-info-record`、`sd quotation`、`cr fee` 直接执行。
- 销售订单、采购订单等结果中的 `price`、`amount`、`cost`、`fee`、`charge`、`discount`、`margin`、`tax` 字段原样输出。
- 旧文件 `.price-privilege-cache.json` 不再读取；可以保留，不影响运行。

## 安全边界

这次升级只删除本地 Python 调度器的二次过滤。IN3 服务端仍是最终数据来源：

- 服务端返回金额，调度器原样输出。
- 服务端返回 401、403 或其他错误，调度器原样显示错误。
- 调度器不会伪造金额、补空字段或把拒绝改成成功。

如果以后仍需要对终端用户限制金额，应在 IN3 服务端实现，不能依赖用户电脑上的本地脚本。

## 验证命令

```bash
python3 scripts/in3_cli.py version
python3 scripts/in3_cli.py exec sd sales-order list --all
python3 scripts/in3_cli.py exec fn company-code list
```

验收时只检查“调度器没有再删除字段”。业务接口是否返回金额，仍取决于租户数据和服务端行为。
