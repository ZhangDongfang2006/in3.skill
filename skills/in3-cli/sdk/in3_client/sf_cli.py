"""由 in3_cli.py exec sf 调用的薄 CLI，直接复用 SDK 的鉴权及查询逻辑。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from . import IN3, __version__
from .auth import AuthFailedError
from .config import MissingCredentialsError
from .entities.sf import validate_filters
from .http import HttpError
from .sf_schema import SF_FILTERS, capability, schema


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parser() -> Parser:
    parser = Parser(add_help=False)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--tenant")
    entities = parser.add_subparsers(dest="entity", required=True)
    issue = entities.add_parser("sim-issue", add_help=False)
    verbs = issue.add_subparsers(dest="verb", required=True)
    listing = verbs.add_parser("list", add_help=False)
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--page", type=int, default=0)
    listing.add_argument("--size", type=int, default=100)
    listing.add_argument("--max", type=int, dest="max_items")
    listing.add_argument("--max-pages", type=int, default=1000)
    listing.add_argument("--filter", action="append", default=[])
    listing.add_argument("--include-details", action="store_true")
    listing.add_argument("--output", type=Path)
    get = verbs.add_parser("get", add_help=False)
    get.add_argument("id")
    get.add_argument("--output", type=Path)
    return parser


def _scalar(value: object, kind: str) -> object:
    if kind == "integer":
        if isinstance(value, bool) or not str(value).lstrip("-").isdigit():
            raise ValueError("integer 筛选值必须是整数")
        return int(value)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).lower() not in ("true", "false"):
            raise ValueError("boolean 筛选值必须是 true/false")
        return str(value).lower() == "true"
    return value


def _filters(expressions: list[str]) -> dict:
    result = {}
    for expression in expressions:
        name, separator, text = expression.partition("=")
        if not separator or name not in SF_FILTERS:
            raise ValueError(f"无效 --filter：{expression}；请查看 __schema.filter_keys")
        spec = SF_FILTERS[name]
        if not spec["multi"] and name in result:
            raise ValueError(f"{name} 只接受单值，不能重复")
        if spec["multi"]:
            values = json.loads(text) if text.startswith("[") else [text]
            if not isinstance(values, list):
                raise ValueError(f"{name} 必须为数组")
            result.setdefault(name, []).extend(_scalar(value, spec["type"]) for value in values)
        else:
            result[name] = _scalar(text, spec["type"])
    validate_filters(result)
    return result


def _write_output(path: Path, payload: dict) -> dict:
    # 排他创建避免覆盖已有导出；权限 0600，完整内容不经 run 的 64KB 输出通道。
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError(f"导出文件已存在：{path}；请使用新文件名") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"output": str(path.resolve()), "count": len(payload.get("items", [payload])),
            "has_next": payload.get("has_next", False), "truncated": payload.get("truncated", False)}


def _error(exc: Exception) -> tuple[dict, int]:
    status = exc.status if isinstance(exc, HttpError) else None
    if isinstance(exc, HttpError):
        kind, code = {401: ("AUTH_FAILED", 2), 403: ("FORBIDDEN", 2),
                      404: ("NOT_FOUND", 3)}.get(status, ("SERVER", 5) if status >= 500
                                                else ("VALIDATION", 4))
    elif isinstance(exc, (AuthFailedError, MissingCredentialsError)):
        kind, code = "AUTH_FAILED", 2
    elif isinstance(exc, ValueError):
        kind, code = "VALIDATION", 4
    elif isinstance(exc, OSError) or type(exc).__module__.startswith("requests"):
        kind, code = "NETWORK", 5
    else:
        kind, code = "UNKNOWN", 1
    return {"error": {"type": kind, "message": str(exc), "http_status": status}}, code


def main(argv: list[str] | None = None) -> int:
    """执行 SIM 查询；成功及失败均在 stdout 返回合法 JSON。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--capability"]:
        print(json.dumps(capability(__version__), ensure_ascii=False))
        return 0
    if not argv or argv in (["__schema"], ["--help"]):
        print(json.dumps(schema(__version__), ensure_ascii=False))
        return 0
    if argv == ["--version"]:
        print(json.dumps({"name": "in3-sf", "version": __version__}))
        return 0
    try:
        args = _parser().parse_args(argv)
        filters = _filters(args.filter) if args.verb == "list" else None
        entity = IN3(workspace=args.workspace, tenant=args.tenant).sf.sim_issue
        if args.verb == "list":
            payload = asdict(entity.list(filter=filters, all=args.all, page=args.page, size=args.size,
                                         max_items=args.max_items, max_pages=args.max_pages,
                                         include_details=args.include_details))
        else:
            payload = entity.get(args.id)
        if args.output:
            payload = _write_output(args.output, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        payload, code = _error(exc)
        print(json.dumps(payload, ensure_ascii=False))
        return code


if __name__ == "__main__":
    sys.exit(main())
