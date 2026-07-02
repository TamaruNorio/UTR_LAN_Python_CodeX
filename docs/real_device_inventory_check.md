# LAN実機Inventory確認手順

## 1. 目的

この手順書は、LAN接続のUTR RFIDリーダライタで、読み取り処理とログ保存を確認するための手順です。

本手順では、実機への永続設定変更を行いません。Inventory実行、CSV保存、RSSI集計、タグ別読み取り回数集計、送受信ログ保存を確認します。

## 2. 前提条件

- Windows環境で作業します。
- PowerShellを使用します。
- Pythonが使用できる状態にします。
- PCからUTR RFIDリーダライタへLAN接続できることを確認します。
- リーダライタのIPアドレスとTCPポート番号が分かっていることを確認します。
- 本手順では例として、IPアドレス `10.26.201.92`、TCPポート `9004` を使用します。
- 実運用では、IPアドレスとTCPポートを現場環境に合わせて変更してください。

## 3. 安全方針

本手順では、以下の操作を行いません。

- `UHF_SET_INVENTORY_PARAM` は自動送信しません。
- FLASH書き込みは行いません。
- 送信出力変更は行いません。
- 周波数変更は行いません。
- 8CHアンテナ切替は行いません。
- 実機への永続設定変更は行いません。

## 4. 作業前確認

作業前に、mainブランチ、差分、pytest結果を確認します。

```powershell
git switch main
git pull
git status --short
py -m pytest
```

期待結果:

- `git status --short` が空であること。
- `py -m pytest` が `63 passed` で完了すること。

## 5. LANサンプル本体の単発確認

LANサンプル本体をCLI引数付きで実行します。

```powershell
py src/UTR_LAN_sample_1.0.0.py --host 10.26.201.92 --port 9004 --repeat 1
```

確認する内容:

- 接続成功が表示されること。
- ROMバージョン取得が成功すること。
- コマンドモード切替が成功すること。
- `UHF_GET_INVENTORY_PARAM` が実行されること。
- `UHF_SET_INVENTORY_PARAM` が自動送信されないこと。
- Inventory結果が表示されること。
- `logs/lan_sample` に送受信ログが保存されること。

## 6. LAN Inventory batch runner の確認

LAN Inventory batch runnerでInventoryを10回実行します。

```powershell
py tools/lan_inventory_batch.py --host 10.26.201.92 --port 9004 --repeat 10 --interval 0.1
```

確認する内容:

- CSVが `logs/lan_sample` に保存されること。
- Inventory回数が10回であること。
- タグ応答数が表示されること。
- RSSI最小値、最大値、平均値が表示されること。
- タグ別読み取り回数が表示されること。
- SUMMARY行がCSV末尾に出力されること。

## 7. CSV確認方法

最新のCSVファイルを確認します。

```powershell
Get-ChildItem .\logs\lan_sample\inventory_batch_*.csv | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content .\logs\lan_sample\inventory_batch_YYYYMMDD_HHMMSS.csv | Select-Object -Last 12
```

2行目のファイル名は、1行目で確認した最新CSV名に置き換えてください。

CSV末尾に、以下のようなSUMMARY行があることを確認します。

```text
SUMMARY,total_iterations,10
SUMMARY,total_read_time_sec,0.512
SUMMARY,total_tag_responses,10
SUMMARY,unique_tags,1
SUMMARY,average_tag_count,1.000
SUMMARY,min_rssi,-53.000
SUMMARY,max_rssi,-49.800
SUMMARY,average_rssi,-50.900
```

## 8. 送受信ログ確認方法

最新の送受信ログを確認します。

```powershell
Get-ChildItem .\logs\lan_sample\lan_sample_tx_rx_*.txt | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

ログで確認する内容:

- `TX` が記録されていること。
- `RX` が記録されていること。
- `UHF_GET_INVENTORY_PARAM` が記録されていること。
- `UHF_INVENTORY` が記録されていること。
- `UHF_SET_INVENTORY_PARAM` が出ていないこと。

## 9. よくあるエラーと対処

### 接続できない

- IPアドレスを確認してください。
- TCPポート番号を確認してください。
- LANケーブルの接続を確認してください。
- `ping` で疎通を確認してください。
- UTR-RWManagerなど、他ソフトが接続中でないか確認してください。

### タグが読めない

- タグ位置を確認してください。
- アンテナ位置を確認してください。
- 対応タグであることを確認してください。
- 金属や水分の影響がないか確認してください。

### CSVが見つからない

- `logs/lan_sample` を確認してください。
- `--csv` を指定した場合は、指定先のパスを確認してください。

### pytestが失敗する

- 仮想環境を確認してください。
- `requirements-dev.txt` を再インストールしてください。
- 変更差分を確認してください。

## 10. 実機確認結果の記録テンプレート

| 項目 | 記録 |
|---|---|
| 確認日 |  |
| 確認者 |  |
| リーダライタ機種 |  |
| ROMバージョン |  |
| 接続方式 | LAN TCP |
| IPアドレス |  |
| TCPポート |  |
| 実行コマンド |  |
| Inventory回数 |  |
| 読み取りタグ数 |  |
| RSSI最小値 |  |
| RSSI最大値 |  |
| RSSI平均値 |  |
| CSVファイル名 |  |
| 送受信ログファイル名 |  |
| 備考 |  |
