# PRD: @industics/in3-cli-all-in-one

> 状态：暂停（Slice 7/11 完成，63%）
> GitLab issue: [#31](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/31)
> 源码已归档，恢复时从本文档接续。

## 目标

Node TypeScript 重写 in3-cli 调度层，把 8 个 module CLI 写作 npm dependencies，让用户 `npm i -g @industics/in3-cli-all-in-one` 一条装齐 9 binary。**不替代**现有 Python in3-cli skill，物理隔离共存。

## 已完成 Slice（1-7）

| # | Slice | issue | 说明 |
|---|---|---|---|
| 1 | Skeleton | [#32](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/32) | package.json + tsconfig + commander 入口 + 20 命令 stub |
| 2 | WorkspaceManager | [#33](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/33) | init/where/uninstall |
| 3 | TenantStore | [#34](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/34) | use/tenants |
| 4 | CredentialVault | [#35](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/35) | AES-128-ECB + 黄金 fixture |
| 5 | NpmController | [#36](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/36) | install*/upgrade*/status |
| 6 | ModuleDriver | [#37](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/37) | login（非交互）/sync/logout |
| 7 | exec shell | [#38](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/38) | exec + 多租户 use 端到端 |

## 剩余 Slice（8-11）

| # | Slice | issue | 说明 |
|---|---|---|---|
| 8 | 版本缓存 + doctor | [#39](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/39) | NpmController.latestVersion + cache TTL 2h + doctor shell |
| 9 | test / test-all | [#40](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/40) | 独立 verb 包装 ModuleDriver.runSmoke |
| 10 | migrate-from-python | [#41](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/41) | 检测 ~/in3-workspace 并搬迁 cred + config |
| 11 | README + publish [HITL] | [#42](http://gitlab-os.industics.cn:9098/skills/ind-skills/-/issues/42) | status schema 冻结 + pack-vendor + npm publish 1.0.0 |

## 技术设计

### 依赖的 8 个 module CLI

| key | binary | npm 包 | env var | profile 目录 |
|---|---|---|---|---|
| mm | ibrain-mm-cli | @industics/ibrain-mm-cli | IBRAIN_MM_CONFIG_DIR | .ibrain-mm |
| wm | ibrain-wm-cli | @industics/ibrain-wm-cli | IBRAIN_WM_CONFIG_DIR | .ibrain-wm |
| md | in-mom-md-cli | @industics/in-mom-md-cli | IN_MOM_MD_CONFIG_DIR | .in-mom-md |
| pp | ibrain-pp-cli | @industics/ibrain-pp-cli | IBRAIN_PP_CONFIG_DIR | .ibrain-pp |
| qm | ibrain-qm-cli | @industics/in-mom-qm-cli | IBRAIN_QM_CONFIG_DIR | .ibrain-qm |
| sd | ibrain-sd-cli | @industics/ibrain-sd-cli | IBRAIN_SD_CONFIG_DIR | .ibrain-sd |
| cr | in-mom-cr-cli | @industics/in-mom-cr-cli | IN_MOM_CR_CONFIG_DIR | .in-mom-cr |
| fn | ibrain-mom-fn-cli | @industics/ibrain-mom-fn-cli | IBRAIN_MOM_FN_CONFIG_DIR | .ibrain-mom-fn |

已知坑：
- qm 的 binary 是 `ibrain-qm-cli`，但 npm 包是 `@industics/in-mom-qm-cli`（历史包名错位）
- md / cr 的 env var 用 `IN_MOM_` 前缀（不是 `IBRAIN_`）

### 架构

```
src/
├── cli.ts                  # commander 入口, 20 命令注册
├── modules/
│   ├── workspace.ts        # workspace 生命周期
│   ├── tenants.ts          # 多租户存储
│   ├── crypto.ts           # AES-128-ECB
│   ├── npm.ts              # npm install/upgrade
│   ├── driver.ts           # 模块 login/exec/smoke
│   ├── modules.ts          # 8 模块注册表
│   └── prompt.ts           # TTY prompt + stdin pipe
└── commands/               # 每个命令一个文件
```

### 测试

Slice 1-7 共 36 个 vitest 用例（workspace 9 / tenants 11 / crypto 6 / npm 4 / driver 6）。

## 已验证的端到端流程

- workspace 生命周期：init → where → uninstall
- 非交互 login（Codex sandbox 风格）：--password-stdin + 8 模块 fanout + smoke
- 多租户切换：login 两个 tenant → tenants → use 切换 → exec 验证数据隔离
- sync + logout
- 边界 case：缺 flag 早报、--password 与 --password-stdin 互斥、--env custom 缺 --api-host

## 风险/未决

1. 未跑 `npm i -g <tarball>` 全局装载验证（避免污染本机），publish 后需端到端 verify
2. install-in3-cli skill 依赖此包 publish 后才真正能用
3. Python skill 共存时 workspace 路径物理隔离没冲突，但同时跑两套的体验未专门验证
