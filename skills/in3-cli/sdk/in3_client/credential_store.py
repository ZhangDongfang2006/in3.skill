"""token 续期的租户级文件锁与原子写入；不保存或输出明文口令。"""
from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def _lock(file) -> None:
    if os.name == "nt":
        import msvcrt
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def locked_credentials(path: Path):
    """刷新操作互斥（最多等待 10 秒）；进程退出时由操作系统释放锁。"""
    fd = os.open(path.with_suffix(".refresh.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"\0")
            lock.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                _lock(lock)
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("等待 token 刷新锁超时") from None
                time.sleep(0.05)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("无效凭证文件")
            yield data
        finally:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_UN)


def save_refreshed_token(path: Path, original: dict, token) -> None:
    """保留凭证其他字段，原子落盘轮换结果；拒绝覆盖刷新期间的新登录。"""
    if json.loads(path.read_text(encoding="utf-8")) != original:
        raise ValueError("刷新期间凭证已改变，请重新执行命令")
    updated = dict(original, access_token=token.access_token, refresh_token=token.refresh_token,
                   tenant_id=token.tenant_id, user_id=token.user_id)
    fd, name = tempfile.mkstemp(prefix=".token-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(updated, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
