## TAKAYA RFID リーダライタ サンプルプログラム ドキュメント

> **ドキュメントの全体像や他のサンプルプログラムについては、[こちらのランディングページ](https://tamarunorio.github.io/TAKAYA-RFID-Sample-Code/)をご覧ください。**

# UTR-S201 シリーズ（LAN接続）Python サンプル

タカヤ製 UTR-S201 シリーズ（UHF帯）リーダライタを **LAN(TCP)** 経由で制御するためのサンプルです。USB版サンプル（`UTR_USB_sample_1.1.5.py`）の構造を踏襲し、**通信層のみ TCP に置き換え**ています。本サンプルは無保証です。検証・学習目的でご利用ください。

## 概要

このサンプルプログラムは、ROMバージョン確認、コマンドモード切替、送信出力値／周波数チャンネルの取得、インベントリ（タグ読み取り）の実行、RSSIとPC+UIIの抽出・表示、ブザー制御、集計結果の表示／ログ保存、受信フレームのSTX / ETX / SUM / CR 検証といった主要な機能を提供します。

## 動作環境

-   OS: Windows 10 / 11
-   Python: 3.10+
-   ネットワーク到達可能な UTR-S201（LANモデル）
    -   既定ポート例：**9004**（装置設定に依存します）

> **注意**: 装置の通信設定（IP、ポートなど）は **UTR-RWManager** を用いて事前にご確認ください。

## セットアップと実行方法

1.  **Python を用意**: Python 3.10 以上がインストールされていることを確認してください。
2.  **リポジトリのクローン**:
    ```bash
    git clone https://github.com/TamaruNorio/UTR_LAN_Python.git
    cd UTR_LAN_Python
    ```
3.  **実行**:
    ```bash
    python src/UTR_LAN_sample_1.0.0.py
    ```
    実行時プロンプトに従い、**IP アドレス** と **TCP ポート** を入力します。ポート未入力時は **9004** を使用します。指定回数のインベントリを実行し、結果とログを出力します。

## 開発環境セットアップ

開発・テスト用の依存関係をインストールします。

```powershell
py -m pip install -r requirements-dev.txt
```

pytest を実行します。

```powershell
py -m pytest
```

## 半自動チェック

開発中の基本確認をまとめて実行します。

```powershell
.\scripts\dev_check.ps1
```

PR作成前の確認をまとめて表示します。

```powershell
.\scripts\git_preflight.ps1
```

PR本文テンプレートを表示、またはファイルへ保存します。

```powershell
.\scripts\pr_body.ps1
.\scripts\pr_body.ps1 -OutputPath pr_body.md
```

これらのスクリプトは実機通信、`real_device_check.py`、`git push`、PR作成、mergeを自動実行しません。

PR作業の開始、公開準備、merge後の同期を補助します。

```powershell
.\scripts\new_task.ps1 -Branch codex/example-task
.\scripts\publish_pr.ps1 -Message "Add PR helper scripts" -Title "Add PR helper scripts"
.\scripts\sync_after_merge.ps1 -Branch codex/example-task
```

`publish_pr.ps1` は確認後に `git commit` と `git push` を実行し、`pr_body.md` の生成、クリップボード確認、PR作成URLの表示を行います。クリップボード確認に失敗した場合は `pr_body.md` を開きます。PR作成とmergeは自動実行しません。

## mock TCPサーバーの使い方

UTRリーダライタ実機の代わりに、localhost 上で mock TCPサーバーを起動できます。

one-tag シナリオ:

```powershell
py tools/mock_utr_tcp_server.py --scenario one-tag
```

no-tag シナリオ:

```powershell
py tools/mock_utr_tcp_server.py --scenario no-tag
```

停止する場合は、起動中の PowerShell で `Ctrl + C` を押します。

## mockクライアントの使い方

mock TCPサーバーを起動した状態で、別の PowerShell から mockクライアントを実行します。

```powershell
py tools/mock_client_check.py
```

この確認では、以下の流れを確認できます。

1. ROMバージョン確認コマンド送信
2. ACK応答受信、ROM文字列解析
3. RAM指定のコマンドモード設定コマンド送信
4. ACK応答受信
5. UHF_Inventory コマンド送信
6. one-tag / no-tag シナリオの応答受信
7. 送信HEX、受信HEX、解析結果の表示

## 実機確認前の方針

実機確認の前に、まず UTRRWManager で以下を確認します。

1. TCP/IP接続確認
2. ROMバージョン読み取り
3. Inventory 1回
4. 送受信ログの TX / RX 保存
5. Pythonサンプルの TX / RX との比較

通信コマンド仕様は `docs/protocol/` を正とします。
UTRRWManager の送受信ログは、実機確認用および Pythonサンプルとの比較用の基準ログとして扱います。
ただし、通信コマンド仕様の正は `docs/protocol/` とします。

## 実機LAN確認ツールの使い方

実機LAN確認には `tools/real_device_check.py` を使用します。

```powershell
py tools/real_device_check.py --host <実機IP> --port 9004
```

`--host` は必須です。デフォルトの実機IPは設定していません。

`127.0.0.1` 以外へ接続する場合は、実行前に対象IP、ポート、実行内容、期待結果、ログ保存先、禁止操作が表示されます。内容を確認し、`YES` と入力した場合のみ接続を開始します。

このツールで実行する処理は以下のみです。

1. TCP接続確認
2. ROMバージョン確認
3. RAM指定のコマンドモード設定
4. UHF_Inventory 1回
5. ログ保存

ログは `logs/real_device/` に保存されます。実機IPなどのネットワーク情報を含む可能性があるため、`logs/real_device/` はGit管理しないでください。

実機確認前には、まず UTRRWManager で基準ログを取得し、UTRRWManager の TX/RX と Pythonサンプルの TX/RX を比較してください。

## 初期実機確認で禁止する操作

初期実機確認では、以下の操作を行いません。

- FLASH書き込み
- FLASH初期化
- FLASH設定復元
- RF出力設定変更
- 周波数設定変更
- ブザー制御
- LED&ブザー制御
- 連続Inventory
- リスタート
- RFタグ書き込み系コマンド

### VS Code でのワンクリック実行（推奨設定）

`.vscode/launch.json` に以下を保存してください（**debugpy**使用）。

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run: UTR LAN sample",
      "type": "debugpy",
      "request": "launch",
      "program": "${workspaceFolder}/src/UTR_LAN_sample_1.0.0.py",
      "console": "integratedTerminal",
      "cwd": "${workspaceFolder}",
      "justMyCode": true,
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  ]
}
```

## プロジェクト構成

```
UTR_LAN_PYTHON/
├─ src/
│  └─ UTR_LAN_sample_1.0.0.py   # 本サンプル（LAN版）
├─ .gitignore
└─ README.md                     # このファイル
```

## 実装メモ

### 実行フロー

1.  TCP 接続確立（クライアント）
2.  ROMバージョン確認（ACK/NACK判定）
3.  コマンドモード切替
4.  送信出力値・周波数チャンネルの取得
5.  インベントリ（指定回数）
6.  ブザー制御（応答あり）
7.  集計表示／ログ保存 → 切断

> 受信処理は **1バイトずつ読み取り**、ヘッダ/フッタおよび **SUM を検証**してフレーム確定します。ACK/NACK を受信した時点で `communicate()` は戻ります。

### 主な設定ポイント

-   **装置 IP / ポート**：実機の設定に合わせて入力（デフォルト 9004）
-   **タイムアウト**：`TcpSession(timeout=1.0)`、`communicate(..., timeout=...)` で変更可。タグ枚数が多い環境では **インベントリのみ 3秒** など長めを推奨。
-   **繰り返し回数**：1〜100 の範囲で指定。

## ライセンス

本リポジトリは `LICENSE` に記載の MIT License に基づいて公開しています。

本サンプルプログラムは、TAKAYA UTR-S201シリーズの通信確認・学習・検証を目的としたサンプルです。  
すべての条件分岐や実運用環境での動作を網羅・保証するものではありません。

実際の機器設定や運用確認では、通信プロトコル仕様書、機器取扱説明書、UTRRWManager等の公式資料・ユーティリティを併用し、実機の通信ログを確認してください。

## 変更履歴

-   0.2.0 (2026-05-19): 通信プロトコル資料、機器取扱説明書、UTRRWManager確認手順、mock TCPサーバー、mockクライアント、実機LAN確認ツール、pytestによる検証基盤を追加。UTRRWManagerの送受信ログを基準ログとして、PythonサンプルのTX/RXと比較できる構成に整理。
-   0.1.0 (2024-06-06): 初版。LAN受信のフレーム復元とInventory2最小動作を実装。
