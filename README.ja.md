# edinet-pit

EDINETの有価証券報告書（XBRL）から **point-in-time（原初開示）** の年次財務を抽出するPythonライブラリ。日本株バックテストの look-ahead bias（再表示財務問題）対策のために作った。

*English README: [README.md](README.md)*

## なぜ必要か

yfinance 等で取れる「過去の」財務データは、実は **現在の**（＝その後に修正・再表示された）数値です。開示日でフィルタしても、値そのものは当時投資家が見た数字ではありません。これがバックテストに look-ahead bias を混入させます。

EDINETの有価証券報告書（docTypeCode=120）は各年度の**原初開示**をXBRLで保持しており、無料で取得できます。本ライブラリは各報告書から「当期（`CurrentYear*`）」コンテキストの値だけを抽出します——ある年度の数値は「その年度を当期とする有報」由来、つまり真の point-in-time になります。翌年の有報が持つ前期（`Prior1Year*`）＝再表示値は拾いません。

## インストール

```
pip install edinet-pit            # 依存なし（標準ライブラリのみ）
pip install "edinet-pit[frames]"  # pandas DataFrame 出力も使う場合
```

## 使い方

APIキーは [EDINET API](https://api.edinet-fsa.go.jp/) で無料取得し、環境変数 `EDINET_API_KEY` に設定します。

```python
import datetime as dt
import edinet_pit as ep

# 1. 期間内の有報を証券コード別に収集（EDINETに横断検索は無いので日次スキャン）
docs = ep.find_annual_reports(dt.date(2023, 6, 1), dt.date(2023, 6, 30),
                              codes={"7203"}, verbose=True)

# 2. 各docIDをダウンロード→当期の財務を抽出
periods = [ep.fetch_period_for_doc(d["docID"], fallback_period_end=d["period_end"])
           for d in docs["7203"]]

# 3. yfinance互換ラベルの DataFrame に（columns=期末, index=科目）
fin, bs, cf = ep.build_frames([p for p in periods if p])
print(fin.loc["Total Revenue"])
```

各 `find_annual_reports` エントリの `submit`（実際の提出日）を保存しておけば、「as-of時点でその数値を知り得たか」の判定に使えます。期末＋固定ラグの近似より正確です。

ネットワーク部（`client`）と純粋変換部（`parse`: CSV解析→当期抽出→フレーム組立）は分離されており、後者はオフラインで単体テスト可能です。

## 取得できる科目

売上・営業利益・純利益・基本/希薄化EPS・発行済株式数・純資産・現金同等物・流動資産・流動負債・負債合計・投資有価証券・有利子負債（近似合算）・営業CF・CAPEX。日本基準（jppfs）とIFRS（jpigp）の両タクソノミ、およびIFRS大手が使う提出者拡張タグの売上フォールバックに対応。

## 既知の限界

- **主要科目のみ。** 細目や特殊科目は未対応（必要ならタグを `ELEMENT_MAP` に足せば拾えます）。
- **連結優先・完全一致。** 純粋な単体決算会社など、コンテキスト命名の揺れは取りこぼしうる。
- **有利子負債は近似。** 単一タグが無いため主要な借入・社債・リース債務の合算。
- **EDINET APIの遡及下限は2016年頃。** それ以前は旧タクソノミで未対応。
- **年次のみ。** 四半期報告書・訂正報告書（130）は対象外（訂正を除外するのは原初値を保つため）。

## 背景

日本株の長期バックテスト検証プロジェクトから抽出したモジュールです。再表示財務・生存者バイアスの実測結果を含む詳しい解説記事を準備中です。

このライブラリは as-is で提供します。Issue/PRは歓迎しますが、対応は不定期です。

## ライセンス

MIT
