# UHF_SET_INVENTORY_PARAM 自動送信停止メモ

## 目的

LAN版サンプルの通常実行フローでは、`UHF_SET_INVENTORY_PARAM` を自動送信しません。

Inventoryパラメータは、まず `UHF_GET_INVENTORY_PARAM` で現在値を読み取り、画面へHEX表示するだけにします。

## 背景

`UHF_SET_INVENTORY_PARAM` は、Inventory処理に関係する設定値を書き換えるSET系コマンドです。実機の状態や設定値の意味を十分に確認しないまま自動送信すると、読み取り条件が意図せず変わる可能性があります。

そのため、第1段階では読み取り専用の確認に限定します。

## 通常実行フローで行うこと

1. TCP接続
2. ROMバージョン確認
3. コマンドモード切替
4. 送信出力値読み取り
5. 周波数チャンネル読み取り
6. `UHF_GET_INVENTORY_PARAM` によるInventoryパラメータ読み取り
7. Inventoryパラメータの受信HEX表示
8. `UHF_INVENTORY` によるタグ読み取り

## 通常実行フローで行わないこと

- `UHF_SET_INVENTORY_PARAM` の自動送信
- FLASH書き込み
- 送信出力設定変更
- 周波数設定変更
- 8CHアンテナ切替の実送信
- 8CH復元の実送信
- ROMシリーズ判定ロジック変更
- 安全ガードの削除または緩和

## 実機確認時の確認ポイント

実機確認では、Pythonサンプルの送信ログまたはUTRRWManagerの比較ログで、以下を確認してください。

- `UHF_GET_INVENTORY_PARAM` が送信されていること
- `UHF_SET_INVENTORY_PARAM` が送信されていないこと
- Inventoryが従来どおり実行できること

実機確認が完了するまでは、机上確認だけで完了扱いにしません。
