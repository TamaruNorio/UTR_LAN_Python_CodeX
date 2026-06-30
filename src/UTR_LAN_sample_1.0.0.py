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

import sys
import time
import datetime
import re
import socket
from typing import List, Optional, Tuple

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

def communicate(session: Optional[TcpSession], command: bytes, timeout: float = 1.0) -> bytes:
    """
    【LAN版】コマンド送信→受信しながら STX/ETX/SUM/CR を検証し、正常フレームのみ連結して返す。
    ACK/NACK のどちらかを受信したら戻る。timeout 超過でも戻る。
    """
    complete_response  = b''
    receive_buffer: List[int] = []
    buffer_length = 0
    data_length   = 0

    if session is not None:
        session.send(command)

    start_time = time.time()
    while True:
        if (time.time() - start_time) > timeout:
            print("タイムアウト: レスポンスが一定時間内に受信されませんでした。")
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
def send_buzzer_command(session: TcpSession, response_type: int, sound_type: int) -> bytes:
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
    return communicate(session, full_command)

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

# =============================================================================
#  メイン
# =============================================================================
def main():
    # --- 接続情報の入力 ---
    print("UTR（LANモデル）に接続します。")
    host = input("装置の IP アドレスを入力してください（例: 192.168.0.1）: ").strip()
    port_text = input("TCP ポート番号を入力してください（未入力なら 9004 を使用）: ").strip()
    port = int(port_text) if port_text else 9004

    # --- セッション確立 ---
    session = TcpSession(host, port, timeout=1.0)
    try:
        session.connect()
        print(f"接続成功: {host}:{port}")
    except Exception as e:
        print(f"接続エラー: {e}")
        sys.exit(1)

    # --- ROMバージョンで通信確認 ---
    result = communicate(session, COMMANDS['ROM_VERSION_CHECK'])
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
    result = communicate(session, COMMANDS['COMMAND_MODE_SET'])
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
    result = communicate(session, COMMANDS['UHF_READ_OUTPUT_POWER'])
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
    result = communicate(session, COMMANDS['UHF_READ_FREQ_CH'])
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
    result = communicate(session, COMMANDS['UHF_GET_INVENTORY_PARAM'])
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

    while True:
        try:
            repeat_count = int(input("繰り返す回数を入力してください（1〜100）: "))
            if (repeat_count <= 0) or (repeat_count > 100):
                raise ValueError("入力は 1 〜 100 の整数である必要があります。")
            break
        except ValueError as e:
            print(f"エラー: {e}")

    for _ in range(repeat_count):
        start_time = time.time()
        received_data_bytes = communicate(session, COMMANDS['UHF_INVENTORY'], timeout=3.0)
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
            result = send_buzzer_command(session, 0x01, 0x00)  # 応答あり / ピー
            if re.match(STX + b'.' + NACK, result):
                print("ブザーパラメータが間違っています")
            print("タグを " + str(expected_read_count) + " 枚読み取りました。")
        else:
            result = send_buzzer_command(session, 0x01, 0x01)  # 応答あり / ピッピッピ
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

    session.close()

if __name__ == "__main__":
    main()
