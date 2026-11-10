"""C 执行壳的**传输无关执行核** + audit（issue #2）。

唯一强约束：execute 核与 argparse 壳分离——超时/截断/审计全在核里，cmd_run 只做解析+装配+透传。
v2 的 MCP execute_code 可零返工复用本核（同 ExecuteContext/ExecuteResult）。

不 import argparse、不读 sys.argv、不调 dispatcher 的 _require_* —— 那些在 cmd_run 壳里做。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

DEFAULT_TIMEOUT_S = 300
DEFAULT_OUTPUT_CAP = 65536  # 64KB
AUDIT_KEEP = 100
_TIMEOUT_EXIT = 124
_TRUNC_MARK = "[TRUNCATED@64KB]"


@dataclass
class ExecuteContext:
    workspace: Path
    tenant_alias: str
    env: dict
    pythonpath: List[str]
    timeout_s: int = DEFAULT_TIMEOUT_S
    output_cap_bytes: int = DEFAULT_OUTPUT_CAP
    audit: bool = True
    script_args: List[str] = field(default_factory=list)


@dataclass
class ExecuteResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    truncated: bool


def _truncate(s: str, cap: int) -> tuple[str, bool]:
    """按**字节**截断（多字节 UTF-8 边界用 errors='ignore' 不产生半截非法字节）。"""
    if s is None:
        return "", False
    b = s.encode("utf-8")
    if len(b) <= cap:
        return s, False
    return b[:cap].decode("utf-8", errors="ignore") + _TRUNC_MARK, True


def _build_subprocess_env(ctx: ExecuteContext) -> dict:
    env = dict(ctx.env)
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in ctx.pythonpath if p]
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def execute(script_path: Optional[str], code: Optional[str], ctx: ExecuteContext) -> ExecuteResult:
    """在子进程跑脚本/内联代码，注入 env+PYTHONPATH，带超时/截断/审计。

    script_path 与 code 互斥（都给时 code 优先）；两者皆 None → 报错（不静默空跑）。
    超时 → exit_code=124；输出超 cap → truncated=True 且末尾标 [TRUNCATED@64KB]。
    """
    if code is None and script_path is None:
        raise ValueError("execute: 必须给 script_path 或 code 其一")

    env = _build_subprocess_env(ctx)
    if code is not None:
        cmd = [sys.executable, "-c", code]
        source = code
    else:
        cmd = [sys.executable, script_path]
        try:
            source = Path(script_path).read_text(encoding="utf-8")
        except OSError:
            source = f"<unreadable script: {script_path}>"
    cmd += list(ctx.script_args)

    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=ctx.timeout_s)
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = (e.stderr or "") + f"\n[in3-cli] script exceeded timeout {ctx.timeout_s}s"
        rc = _TIMEOUT_EXIT
        timed_out = True
    duration = round(time.monotonic() - start, 3)

    out_t, t1 = _truncate(stdout, ctx.output_cap_bytes)
    err_t, t2 = _truncate(stderr, ctx.output_cap_bytes)
    result = ExecuteResult(stdout=out_t, stderr=err_t, exit_code=rc, duration_s=duration, truncated=t1 or t2)

    if ctx.audit:
        _write_audit(ctx, source, result, timed_out)
    return result


# ---------- audit ----------

def _audit_dir(ctx: ExecuteContext) -> Path:
    return ctx.workspace / "audit"


def _write_audit(ctx: ExecuteContext, source: str, result: ExecuteResult, timed_out: bool) -> Path:
    d = _audit_dir(ctx)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    short = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    path = d / f"{ts}_{short}.json"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant": ctx.tenant_alias,
        "script_source": source,
        "exit_code": result.exit_code,
        "duration_s": result.duration_s,
        "stdout_excerpt": result.stdout,
        "stderr_excerpt": result.stderr,
        "output_truncated": result.truncated,
        "timed_out": timed_out,
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    _rotate_audit(d)
    return path


def _rotate_audit(d: Path) -> None:
    """仅保留最近 AUDIT_KEEP 个本格式审计文件（按文件名 ISO 时间戳排序删最旧；不误删他格式）。"""
    files = sorted(p for p in d.glob("*.json") if "_" in p.stem)
    excess = len(files) - AUDIT_KEEP
    for p in files[:max(0, excess)]:
        try:
            p.unlink()
        except OSError:
            pass
