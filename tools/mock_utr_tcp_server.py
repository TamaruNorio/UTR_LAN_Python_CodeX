#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Mock TCP server for the UTR LAN sample.

This tool listens on localhost by default and returns fixed protocol frames for
pre-real-device checks. It is not an emulator of all real-device behavior.
"""

from __future__ import annotations

import argparse
import socket
from dataclasses import dataclass
from typing import Iterable, List, Optional


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9004
DEFAULT_SCENARIO = "one-tag"
SCENARIOS = ("no-tag", "one-tag", "force-nack")

STX = 0x02
ETX = 0x03
CR = 0x0D
ACK = 0x30
NACK = 0x31
RF_TAG_DATA = 0x6C
BUZZER = 0x42

ERROR_SUM = 0x42
ERROR_FORMAT = 0x44

ROM_VERSION_REQUEST = bytes.fromhex("02 00 4F 01 90 03 E5 0D")
ROM_VERSION_RESPONSE = bytes.fromhex(
    "02 00 30 0A 90 31 31 30 30 55 53 4D 30 31 03 E7 0D"
)
COMMAND_MODE_ACK = bytes.fromhex("02 00 30 00 03 35 0D")
UHF_INVENTORY_REQUEST = bytes.fromhex("02 00 55 01 10 03 6B 0D")
UHF_READ_OUTPUT_POWER_REQUEST = bytes.fromhex("02 00 55 03 43 01 00 03 A1 0D")
UHF_READ_FREQ_CH_REQUEST = bytes.fromhex("02 00 55 03 43 02 00 03 A2 0D")
UHF_GET_INVENTORY_PARAM_REQUEST = bytes.fromhex("02 00 55 02 41 00 03 9D 0D")
UHF_SET_INVENTORY_PARAM_REQUEST = bytes.fromhex(
    "02 00 55 09 30 00 81 00 00 00 00 00 00 03 14 0D"
)

# 送信出力読み取りの固定応答です。
# サンプル側は result[7] / result[8] を見て dBm 表示するため、
# 0x00F0 = 240 -> 24.0 dBm 相当の値を返します。
UHF_READ_OUTPUT_POWER_RESPONSE = build_frame_placeholder = None

INVENTORY_TAG_RESPONSE = bytes.fromhex(
    "02 00 6C 13 09 FF 12 30 0E 30 00 E2 80 11 00 20 00 39 46 A5 F0 0F 5A 03 1C 0D"
)
INVENTORY_DONE_ONE_TAG = bytes.fromhex("02 00 30 05 10 00 01 00 1A 03 65 0D")
INVENTORY_DONE_NO_TAG = bytes.fromhex("02 00 30 05 10 00 00 00 1A 03 64 0D")


@dataclass(frozen=True)
class ParsedFrame:
    raw: bytes
    address: int
    command: int
    data: bytes


def format_hex(data: bytes) -> str:
    return data.hex(" ").upper()


def calculate_sum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_frame(command: int, data: bytes = b"", address: int = 0x00) -> bytes:
    body = bytes([STX, address, command, len(data)]) + data + bytes([ETX])
    return body + bytes([calculate_sum(body), CR])


def build_nack(detail: int, error_code_1: int, address: int = 0x00) -> bytes:
    data = bytes([detail, error_code_1, 0x00, 0x00, 0x00]) + (b"\x00" * 5)
    return build_frame(NACK, data, address=address)


# build_frame() 定義後に固定応答を生成します。
# ここで返す値は mock 用の安全な固定値であり、実機設定の正値ではありません。
UHF_READ_OUTPUT_POWER_RESPONSE = build_frame(ACK, bytes([0x43, 0x01, 0x00, 0xF0, 0x00]))
UHF_READ_FREQ_CH_RESPONSE = build_frame(ACK, bytes([0x43, 0x02, 0x00, 0x15]))
UHF_GET_INVENTORY_PARAM_RESPONSE = build_frame(
    ACK,
    bytes([0x41, 0x00, 0x30, 0x00, 0x81, 0x00, 0x00, 0x00, 0x00]),
)
BUZZER_ACK = build_frame(ACK)


def extract_detail_for_nack(frame: bytes) -> int:
    if len(frame) > 4:
        return frame[4]
    return 0x00


def parse_frame(frame: bytes) -> ParsedFrame:
    if len(frame) < 7:
        raise ValueError("frame is too short")
    data_length = frame[3]
    expected_length = data_length + 7
    if len(frame) != expected_length:
        raise ValueError("frame length does not match data length")
    if frame[0] != STX:
        raise ValueError("frame does not start with STX")
    if frame[4 + data_length] != ETX:
        raise ValueError("frame does not contain ETX at the expected position")
    if frame[-1] != CR:
        raise ValueError("frame does not end with CR")
    if frame[-2] != calculate_sum(frame[:-2]):
        raise ValueError("frame SUM is invalid")
    return ParsedFrame(
        raw=frame,
        address=frame[1],
        command=frame[2],
        data=frame[4 : 4 + data_length],
    )


def is_ram_command_mode_set(frame: ParsedFrame) -> bool:
    return (
        frame.command == 0x4E
        and len(frame.data) == 7
        and frame.data[0] == 0x00
        and frame.data[1] == 0x00
    )


def is_buzzer_command(frame: ParsedFrame) -> bool:
    return frame.command == BUZZER and len(frame.data) == 2


def responses_for_request(frame: bytes, scenario: str) -> List[bytes]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")

    try:
        parsed = parse_frame(frame)
    except ValueError as exc:
        if "SUM is invalid" in str(exc):
            return [build_nack(extract_detail_for_nack(frame), ERROR_SUM)]
        return []

    if scenario == "force-nack":
        # Mock-specific behavior for NACK-path tests. Do not treat this as real
        # device behavior for every supported command.
        return [build_nack(extract_detail_for_nack(frame), ERROR_FORMAT, parsed.address)]

    if frame == ROM_VERSION_REQUEST:
        return [ROM_VERSION_RESPONSE]

    if is_ram_command_mode_set(parsed):
        return [COMMAND_MODE_ACK]

    if frame == UHF_READ_OUTPUT_POWER_REQUEST:
        return [UHF_READ_OUTPUT_POWER_RESPONSE]

    if frame == UHF_READ_FREQ_CH_REQUEST:
        return [UHF_READ_FREQ_CH_RESPONSE]

    if frame == UHF_GET_INVENTORY_PARAM_REQUEST:
        return [UHF_GET_INVENTORY_PARAM_RESPONSE]

    if frame == UHF_SET_INVENTORY_PARAM_REQUEST:
        # SET系コマンドは、通常サンプルから送られないことを確認する対象です。
        # 誤って送られた場合はACKせず、FORMAT_ERROR相当のNACKを返します。
        return [build_nack(extract_detail_for_nack(frame), ERROR_FORMAT, parsed.address)]

    if frame == UHF_INVENTORY_REQUEST:
        if scenario == "no-tag":
            return [INVENTORY_DONE_NO_TAG]
        return [INVENTORY_TAG_RESPONSE, INVENTORY_DONE_ONE_TAG]

    if is_buzzer_command(parsed):
        return [BUZZER_ACK]

    # TODO: Unsupported commands are intentionally not inferred here. If a
    # NACK-path check is needed for unsupported commands, use force-nack.
    return []


def try_extract_frame(buffer: bytearray) -> Optional[bytes]:
    while buffer and buffer[0] != STX:
        del buffer[0]

    if len(buffer) < 4:
        return None

    data_length = buffer[3]
    total_length = data_length + 7
    if len(buffer) < total_length:
        return None

    frame = bytes(buffer[:total_length])
    del buffer[:total_length]
    return frame


def handle_client(conn: socket.socket, scenario: str) -> None:
    buffer = bytearray()
    with conn:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buffer.extend(chunk)
            while True:
                frame = try_extract_frame(buffer)
                if frame is None:
                    break
                print(f"RX: {format_hex(frame)}", flush=True)
                responses = responses_for_request(frame, scenario)
                if not responses:
                    print("TX: <no response> TODO: unsupported command", flush=True)
                for response in responses:
                    conn.sendall(response)
                    print(f"TX: {format_hex(response)}", flush=True)


def run_server(host: str, port: int, scenario: str) -> None:
    if host == "0.0.0.0":
        raise ValueError("Refusing to listen on 0.0.0.0; use 127.0.0.1 for mock tests")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        server.settimeout(0.5)
        print(f"UTR mock TCP server listening on {host}:{port} scenario={scenario}", flush=True)
        try:
            while True:
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                print(f"CLIENT: {addr[0]}:{addr[1]}", flush=True)
                handle_client(conn, scenario)
        except KeyboardInterrupt:
            print("Mock server stopped.", flush=True)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UTR LAN mock TCP server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--scenario", choices=SCENARIOS, default=DEFAULT_SCENARIO)
    args = parser.parse_args(argv)
    if args.host == "0.0.0.0":
        parser.error("0.0.0.0 is not allowed for this mock server")
    return args


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = parse_args(argv)
    run_server(args.host, args.port, args.scenario)


if __name__ == "__main__":
    main()
