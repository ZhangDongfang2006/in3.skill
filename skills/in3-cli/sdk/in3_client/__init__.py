"""in3_client —— IN3 只读 Python SDK（直连 HTTP，不 wrap CLI）。

见 docs/in3-cli-cemcp/PRD-v1-c-build.md / ADR-0002 / ADR-0003。
覆盖 md/mm/wm/sd/pp/qm/cr/fn/sf，SIM 支持全量列表及完整详情。
"""
from .facade import IN3
from .auth import AuthFailedError, TokenExpiredError

__version__ = "1.3.0"

__all__ = ["IN3", "AuthFailedError", "TokenExpiredError"]
