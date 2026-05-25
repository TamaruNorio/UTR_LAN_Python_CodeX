# Codex作業依頼テンプレート

## 目的

- 

## 変更してよいファイル

- 

## 変更禁止ファイル

- 

## 作業ルール

- 実機通信は禁止。
- `real_device_check.py` は実行しない。
- `git commit`、`git push`、PR mergeは禁止。
- pytest未実行を成功扱いしない。
- `py` / `python` がPATHに存在しない場合は、Codex同梱Pythonの有無を確認してpytestを実行する。
- Codex同梱Pythonの例: `C:\Users\tamaru\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`
- pytest実行例: `& 'C:\Users\tamaru\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests -p no:cacheprovider --basetemp "$env:TEMP\utr_lan_pytest_tmp"`
- pytestが実際に起動して完了した場合のみ「pytest成功」または「pytest失敗」と報告する。
- それでも実行できない場合のみ「pytest未実行」とし、試したコマンドと失敗理由を明記する。
- `logs/real_device/` は実機ログ保存用であり、pytest一時領域には使わない。
- 不明な通信仕様は推測で実装しない。
- 通信仕様に関わる変更が必要な場合は、根拠となる資料と確認事項を先に提示する。
- PowerShellでの確認コマンドは、原則としてCodex側で実行する。
- ユーザーに `git status`、`git branch --show-current`、`.\scripts\dev_check.ps1`、`.\scripts\git_preflight.ps1` などを毎回コピペさせない。
- 実行に承認が必要な操作がある場合は、個別に何度も聞かず、作業内容をまとめて1回だけ確認する。
- 実機通信、`git commit`、`git push`、PR作成、merge は明示許可がない限り実行しない。

## 変更後の報告項目

1. 変更ファイル一覧
2. 主な変更点
3. 通信仕様に関わる変更の有無
4. pytestを実行できたかどうか
5. 実機確認が必要な項目
6. 次に行うべき作業
