# in3_client SDK —— BDD .feature（外环验收 spec）

> 源：[issues](../../../../docs/in3-cli-cemcp/issues/) · [Build-PRD](../../../../docs/in3-cli-cemcp/PRD-v1-c-build.md)
> step defs：[`../tests/step_defs/`](../tests/step_defs/) · 约定：pytest-bdd 8 + zh-CN i18n + 同步栈

2026-06-02 scaffold 4 片 .feature（issue **#1** 脊柱 + **#9** 北极星）；**2026-06-03 step defs 全部填实转绿**（见下「状态」）。

## 已 scaffold 的 feature

| 文件 | 覆盖 issue | 覆盖用户故事（RTM #）|
|---|---|---|
| `in3-client-auth.feature` | #1 | 21, 22, 23（+ 21 fail-loud）|
| `in3-client-envelope.feature` | #1 | 13, 14 |
| `in3-client-md-currency.feature` | #1 | 1, 8, 31 |
| `in3-client-poc-acceptance.feature` | #9 | 7, 32 + Decision Gate（**北极星**）|

## 状态：已转绿（2026-06-03）

4 个 feature 的 step defs 全部填实，绑定已落地的 `in3_client`：

| feature | 结果 |
|---|---|
| envelope | **9 passed**（五信封 unwrap / total 不可信置 None / has_next 优先 last + 启发式 / iterate_all 不按 total + 封顶 truncated）|
| auth | **5 passed**（AES 串直发不解密 / 三鉴权头 / 401 重试一次 / 200 非 JSON 判认证失败 / 缺凭证 fail-loud）|
| md_currency | **4 passed**（import 直跑 A surface / 脊柱端到端 / CLI parity 逐位（录制 fixture）/ 不做 156↔CNY 归一）|
| poc | **2 passed + 5 skipped**（离线可跑：partial 失败 fail-loud、孤儿保留；skip：Top10 parity / token 降幅 / doctor BARS / M4 裁决需 zhuzheng 凭证或 HITL）|

合计 **20 passed + 5 skipped**。step defs 在 `tests/step_defs/`，共享桩 `_support.py`（FakeTransport + IN3 构造），fixture 在 `conftest.py`（mock_uaas_token / recorded_backend / cli_runner）。

> 偏离 generate-bdd-skeleton 的「至少 1 个 scenario 可跑」DoD 已消除：所有离线 scenario 均真跑、非空断言；仅凭证/HITL 依赖项 skip 并注明原因。

## 跑

BDD 外环依赖 pytest-bdd（主单测内环不依赖）。用独立 venv 跑，不污染全局 anaconda：

```
cd engineering/skills/in3-cli/sdk
python3 -m venv .venv-bdd
./.venv-bdd/bin/pip install pytest pytest-bdd && ./.venv-bdd/bin/pip install -e .
./.venv-bdd/bin/python -m pytest tests/step_defs/ -q      # BDD 外环：20 passed + 5 skipped
# 选装 pandas（从自带 wheelhouse 离线装）→ venv 可跑全套：
./.venv-bdd/bin/pip install --no-index --find-links ../vendor/python pandas
./.venv-bdd/bin/python -m pytest -q                        # 全套：695 passed + 5 skipped
```

> 主 fast 内环仍走 anaconda/系统 python：`python3 -m pytest`（pytest-bdd 缺失时 `conftest.py` 的 `collect_ignore_glob` 自动跳过 step_defs，675 passed）。`.venv-bdd/` 已 gitignore。

## 下一步

- **poc 5 个 skip 转绿**：需 zhuzheng 凭证（Top10 parity / token 测量）、另起 in3-cli-doctor（BARS）、或人裁决（M4）——HITL，非离线可补。
- **RTM**：scenario 已按 Build-PRD 用户故事号标 `RTM #N`；用 `/build-rtm` 串 issues(PRD) ↔ .feature ↔ tests 的 5 列追溯表（ADR-0001 BDD 锚定）。
