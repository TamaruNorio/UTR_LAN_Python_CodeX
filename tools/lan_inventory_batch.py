#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""LAN-connected UTR inventory batch tool.

This tool reuses the verified LAN sample implementation and only adds a
non-interactive batch runner plus CSV output. It intentionally does not send
UHF_SET_INVENTORY_PARAM or any write/configuration-changing command.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Optional


DEFAULT_HOST = "10.26.201.92"
DEFAULT_PORT = 9004
DEFAULT_REPEAT = 10
DEFAULT_INTERVAL = 0.1
REPO_ROOT = Path(__file__).resolve().parents[1]
LAN_SAMPLE_PATH = REPO_ROOT / "src" / "UTR_LAN_sample_1.0.0.py"
DEFAULT_LOG_DIR = REPO_ROOT / "logs" / "lan_sample"
CSV_COLUMNS = [
    "timestamp",
    "iteration",
    "read_time_sec",
    "expected_read_count",
    "actual_tag_count",
    "rssi",
    "pc_uii",
    "output_power_dbm",
    "channel",
    "frequency_mhz",
    "note",
]


def load_lan_sample() -> ModuleType:
    spec = importlib.util.spec_from_file_location("utr_lan_sample", LAN_SAMPLE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load LAN sample: {LAN_SAMPLE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_csv_path() -> Path:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_LOG_DIR / f"inventory_batch_{timestamp}.csv"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run UHF_INVENTORY repeatedly over a LAN TCP connection and save CSV results."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"UTR host IP address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"UTR TCP port (default: {DEFAULT_PORT})")
    parser.add_argument(
        "--repeat",
        type=int,
        default=DEFAULT_REPEAT,
        help=f"Number of inventory executions (default: {DEFAULT_REPEAT})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"Interval between inventory executions in seconds (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument("--no-buzzer", action="store_true", help="Do not send buzzer commands")
    parser.add_argument("--csv", type=Path, default=None, help="CSV output path")
    args = parser.parse_args(argv)

    if args.repeat < 1:
        parser.error("--repeat must be 1 or greater")
    if args.interval < 0:
        parser.error("--interval must be 0 or greater")
    return args


def is_ack(module: ModuleType, response: bytes) -> bool:
    return (
        len(response) > module.CMD_LOCATION
        and response[0] == module.STX[0]
        and response[module.CMD_LOCATION] == module.ACK[0]
    )


def is_nack(module: ModuleType, response: bytes) -> bool:
    return (
        len(response) > module.CMD_LOCATION
        and response[0] == module.STX[0]
        and response[module.CMD_LOCATION] == module.NACK[0]
    )


def require_ack(module: ModuleType, label: str, response: bytes) -> None:
    if is_ack(module, response):
        return
    if is_nack(module, response):
        raise RuntimeError(f"{label} returned NACK: {module.parse_nack_response(response)}")
    raise RuntimeError(f"{label} did not return ACK/NACK: {response.hex(' ').upper()}")


def read_output_power_dbm(module: ModuleType, response: bytes) -> Optional[float]:
    if not is_ack(module, response) or len(response) <= 8:
        return None
    return int.from_bytes(response[7:9], byteorder="little") / 10


def read_channel(module: ModuleType, response: bytes) -> Optional[int]:
    if not is_ack(module, response) or len(response) <= 7:
        return None
    return int(response[7])


def channel_to_frequency_mhz(module: ModuleType, channel: Optional[int]) -> Optional[float]:
    if channel is None:
        return None
    if 1 <= channel <= len(module.OUTPUT_CH_FREQ_LIST):
        return module.OUTPUT_CH_FREQ_LIST[channel - 1]
    return None


def fmt_optional(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def rssi_stats(rssi_values: list[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if not rssi_values:
        return None, None, None
    return min(rssi_values), max(rssi_values), sum(rssi_values) / len(rssi_values)


def write_summary_rows(
    writer: csv.writer,
    *,
    total_iterations: int,
    total_read_time: float,
    total_tag_responses: int,
    unique_tag_count: int,
    rssi_values: list[float],
) -> None:
    min_rssi, max_rssi, average_rssi = rssi_stats(rssi_values)
    summary_values = [
        ("total_iterations", total_iterations),
        ("total_read_time_sec", f"{total_read_time:.3f}"),
        ("total_tag_responses", total_tag_responses),
        ("unique_tags", unique_tag_count),
        ("average_tag_count", f"{total_tag_responses / total_iterations:.3f}"),
        ("min_rssi", fmt_optional(min_rssi)),
        ("max_rssi", fmt_optional(max_rssi)),
        ("average_rssi", fmt_optional(average_rssi)),
    ]
    for key, value in summary_values:
        writer.writerow(["SUMMARY", key, value])


def print_summary(
    *,
    total_iterations: int,
    total_read_time: float,
    total_tag_responses: int,
    tag_counts: dict[str, int],
    rssi_values: list[float],
    csv_path: Path,
    tx_rx_log_path: Path,
) -> None:
    print("\n=== 集計結果 ===")
    print(f"Inventory回数: {total_iterations}")
    print(f"総読み取り時間: {total_read_time:.3f} 秒")
    print(f"総タグ応答数: {total_tag_responses}")
    print(f"ユニークタグ数: {len(tag_counts)}")
    print(f"平均タグ応答数: {total_tag_responses / total_iterations:.3f}")

    min_rssi, max_rssi, average_rssi = rssi_stats(rssi_values)
    if min_rssi is None:
        print("RSSI集計: 読み取りなし")
    else:
        print(f"RSSI最小値: {min_rssi:.3f}")
        print(f"RSSI最大値: {max_rssi:.3f}")
        print(f"RSSI平均値: {average_rssi:.3f}")

    print("タグ別読み取り回数:")
    if tag_counts:
        for pc_uii_hex, count in sorted(tag_counts.items()):
            print(f"  {pc_uii_hex}: {count} 回")
    else:
        print("  読み取りなし")

    print(f"CSV保存先: {csv_path}")
    print(f"送受信ログ保存先: {tx_rx_log_path}")


def write_inventory_rows(
    writer: csv.DictWriter,
    *,
    iteration: int,
    read_time_sec: float,
    expected_read_count: Optional[int],
    pc_uii_list: list[bytes],
    rssi_list: list[float],
    output_power_dbm: Optional[float],
    channel: Optional[int],
    frequency_mhz: Optional[float],
) -> int:
    timestamp = datetime.datetime.now().isoformat(timespec="milliseconds")
    actual_tag_count = len(pc_uii_list)

    if not pc_uii_list:
        writer.writerow(
            {
                "timestamp": timestamp,
                "iteration": iteration,
                "read_time_sec": f"{read_time_sec:.3f}",
                "expected_read_count": fmt_optional(expected_read_count),
                "actual_tag_count": actual_tag_count,
                "rssi": "",
                "pc_uii": "",
                "output_power_dbm": fmt_optional(output_power_dbm),
                "channel": fmt_optional(channel),
                "frequency_mhz": fmt_optional(frequency_mhz),
                "note": "NO_TAG",
            }
        )
        return 0

    for index, pc_uii in enumerate(pc_uii_list):
        rssi = rssi_list[index] if index < len(rssi_list) else None
        writer.writerow(
            {
                "timestamp": timestamp,
                "iteration": iteration,
                "read_time_sec": f"{read_time_sec:.3f}",
                "expected_read_count": fmt_optional(expected_read_count),
                "actual_tag_count": actual_tag_count,
                "rssi": fmt_optional(rssi),
                "pc_uii": pc_uii.hex(),
                "output_power_dbm": fmt_optional(output_power_dbm),
                "channel": fmt_optional(channel),
                "frequency_mhz": fmt_optional(frequency_mhz),
                "note": "TAG_READ",
            }
        )
    return actual_tag_count


def maybe_send_buzzer(module: ModuleType, session: Any, logger: Any, has_tag: bool, no_buzzer: bool) -> None:
    if no_buzzer:
        return

    sound_type = 0x00 if has_tag else 0x01
    response = module.send_buzzer_command(session, 0x01, sound_type, logger=logger)
    if is_nack(module, response):
        print(f"ブザー制御NACK: {module.parse_nack_response(response)}")


def run(args: argparse.Namespace) -> int:
    module = load_lan_sample()

    csv_path = args.csv if args.csv is not None else default_csv_path()
    csv_path = csv_path.resolve()
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    tx_rx_logger = module.TxRxLogger(log_dir=str(DEFAULT_LOG_DIR))
    tx_rx_logger.info("CONNECT_TARGET", f"{args.host}:{args.port}")

    session = module.TcpSession(args.host, args.port, timeout=1.0)
    total_read_time = 0.0
    total_tag_responses = 0
    tag_counts: dict[str, int] = {}
    rssi_values: list[float] = []
    output_power_dbm: Optional[float] = None
    channel: Optional[int] = None
    frequency_mhz: Optional[float] = None

    try:
        session.connect()
        tx_rx_logger.info("CONNECT", "OK")
        print(f"接続成功: {args.host}:{args.port}")
        print(f"送受信ログ保存先: {tx_rx_logger.path}")

        response = module.communicate(
            session,
            module.COMMANDS["ROM_VERSION_CHECK"],
            logger=tx_rx_logger,
            command_name="ROM_VERSION_CHECK",
        )
        require_ack(module, "ROM_VERSION_CHECK", response)

        response = module.communicate(
            session,
            module.COMMANDS["COMMAND_MODE_SET"],
            logger=tx_rx_logger,
            command_name="COMMAND_MODE_SET",
        )
        require_ack(module, "COMMAND_MODE_SET", response)

        response = module.communicate(
            session,
            module.COMMANDS["UHF_READ_OUTPUT_POWER"],
            logger=tx_rx_logger,
            command_name="UHF_READ_OUTPUT_POWER",
        )
        require_ack(module, "UHF_READ_OUTPUT_POWER", response)
        output_power_dbm = read_output_power_dbm(module, response)

        response = module.communicate(
            session,
            module.COMMANDS["UHF_READ_FREQ_CH"],
            logger=tx_rx_logger,
            command_name="UHF_READ_FREQ_CH",
        )
        require_ack(module, "UHF_READ_FREQ_CH", response)
        channel = read_channel(module, response)
        frequency_mhz = channel_to_frequency_mhz(module, channel)

        response = module.communicate(
            session,
            module.COMMANDS["UHF_GET_INVENTORY_PARAM"],
            logger=tx_rx_logger,
            command_name="UHF_GET_INVENTORY_PARAM",
        )
        require_ack(module, "UHF_GET_INVENTORY_PARAM", response)
        print("UHF_GET_INVENTORY_PARAM が正常に実行されました")
        print("安全方針: UHF_SET_INVENTORY_PARAM は自動送信しません。")

        with csv_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
            writer.writeheader()

            for iteration in range(1, args.repeat + 1):
                start_time = time.time()
                response = module.communicate(
                    session,
                    module.COMMANDS["UHF_INVENTORY"],
                    timeout=3.0,
                    logger=tx_rx_logger,
                    command_name="UHF_INVENTORY",
                )
                read_time_sec = time.time() - start_time
                pc_uii_list, rssi_list, expected_read_count = module.received_data_parse(response)

                total_read_time += read_time_sec
                total_tag_responses += write_inventory_rows(
                    writer,
                    iteration=iteration,
                    read_time_sec=read_time_sec,
                    expected_read_count=expected_read_count,
                    pc_uii_list=pc_uii_list,
                    rssi_list=rssi_list,
                    output_power_dbm=output_power_dbm,
                    channel=channel,
                    frequency_mhz=frequency_mhz,
                )
                for pc_uii in pc_uii_list:
                    pc_uii_hex = pc_uii.hex()
                    tag_counts[pc_uii_hex] = tag_counts.get(pc_uii_hex, 0) + 1
                rssi_values.extend(rssi_list[: len(pc_uii_list)])

                maybe_send_buzzer(
                    module,
                    session,
                    tx_rx_logger,
                    has_tag=bool(pc_uii_list),
                    no_buzzer=args.no_buzzer,
                )

                print(
                    f"{iteration}/{args.repeat}: "
                    f"tags={len(pc_uii_list)} expected={fmt_optional(expected_read_count)} "
                    f"time={read_time_sec:.3f}s"
                )
                if iteration < args.repeat and args.interval > 0:
                    time.sleep(args.interval)

            write_summary_rows(
                csv.writer(csv_file),
                total_iterations=args.repeat,
                total_read_time=total_read_time,
                total_tag_responses=total_tag_responses,
                unique_tag_count=len(tag_counts),
                rssi_values=rssi_values,
            )

        print_summary(
            total_iterations=args.repeat,
            total_read_time=total_read_time,
            total_tag_responses=total_tag_responses,
            tag_counts=tag_counts,
            rssi_values=rssi_values,
            csv_path=csv_path,
            tx_rx_log_path=tx_rx_logger.path,
        )
        tx_rx_logger.info("CSV", f"Saved {csv_path}")
        return 0
    except Exception as exc:
        tx_rx_logger.info("ERROR", str(exc))
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
        tx_rx_logger.info("CLOSE", "TCP session closed")


def main(argv: Optional[list[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
