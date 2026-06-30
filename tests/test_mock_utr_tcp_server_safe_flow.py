# -*- coding: utf-8 -*-
"""mock TCPサーバーの安全な応答範囲を確認するテスト。

このテストはソケット通信を行いません。
responses_for_request() を直接呼び出し、LAN版サンプルの机上確認に必要な
読み取り系コマンドへ応答できることと、SET系コマンドをACKしないことを確認します。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_SERVER_PATH = REPO_ROOT / "tools" / "mock_utr_tcp_server.py"


def load_mock_server_module():
    spec = importlib.util.spec_from_file_location("mock_utr_tcp_server", MOCK_SERVER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mock_server_supports_safe_read_flow_commands():
    module = load_mock_server_module()

    safe_requests = [
        module.ROM_VERSION_REQUEST,
        module.UHF_READ_OUTPUT_POWER_REQUEST,
        module.UHF_READ_FREQ_CH_REQUEST,
        module.UHF_GET_INVENTORY_PARAM_REQUEST,
        module.UHF_INVENTORY_REQUEST,
    ]

    for request in safe_requests:
        responses = module.responses_for_request(request, "one-tag")
        assert responses, f"no mock response for {module.format_hex(request)}"
        for response in responses:
            parsed = module.parse_frame(response)
            assert parsed.command in {module.ACK, module.RF_TAG_DATA}


def test_mock_server_does_not_ack_set_inventory_param():
    module = load_mock_server_module()

    responses = module.responses_for_request(module.UHF_SET_INVENTORY_PARAM_REQUEST, "one-tag")

    assert len(responses) == 1
    parsed = module.parse_frame(responses[0])
    assert parsed.command == module.NACK
