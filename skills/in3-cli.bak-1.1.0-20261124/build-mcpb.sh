#!/usr/bin/env bash
# 构建 in3-mcp 的 Claude Desktop 桌面扩展（.mcpb，配置壳）。
# 用法: bash engineering/skills/in3-cli/build-mcpb.sh
# 产物: engineering/skills/in3-cli/dist/in3-mcp.mcpb（dist/ 已 gitignore，是 build artifact）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/mcpb"          # 被打包的单元（只含 manifest.json + launcher.py；文档在 MCP-SERVER.md §8.5）
OUT_DIR="$HERE/dist"
OUT="$OUT_DIR/in3-mcp.mcpb"
MCPB="npx --yes @anthropic-ai/mcpb@latest"

mkdir -p "$OUT_DIR"

echo "==> validate manifest"
$MCPB validate "$SRC/manifest.json"

echo "==> pack -> $OUT"
$MCPB pack "$SRC" "$OUT"

echo "==> info"
$MCPB info "$OUT"

echo "✅ built: $OUT"
echo "   安装: Claude Desktop → Settings → Extensions → 选这个 .mcpb，按向导填 in3_cli.py 路径 + python 路径。"
