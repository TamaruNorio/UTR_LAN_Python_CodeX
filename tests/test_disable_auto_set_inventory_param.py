# -*- coding: utf-8 -*-
"""LAN版サンプルの安全方針を確認するテスト。

このテストは実機通信を行いません。
通常実行フローで UHF_SET_INVENTORY_PARAM を自動送信しないことを、
main() のソースから確認します。
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = REPO_ROOT / "src" / "UTR_LAN_sample_1.0.0.py"


def load_lan_sample_module():
    spec = importlib.util.spec_from_file_location("utr_lan_sample", SAMPLE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_reads_inventory_param_but_does_not_set_it_automatically():
    module = load_lan_sample_module()
    main_source = inspect.getsource(module.main)

    assert "COMMANDS['UHF_GET_INVENTORY_PARAM']" in main_source
    assert "COMMANDS['UHF_SET_INVENTORY_PARAM']" not in main_source


def test_set_inventory_param_command_definition_is_not_removed():
    module = load_lan_sample_module()

    # 定義は残してよい。ただし通常実行フローから自動送信しないことが安全条件。
    assert "UHF_SET_INVENTORY_PARAM" in module.COMMANDS
    assert isinstance(module.COMMANDS["UHF_SET_INVENTORY_PARAM"], bytes)
