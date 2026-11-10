"""in3_client —— IN3 只读 Python SDK（直连 HTTP，不 wrap CLI）。

见 docs/in3-cli-cemcp/PRD-v1-c-build.md / ADR-0002 / ADR-0003。
v1 小切片：mm/wm/sd/md 7 个 entity。
"""
from .facade import IN3

__all__ = ["IN3"]
