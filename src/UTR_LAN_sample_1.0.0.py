#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UTR-S201 シリーズ（LAN接続）
サンプルプログラム（無保証） v1.0.0
Python 3.10+ / Windows 10+ で動作確認想定

【概要】
- 既存の USB シリアル版サンプル（UTR_USB_sample_1.1.5.py）と同じコマンド構造で、
  LAN(TCP) 接続に置き換えたものです。
- 受信処理（STX/ETX/SUM/CR の逐次検証）とインベントリ解析は、USB 版の設計を踏襲。
- 例として「ROMバージョン確認 → コマンドモード → 出力/周波数取得 →
  インベントリ（指定回数）→ ブザー制御 → 集計保存」の流れを実装。
- 実機確認やトラブル切り分けのため、送信HEXと受信HEXを logs/lan_sample/ に保存します。

【注意事項】
- すべての条件分岐を網羅しているわけではありません。
- 実機の設定（IP/ポート）や詳細なプロトコルは、製品のプロトコル仕様書をご確認ください。
- タイムアウトや再送、パケット分割等は環境に合わせて調整してください。
- 安全のため、UHF_SET_INVENTORY_PARAM は通常実行フローでは自動送信しません。
  Inventoryパラメータは UHF_GET_INVENTORY_PARAM で読み取り・表示のみ行います。

