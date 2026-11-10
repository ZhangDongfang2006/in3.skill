"""最简示例：证明「装好 → in3_cli.py run → 出结果」。当前租户查币种，5 行。"""
import in3_client

in3 = in3_client.IN3()  # 用当前 active 租户（in3_cli.py use <alias> 切换）
page = in3.md.currency.list()
codes = [c["currency_code"] for c in page.items[:5]]
print(f"✅ SDK 跑通：拿到 {len(page.items)} 个币种；前 5 个 = {codes}")
