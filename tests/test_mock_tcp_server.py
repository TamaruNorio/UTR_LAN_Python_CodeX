from importlib import util
from pathlib import Path
import sys

import pytest


@pytest.fixture(scope="module")
def mock_server():
    repo_root = Path(__file__).resolve().parents[1]
    server_path = repo_root / "tools" / "mock_utr_tcp_server.py"
    spec = util.spec_from_file_location("mock_utr_tcp_server", server_path)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rom_version_request_returns_protocol_example_response(mock_server):
    responses = mock_server.responses_for_request(
        mock_server.ROM_VERSION_REQUEST,
        "one-tag",
    )

    assert responses == [mock_server.ROM_VERSION_RESPONSE]


def test_ram_command_mode_set_returns_ack(mock_server, utr_sample):
    responses = mock_server.responses_for_request(
        utr_sample.COMMANDS["COMMAND_MODE_SET"],
        "one-tag",
    )

    assert responses == [mock_server.COMMAND_MODE_ACK]


def test_inventory_one_tag_scenario_returns_tag_response_then_done_ack(mock_server):
    responses = mock_server.responses_for_request(
        mock_server.UHF_INVENTORY_REQUEST,
        "one-tag",
    )

    assert responses == [
        mock_server.INVENTORY_TAG_RESPONSE,
        mock_server.INVENTORY_DONE_ONE_TAG,
    ]


def test_inventory_no_tag_scenario_returns_done_ack_only(mock_server):
    responses = mock_server.responses_for_request(
        mock_server.UHF_INVENTORY_REQUEST,
        "no-tag",
    )

    assert responses == [mock_server.INVENTORY_DONE_NO_TAG]


@pytest.mark.parametrize("scenario", ["no-tag", "one-tag", "force-nack"])
def test_invalid_sum_returns_sum_error_nack_in_every_scenario(mock_server, scenario):
    invalid_sum_request = (
        mock_server.ROM_VERSION_REQUEST[:-2]
        + bytes([mock_server.ROM_VERSION_REQUEST[-2] ^ 0xFF])
        + mock_server.ROM_VERSION_REQUEST[-1:]
    )

    responses = mock_server.responses_for_request(invalid_sum_request, scenario)

    assert len(responses) == 1
    nack = responses[0]
    assert nack[2] == mock_server.NACK
    assert nack[3] == 0x0A
    assert nack[5] == mock_server.ERROR_SUM


def test_force_nack_returns_mock_specific_format_error_for_supported_command(mock_server):
    responses = mock_server.responses_for_request(
        mock_server.ROM_VERSION_REQUEST,
        "force-nack",
    )

    assert len(responses) == 1
    nack = responses[0]
    assert nack[2] == mock_server.NACK
    assert nack[3] == 0x0A
    assert nack[5] == mock_server.ERROR_FORMAT


def test_unsupported_command_has_no_response_in_normal_scenario(mock_server):
    # 0x7F は、このmockサーバーで対応していない任意のコマンド番号です。
    # 0x42 はブザーコマンドとして対応対象にしたため、unsupported用途には使いません。
    unsupported = mock_server.build_frame(0x7F, bytes([0x01, 0x00]))

    assert mock_server.responses_for_request(unsupported, "one-tag") == []


def test_force_nack_returns_mock_specific_nack_for_unsupported_command(mock_server):
    # 0x7F は、このmockサーバーで対応していない任意のコマンド番号です。
    unsupported = mock_server.build_frame(0x7F, bytes([0x01, 0x00]))

    responses = mock_server.responses_for_request(unsupported, "force-nack")

    assert len(responses) == 1
    assert responses[0][2] == mock_server.NACK
    assert responses[0][5] == mock_server.ERROR_FORMAT


def test_parse_args_defaults_to_localhost_9004_one_tag(mock_server):
    args = mock_server.parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 9004
    assert args.scenario == "one-tag"


def test_parse_args_rejects_0_0_0_0(mock_server):
    with pytest.raises(SystemExit):
        mock_server.parse_args(["--host", "0.0.0.0"])
