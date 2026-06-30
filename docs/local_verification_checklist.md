# ローカル確認チェックリスト

このチェックリストは、`fix/disable-auto-set-inventory-param` ブランチをローカルPCで確認するための手順です。

## 目的

LAN版サンプルの通常実行フローで、以下を確認します。

- `UHF_GET_INVENTORY_PARAM` は送信される
- `UHF_SET_INVENTORY_PARAM` は自動送信されない
- pytest が通る
- 実機を使わずに、mock TCPサーバーで机上確認できる

## 1. ブランチを取得する

PowerShellでリポジトリのフォルダを開きます。

```powershell
git fetch
git switch fix/disable-auto-set-inventory-param
```

現在のブランチを確認します。

```powershell
git status --short
git branch --show-current
```

期待結果:

```text
fix/disable-auto-set-inventory-param
```

## 2. テストを実行する

```powershell
py -m pytest
```

`py` コマンドで動かない場合は、以下を使います。

```powershell
python -m pytest
```

期待結果:

```text
failed が 0 件
```

## 3. 差分の空白エラーを確認する

```powershell
git diff --check main...HEAD
```

期待結果:

```text
何も表示されない
```

何も表示されなければ、不要な末尾スペースなどはありません。

## 4. mock TCPサーバーで机上確認する

PowerShellを2つ開きます。

### PowerShell 1つ目: mockサーバー起動

```powershell
py tools/mock_utr_tcp_server.py --scenario no-tag
```

期待結果:

```text
UTR mock TCP server listening on 127.0.0.1:9004 scenario=no-tag
```

### PowerShell 2つ目: LANサンプル実行

```powershell
py src/UTR_LAN_sample_1.0.0.py
```

入力値:

```text
装置の IP アドレス: 127.0.0.1
TCP ポート番号: 9004
繰り返す回数: 1
```

## 5. mockサーバー側ログの確認ポイント

mockサーバー側の `RX:` ログで、以下が出ていることを確認します。

```text
02 00 55 02 41 00 03 9D 0D
```

これは `UHF_GET_INVENTORY_PARAM` です。

一方で、以下が出ていないことを確認します。

```text
02 00 55 09 30 00 81 00 00 00 00 00 00 03 14 0D
```

これは `UHF_SET_INVENTORY_PARAM` です。

## 6. サンプル画面の確認ポイント

LANサンプル側に、以下のような表示が出ることを確認します。

```text
UHF_GET_INVENTORY_PARAM が正常に実行されました
Inventoryパラメータ受信HEX: ...
安全方針: UHF_SET_INVENTORY_PARAM は自動送信しません。
```

## 7. 実機確認前に止めること

このPRの範囲では、以下は実施しません。

- FLASH書き込み
- 送信出力設定変更
- 周波数設定変更
- `UHF_SET_INVENTORY_PARAM` の送信
- 8CHアンテナ切替送信
- 8CH設定復元送信
- ROMシリーズ判定ロジック変更

## 8. 実機確認で見ること

実機確認では、Pythonサンプルの送信ログまたはUTRRWManagerの比較ログで以下を確認します。

- `UHF_GET_INVENTORY_PARAM` が送信されている
- `UHF_SET_INVENTORY_PARAM` が送信されていない
- Inventoryが従来どおり動作する

実機確認が終わるまでは、机上確認だけで完了扱いにしません。