【前提】
- LAN モデル（TCP サーバーモード）に対して、上位機器（本プログラム）が TCP クライアントとして接続。
- 既定のポート例: 9004（装置・設定により異なる場合があります）
"""

import argparse
import sys
import time
import datetime
import re
import socket
from pathlib import Path
from typing import List, Optional, Tuple

# ==== CLI 既定値 ==============================================================
DEFAULT_HOST = "10.26.201.92"
DEFAULT_PORT = 9004
MIN_REPEAT_COUNT = 1
MAX_REPEAT_COUNT = 100

# ==== 定数定義（USB版と同じ）====================================================
HEADER_LENGTH     = 4        # STX, アドレス, コマンド, データ長 (各1バイト)
FOOTER_LENGTH     = 3        # ETX, SUM, CR (各1バイト)
STX : bytes       = b'\x02'  # Start Text
ADD : bytes       = b'\x00'  # RW IDなど(設定により変化することあり)
ETX : bytes       = b'\x03'  # End Text
CR  : bytes       = b'\x0D'  # Carriage Return
ACK : bytes       = b'\x30'  # ACK
NACK: bytes       = b'\x31'  # NACK
INV : bytes       = b'\x6C'  # インベントリコマンド
BUZ : bytes       = b'\x42'  # ブザーコマンド
CMD_LOCATION      = 2        # コマンドの位置（3バイト目）
DETAIL_LOCATION   = 4        # 詳細コマンド位置（5バイト目）
DETAIL_ROM: bytes = b'\x90'  # ROMバージョン読み取り詳細コマンド
DETAIL_INV: bytes = b'\x10'  # インベントリ詳細コマンド

OUTPUT_CH_FREQ_LIST = [916.0, 916.2, 916.4, 916.6, 916.8, 917.0, 917.2, 917.4, 917.6, 917.8,
                       918.0, 918.2, 918.4, 918.6, 918.8, 919.0, 919.2, 919.4, 919.6, 919.8,
                       920.0, 920.2, 920.4, 920.6, 920.8, 921.0, 921.2, 921.4, 921.6, 921.8,
                       922.0, 922.2, 922.4, 922.6, 922.8, 923.0, 923.2, 923.4]

# ==== UTR用 送信コマンド定義（USB版と同じ）=======================================
COMMANDS = {
    'ROM_VERSION_CHECK'      : bytes([0x02, 0x00, 0x4F, 0x01, 0x90, 0x03, 0xE5, 0x0D]),
    'COMMAND_MODE_SET'       : bytes([0x02, 0x00, 0x4E, 0x07, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x03, 0x6A, 0x0D]),
    'UHF_INVENTORY'          : bytes([0x02, 0x00, 0x55, 0x01, 0x10, 0x03, 0x6B, 0x0D]),
    'UHF_GET_INVENTORY_PARAM': bytes([0x02, 0x00, 0x55, 0x02, 0x41, 0x00, 0x03, 0x9D, 0x0D]),
    # 安全上の理由により、通常実行フローではこのSET系コマンドを自動送信しません。
    # 明示許可、仕様確認、実機ログ比較、復元手順がそろうまでは読み取り専用で扱います。
    'UHF_SET_INVENTORY_PARAM': bytes([0x02, 0x00, 0x55, 0x09, 0x30, 0x00, 0x81, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x14, 0x0D]),
    'UHF_READ_OUTPUT_POWER'  : bytes([0x02, 0x00, 0x55, 0x03, 0x43, 0x01, 0x00, 0x03, 0xA1, 0x0D]),
    'UHF_READ_FREQ_CH'       : bytes([0x02, 0x00, 0x55, 0x03, 0x43, 0x02, 0x00, 0x03, 0xA2, 0x0D]),
    'UHF_WRITE'              : bytes([0x02, 0x00, 0x55, 0x08, 0x16, 0x01, 0x00, 0x00, 0x00, 0x02, 0x04, 0x56, 0x03, 0xD5, 0x0D]),
}

# =============================================================================
#  ユーティリティ（SUM 計算/検証、NACK解析、RSSI値計算 等）
# =============================================================================
def calculate_sum_value(data: bytes) -> int:
    """STX〜ETX までの合計値(下位1バイト)を算出して返す。"""
    return sum(data) & 0xFF

def verify_sum_value(data_frame: bytes) -> bool:
    """データ末尾の SUM と、STX〜ETX までの合計値が一致するか検証する。"""
    if len(data_frame) < HEADER_LENGTH + FOOTER_LENGTH:
        return False
    expected = data_frame[-2]
    calc     = calculate_sum_value(data_frame[:-2])
    return expected == calc

def parse_nack_response(nack_response: bytes) -> str:
    """NACK 応答のエラーコードを簡易的に日本語に変換して返す（例示）。"""
    if len(nack_response) < (HEADER_LENGTH + FOOTER_LENGTH):
        return "Invalid NACK response"

    error_code = nack_response[5]
    error_messages = {
        0x01: "CMD_CRC_ERROR: データのCRCが一致しない",
        0x02: "CMD_TIME_OVER: データが途中で途切れた",
        0x03: "CMD_RX_ERROR: アンチコリジョン処理中にエラー",
        0x04: "CMD_RXBUSY_ERROR: RFタグからの応答がない",
        0x07: "CMD_ERROR: コマンド実行中にリーダライタ内部でエラー",
        0x0A: "CMD_UHF_IC_ERROR: RFタグアクセス時の内蔵チップエラー",
        0x60: "CMD_LBT_ERROR: キャリアセンス時のタイムアウトエラー",
        0x64: "HARDWARE_ERROR: ハードウェア内部で異常が発生",
        0x68: "CMD_ANT_ERROR: アンテナ断線検知エラー",
        0x42: "SUM_ERROR: 上位機器から送信されたコマンドのSUM値が正しくない",
        0x44: "FORMAT_ERROR: 上位機器から送信されたコマンドのフォーマットまたはパラメータが正しくない",
    }
    return error_messages.get(error_code, f"Unknown NACK error (0x{error_code:02X})")

def convert_rssi(rssi_hex_value: str) -> float:
    """
    RSSI 値(無線信号強度の指標)を計算して返す。
    レスポンスの6〜7バイト目を符号付き16ビットとして扱い、10進数化してから10で割る。
    """
    binary_value = bin(int(rssi_hex_value, 16))[2:]
    inverted_binary_value = ''.join('1' if bit == '0' else '0' for bit in binary_value)
    added_binary_value = bin(int(inverted_binary_value, 2) + 1)[2:]
    rssi_value = int(added_binary_value, 2)
    return -rssi_value / 10

def format_hex(data: bytes) -> str:
    """ログや画面表示で見やすいように、bytesをスペース区切りの大文字HEXへ変換する。"""
    if not data:
        return "(no data)"
    return data.hex(' ').upper()

class TxRxLogger:
    """LANサンプルの送受信内容をファイルへ残すための簡易ロガー。"""

    def __init__(self, log_dir: str = "logs/lan_sample") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = self.log_dir / f"lan_sample_tx_rx_{timestamp}.txt"
        self.write("INFO", "START", "LAN sample TX/RX log started")

    def write(self, direction: str, label: str, message: str) -> None:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with self.path.open('a', encoding="utf-8") as f:
            f.write(f"{timestamp} {direction:<7} {label} {message}\n")

    def info(self, label: str, message: str) -> None:
        self.write("INFO", label, message)

    def tx(self, label: str, data: bytes) -> None:
        self.write("TX", label, format_hex(data))

    def rx(self, label: str, data: bytes) -> None:
        self.write("RX", label, format_hex(data))

# =============================================================================
#  受信フレーム解析（USB版のロジック踏襲）
# =============================================================================
def parse_data_frame(data: bytes, index: int) -> Tuple[Optional[bytes], int]:
    """STX〜CR までの 1 フレームを取り出して返す。なければ (None, index) を返す。"""
    if len(data) >= (index + HEADER_LENGTH + FOOTER_LENGTH):
        data_length = data[index + 3] + HEADER_LENGTH + FOOTER_LENGTH
        if len(data) >= (index + data_length):
            if data[(index + data_length) - 1] == CR[0]:
                return data[index:(index + data_length)], (index + data_length)
    return None, index

def handle_inventory_response(data_frame: bytes, pc_uii_list: List[bytes], rssi_list: List[float]) -> None:
    """インベントリのレスポンス 1 フレームから PC+UII と RSSI を抽出して格納する。"""
    pc_uii_length = data_frame[8]
    pc_uii_data   = data_frame[9:9 + pc_uii_length]
    pc_uii_list.append(pc_uii_data)
    rssi_value = convert_rssi(data_frame[5:7].hex())
    rssi_list.append(rssi_value)

def check_inventory_ack_response(data_frame: bytes) -> int:
    """インベントリ時 ACK フレームから読み取り枚数を抽出して返す。"""
    return int.from_bytes(data_frame[6:8], byteorder='little')

def received_data_parse(data: bytes):
    """複数フレームを走査し、インベントリ結果を (pc_uii_list, rssi_list, expected_count) で返す。"""
    pc_uii_list: List[bytes] = []
    rssi_list:   List[float] = []
    expected_read_count: Optional[int] = None

    i = 0
    while i < len(data):
        if data[i] == STX[0]:
            frame, next_idx = parse_data_frame(data, i)
            if frame:
                if verify_sum_value(frame):
                    command = bytes([frame[CMD_LOCATION]])
                    detail  = bytes([frame[DETAIL_LOCATION]]) if len(frame) > DETAIL_LOCATION else b''

                    if command == INV:
                        handle_inventory_response(frame, pc_uii_list, rssi_list)
                    elif command == ACK and detail == DETAIL_INV:
                        expected_read_count = check_inventory_ack_response(frame)
                    elif command == NACK:
                        print(parse_nack_response(frame))
                else:
                    print("サム値が正しくありません（途中までの結果を返します）")
                    return pc_uii_list, rssi_list, expected_read_count
                i = next_idx
            else:
                # 途中で切れている場合は打ち切り（上位で追加の受信を検討）
                break
        else:
            i += 1

    if expected_read_count is not None and expected_read_count != len(pc_uii_list):
        print("タグの読み取り数とpc_uii_listの個数が一致しません")
        print("タグの読み取り予定数: ", expected_read_count)
        print("pc_uii_listの個数   : ", len(pc_uii_list))

    return pc_uii_list, rssi_list, expected_read_count

# =============================================================================
#  LAN 通信（TCP）
# =============================================================================
class TcpSession:
    """
    UTR（LANモデル）と TCP で通信するための簡易セッション。
    - recv は 1 バイトずつ読みつつ、USB 版と同等のパーサでフレームを確定。
    - タイムアウトはソケットの timeout で管理。
    """
    def __init__(self, host: str, port: int, timeout: float = 1.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

    def close(self) -> None:
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def send(self, data: bytes) -> None:
        if not self.sock:
            raise RuntimeError("ソケットが未接続です。connect() を先に呼び出してください。")
        self.sock.sendall(data)

    def recv(self, nbytes: int = 1) -> bytes:
        if not self.sock:
            raise RuntimeError("ソケットが未接続です。connect() を先に呼び出してください。")
        return self.sock.recv(nbytes)

def communicate(session: Optional[TcpSession], command: bytes, timeout: float = 1.0,
                logger: Optional[TxRxLogger] = None, command_name: str = "COMMAND") -> bytes:
    """
    【LAN版】コマンド送信→受信しながら STX/ETX/SUM/CR を検証し、正常フレームのみ連結して返す。
    ACK/NACK のどちらかを受信したら戻る。timeout 超過でも戻る。
    logger を渡した場合は、TX/RX のHEXを logs/lan_sample/ に保存する。
    """
    complete_response  = b''
    receive_buffer: List[int] = []
    buffer_length = 0
    data_length   = 0

    if session is not None:
        if logger is not None:
            logger.tx(command_name, command)
        session.send(command)

    start_time = time.time()
    while True:
        if (time.time() - start_time) > timeout:
            print("タイムアウト: レスポンスが一定時間内に受信されませんでした。")
            if logger is not None:
                logger.info(command_name, f"TIMEOUT after {timeout:.1f}s")
                if complete_response:
                    logger.rx(command_name, complete_response)
            return complete_response

        if session is not None:
            try:
                chunk = session.recv(1)  # 1バイトずつ受信（USB版と揃える）
            except socket.timeout:
                continue  # ソケットタイムアウト → 継続
            if not chunk:
                continue  # 切断/未受信
            receive_buffer += chunk
            buffer_length = len(receive_buffer)

        if receive_buffer:
            if receive_buffer[0] == STX[0]:
                if buffer_length >= HEADER_LENGTH:
                    data_length = receive_buffer[HEADER_LENGTH - 1]
                    total_len   = data_length + HEADER_LENGTH + FOOTER_LENGTH
                    if buffer_length >= total_len:
                        if receive_buffer[total_len - 1] == CR[0]:
                            if receive_buffer[data_length + HEADER_LENGTH] == ETX[0]:
                                frame = bytes(receive_buffer[:total_len])
                                if verify_sum_value(frame):
                                    complete_response += frame
                                    if receive_buffer[CMD_LOCATION] in [ACK[0], NACK[0]]:
                                        receive_buffer = []
                                        if logger is not None:
                                            logger.rx(command_name, complete_response)
                                        return complete_response
                                    receive_buffer = receive_buffer[total_len:]
                                else:
                                    # SUM 不一致 → 先頭をずらして同期取り直し
                                    receive_buffer = receive_buffer[1:]
                            else:
                                receive_buffer = receive_buffer[1:]
                        else:
                            receive_buffer = receive_buffer[1:]
                    else:
                        continue
                else:
                    continue
            else:
                receive_buffer = receive_buffer[1:]

# =============================================================================
#  ブザー制御（LAN版）
# =============================================================================
def send_buzzer_command(session: TcpSession, response_type: int, sound_type: int,
                        logger: Optional[TxRxLogger] = None) -> bytes:
    """
    ブザー制御コマンド（応答要求:0x01 を想定）。
    response_type: 0x00=応答なし / 0x01=応答あり（本サンプルは 0x01 推奨）
    sound_type   : 0x00=ピー / 0x01=ピッピッピ / ... 0x08=ピッピッピッピッ
    """
    data = bytes([response_type, sound_type])
    header = STX + ADD + BUZ + bytes([len(data)])
    frame_wo_sum = header + data + ETX
    sum_value = calculate_sum_value(frame_wo_sum)
    full_command = frame_wo_sum + bytes([sum_value]) + CR
    command_name = f"BUZZER_RESPONSE_{response_type:02X}_SOUND_{sound_type:02X}"
    return communicate(session, full_command, logger=logger, command_name=command_name)

# =============================================================================
#  集計ログ保存
# =============================================================================
def save_results_to_file(filename: str, total_iterations: int, total_read_time: float,
                         total_read_count: int, pc_uii_count_dict: dict) -> None:
    with open(filename, 'a', encoding="utf-8") as f:
        current_datetime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        f.write("\n# -*- coding: utf-8 -*-\n")
        f.write(f"\n=== 集計結果 ({current_datetime}) ===\n")
        f.write(f"総繰り返し回数: {total_iterations}\n")
        f.write(f"総読み取り時間: {total_read_time:.2f} 秒\n")
        if total_iterations > 0:
            f.write(f"平均読み取り枚数: {total_read_count / total_iterations:.2f} 枚\n")
        f.write("各PC+UIIデータの読み取り回数:\n")
        for pc_uii_hex, count in pc_uii_count_dict.items():
            f.write(f"{pc_uii_hex}: {count} 回\n")
        f.write("========= ここまで ============\n\n\n")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UTR LAN sample")
    parser.add_argument("--host", help=f"装置のIPアドレス（既定値: {DEFAULT_HOST}）")
    parser.add_argument("--port", type=int, help=f"TCPポート番号（既定値: {DEFAULT_PORT}）")
    parser.add_argument("--repeat", type=int, help=f"Inventory繰り返し回数（{MIN_REPEAT_COUNT}〜{MAX_REPEAT_COUNT}）")
    args = parser.parse_args(argv)

    if args.repeat is not None and not (MIN_REPEAT_COUNT <= args.repeat <= MAX_REPEAT_COUNT):
        parser.error(f"--repeat は {MIN_REPEAT_COUNT}〜{MAX_REPEAT_COUNT} の整数で指定してください。")
    if args.port is not None and args.port <= 0:
        parser.error("--port は 1 以上の整数で指定してください。")
    return args


def prompt_host(args: argparse.Namespace) -> Tuple[str, str]:
    if args.host is not None:
        return args.host, "--host 指定"

    host = input(f"装置の IP アドレスを入力してください（未入力なら {DEFAULT_HOST} を使用）: ").strip()
    if host:
        return host, "対話入力"
    return DEFAULT_HOST, "既定値"


def prompt_port(args: argparse.Namespace) -> Tuple[int, str]:
    if args.port is not None:
        return args.port, "--port 指定"

    while True:
        port_text = input(f"TCP ポート番号を入力してください（未入力なら {DEFAULT_PORT} を使用）: ").strip()
        if not port_text:
            return DEFAULT_PORT, "既定値"
        try:
            port = int(port_text)
            if port <= 0:
                raise ValueError("入力は 1 以上の整数である必要があります。")
            return port, "対話入力"
        except ValueError as e:
            print(f"エラー: {e}")


def prompt_repeat_count(args: argparse.Namespace) -> Tuple[int, str]:
    if args.repeat is not None:
        return args.repeat, "--repeat 指定"

    while True:
        try:
            repeat_count = int(input(f"繰り返す回数を入力してください（{MIN_REPEAT_COUNT}〜{MAX_REPEAT_COUNT}）: "))
            if not (MIN_REPEAT_COUNT <= repeat_count <= MAX_REPEAT_COUNT):
                raise ValueError(f"入力は {MIN_REPEAT_COUNT} 〜 {MAX_REPEAT_COUNT} の整数である必要があります。")
            return repeat_count, "対話入力"
        except ValueError as e:
            print(f"エラー: {e}")


def print_runtime_value(label: str, value, source: str) -> None:
    print(f"{label}: {value}（{source}）")

# =============================================================================
#  メイン
# =============================================================================
def main(argv: Optional[List[str]] = None):
    args = parse_args(argv)

    # --- 接続情報の入力 ---
    print("UTR（LANモデル）に接続します。")
    host, host_source = prompt_host(args)
    port, port_source = prompt_port(args)
    print_runtime_value("接続先IP", host, host_source)
    print_runtime_value("TCPポート番号", port, port_source)

    # --- ログ準備 ---
    # 実機確認時に「何を送って、何を受けたか」を後から確認できるように保存します。
    tx_rx_logger = TxRxLogger()
    tx_rx_logger.info("CONNECT_TARGET", f"{host}:{port}")
    print(f"送受信ログ保存先: {tx_rx_logger.path}")

    # --- セッション確立 ---
    session = TcpSession(host, port, timeout=1.0)
    try:
        session.connect()
        print(f"接続成功: {host}:{port}")
        tx_rx_logger.info("CONNECT", "OK")
    except Exception as e:
        tx_rx_logger.info("CONNECT", f"NG {e}")
        print(f"接続エラー: {e}")
        sys.exit(1)

    # --- ROMバージョンで通信確認 ---
    result = communicate(session, COMMANDS['ROM_VERSION_CHECK'], logger=tx_rx_logger, command_name='ROM_VERSION_CHECK')
    if re.match(STX + b'.' + ACK, result):
        if bytes([result[DETAIL_LOCATION]]) == DETAIL_ROM:
            print("LAN通信: OK（ROMバージョン ACK 受信）")
    elif re.match(STX + b'.' + NACK, result):
        if bytes([result[DETAIL_LOCATION]]) == DETAIL_ROM:
            print(parse_nack_response(result))
    else:
        print("LAN通信: NG（ACK/NACK なし）")
        session.close()
        sys.exit(1)

    # --- コマンドモード切替 ---
    result = communicate(session, COMMANDS['COMMAND_MODE_SET'], logger=tx_rx_logger, command_name='COMMAND_MODE_SET')
    if re.match(STX + b'.' + ACK, result):
        print("コマンドモードに切り替えました")
    elif re.match(STX + b'.' + NACK, result):
        print(parse_nack_response(result))
    else:
        print("コマンドモード切替に失敗しました")
        session.close()
        sys.exit(1)

    # --- 出力/周波数の読み取り ---
    # 出力
    result = communicate(session, COMMANDS['UHF_READ_OUTPUT_POWER'], logger=tx_rx_logger, command_name='UHF_READ_OUTPUT_POWER')
    if re.match(STX + b'.' + ACK, result):
        level_hex = hex(result[8] + result[7])
        output_power_level = int(level_hex, 16) / 10
        print("送信出力値：", output_power_level, "dBm")
    elif re.match(STX + b'.' + NACK, result):
        print(parse_nack_response(result))
    else:
        print("通信エラー（UHF_READ_OUTPUT_POWER）")
        print(result.hex())
        session.close()
        sys.exit(1)

    # 周波数チャンネル
    result = communicate(session, COMMANDS['UHF_READ_FREQ_CH'], logger=tx_rx_logger, command_name='UHF_READ_FREQ_CH')
    if re.match(STX + b'.' + ACK, result):
        output_ch = int(hex(result[7]), 16)
        print("チャンネル番号：", output_ch, "ch")
        if 1 <= output_ch <= len(OUTPUT_CH_FREQ_LIST):
            print("送信周波数：", OUTPUT_CH_FREQ_LIST[output_ch-1], " MHz")
    elif re.match(STX + b'.' + NACK, result):
        print(parse_nack_response(result))
    else:
        print("通信エラー（UHF_READ_FREQ_CH）")
        print(result.hex())
        session.close()
        sys.exit(1)

    # --- インベントリパラメータ取得（読み取りのみ） ---
    result = communicate(session, COMMANDS['UHF_GET_INVENTORY_PARAM'], logger=tx_rx_logger, command_name='UHF_GET_INVENTORY_PARAM')
    if re.match(STX + b'.' + ACK, result):
        print("UHF_GET_INVENTORY_PARAM が正常に実行されました")
        print("Inventoryパラメータ受信HEX:", result.hex(' ').upper())
        print("安全方針: UHF_SET_INVENTORY_PARAM は自動送信しません。")
    elif re.match(STX + b'.' + NACK, result):
        print(parse_nack_response(result))
    else:
        print("UHF_GET_INVENTORY_PARAM 実行エラー")
        print(result.hex())
        session.close()
        sys.exit(1)

    # --- 読み取りループ ---
    total_read_time   = 0.0
    total_read_count  = 0
    total_iterations  = 0
    pc_uii_count_dict = {}

    repeat_count, repeat_source = prompt_repeat_count(args)
    print_runtime_value("繰り返す回数", repeat_count, repeat_source)

    for _ in range(repeat_count):
        start_time = time.time()
        received_data_bytes = communicate(session, COMMANDS['UHF_INVENTORY'], timeout=3.0, logger=tx_rx_logger, command_name='UHF_INVENTORY')
        pc_uii_data_list, rssi_list, expected_read_count = received_data_parse(received_data_bytes)
        read_time = time.time() - start_time

        total_read_time += read_time
        total_iterations += 1
        if expected_read_count is not None:
            total_read_count += expected_read_count

        for pc_uii_data in pc_uii_data_list:
            pc_uii_hex = pc_uii_data.hex()
            pc_uii_count_dict[pc_uii_hex] = pc_uii_count_dict.get(pc_uii_hex, 0) + 1

        if pc_uii_data_list:
            result = send_buzzer_command(session, 0x01, 0x00, logger=tx_rx_logger)  # 応答あり / ピー
            if re.match(STX + b'.' + NACK, result):
                print("ブザーパラメータが間違っています")
            print("タグを " + str(expected_read_count) + " 枚読み取りました。")
        else:
            result = send_buzzer_command(session, 0x01, 0x01, logger=tx_rx_logger)  # 応答あり / ピッピッピ
            if re.match(STX + b'.' + NACK, result):
                print("ブザーパラメータが間違っています")
            print("タグが見つかりませんでした")

        for pc_uii_data, rssi_value in zip(pc_uii_data_list, rssi_list):
            print("RSSI値:", rssi_value, "/ PC+UIIデータ:", pc_uii_data.hex())

    # --- 集計出力 ---
    print("\n=== 集計結果 ===")
    print(f"総繰り返し回数: {total_iterations}")
    print(f"総読み取り時間: {total_read_time:.2f} 秒")
    if total_iterations > 0:
        print(f"平均読み取り枚数: {total_read_count / total_iterations:.2f} 枚")
    print("各PC+UIIデータの読み取り回数:")
    for pc_uii_hex, count in pc_uii_count_dict.items():
        print(f"{pc_uii_hex}: {count} 回")

    # --- 集計保存 ---
    filename = "Inventory_result_LAN.log"
    save_results_to_file(filename, total_iterations, total_read_time, total_read_count, pc_uii_count_dict)
    tx_rx_logger.info("RESULT_LOG", f"Saved {filename}")
    print(f"送受信ログ保存先: {tx_rx_logger.path}")

    session.close()
    tx_rx_logger.info("CLOSE", "TCP session closed")

if __name__ == "__main__":
    main()
