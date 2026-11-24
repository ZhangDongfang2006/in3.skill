# 给 in3-cli 加新模块的 5 步

skill 设计是开口的。新模块上线时（例如 wm-cli 要接入），按下面 5 步走，10 分钟搞定。

## 1. 拿到包名 + 二进制名

从模块仓的 `apps/cli/package.json` 看 `name`（npm 包名，通常 `@industics/ibrain-<mod>-cli`）和 `bin`（二进制名，通常 `ibrain-<mod>-cli`）。

## 2. 摸清命令能力

```bash
npm i -g @industics/ibrain-<mod>-cli
ibrain-<mod>-cli __schema | jq '.commands | keys'
```

把命令列表抄到 `references/modules.md` 新加的"### `<mod>`"小节，每条命令写一句业务用途 + 关键 flag。

## 3. 选 smoke 命令

挑一个：
- **不需要 plant_id 或 material_id 等业务参数**
- **租户级唯一**（不依赖工厂归属，任何 onboard 后的账号都能拿到非空数据）
- **响应小**（< 1KB，避免污染上下文）

mm 选的是 `currency list`。wm 备选可能是 `warehouse list` 或类似的全租户仓库清单。

跑一下验证：

```bash
ibrain-<mod>-cli <smoke-cmd>
# 应该看到 {"items":[...],"page":0,"total":...} 形态的 JSON
```

## 4. 在 MODULES dict 加一项

编辑 `scripts/in3_cli.py` 顶部的 `MODULES`：

```python
MODULES = {
    "mm": {...},
    "<mod>": {
        "npm_package": "@industics/ibrain-<mod>-cli",
        "binary": "ibrain-<mod>-cli",
        "config_dir": Path.home() / ".ibrain-<mod>",
        "base_suffix": "/mom/<mod>",  # 从 ibrain-<mod>/apps/cli/src/config/env.ts 找 default base_url
        "smoke_cmd": ["<smoke-subcmd>", ...],
        "smoke_desc": "<中文一句话描述>",
        "supports_plaintext_password": False,  # 或 True,实际不影响逻辑（skill 总是传密文）
    },
}
```

`base_suffix` 用法：`base_url = api_host.rstrip('/') + base_suffix`。`api_host` 已经带 `/service`，所以 `base_suffix` 从 `/mom/...` 起头。

## 5. 把主凭证落到新模块的 profile

最简单的办法：重跑 `login` 一次。

```bash
python3 ${SKILL_DIR}/scripts/in3_cli.py login
```

`fanout_profile_to_modules` 会遍历 MODULES，对每个已装的 binary 写一份 `in3` profile。新模块这次就被覆盖到。

如果用户不想重新输密码，可以加一个 `--reonboard <mod>` 子命令，从主凭证直接派生新模块 profile（v1 没做，v1.1 可加）。

---

## 验证清单（接入新模块后）

- [ ] `status` 子命令列出新模块
- [ ] `install <mod>` 能装上
- [ ] `login` 走完后，`~/.ibrain-<mod>/config.json` 里有 `in3` profile
- [ ] `test <mod>` 输出 `ok: true` + 真实 sample
- [ ] `test-all` 把新模块计入 PASS

## 别忘了同步文档

- `references/modules.md` 新增"### `<mod>`"小节
- `SKILL.md` 不用改（已经按 MODULES 注册表泛化）
- 如果新模块有非标准约定（如不同的鉴权前缀、不同的 base_url 结构），在 `references/modules.md` 那一节注明
