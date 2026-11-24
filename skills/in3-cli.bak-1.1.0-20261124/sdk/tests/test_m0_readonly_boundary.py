"""M0 基座②单测：只读边界守护 —— 本片引入的基座 helper 不产任何写方法。

结构性钉死：SDK 只产 list/get/query/summary/info/items/lines/details/pending 等读方法，
绝不生成 create / update / delete / post-write。对承载 M0 基座 helper 的模块断言 not hasattr。
"""
import in3_client.gotchas as gotchas
import in3_client.http as http_mod
from in3_client.http import HttpClient

_WRITE_NAMES = ("create", "update", "delete", "post_write", "save", "insert", "remove", "patch", "put")


def test_http_client_has_no_write_methods():
    for name in _WRITE_NAMES:
        assert not hasattr(HttpClient, name), f"HttpClient must not expose write verb: {name}"


def test_gotchas_module_has_no_write_helpers():
    for name in _WRITE_NAMES:
        assert not hasattr(gotchas, name), f"gotchas must not expose write verb: {name}"


def test_new_m0_symbols_are_read_path_only():
    # enrich_items_fanout 名字里不含写动词；只挂行项（读）
    assert hasattr(gotchas, "enrich_items_fanout")
    fn_name = gotchas.enrich_items_fanout.__name__
    assert not any(w in fn_name for w in ("create", "update", "delete", "write", "save"))


def test_http_request_method_only_get_post_read_path():
    # _request 是共享读管线；HttpClient 暴露的公共数据动词均为读
    public = [n for n in dir(HttpClient) if not n.startswith("_")]
    for w in ("create", "update", "delete"):
        assert w not in public
