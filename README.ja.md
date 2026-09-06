# display360 — 外部ディスプレイを 360Hz で回した記録

> English: [README.md](README.md)

2026-08-31 に通って、それ以来ずっと 360Hz で使っている。以下は当日のメモをほぼそのまま置いたもの。

対象: MacBook Pro 16" M2 Pro (Mac14,10) / macOS 26.5.2 + **Pixio PX259PS**（USB-C の DP alt mode 接続）

## 結論

**360Hz で動いています。追加ハードウェアは不要でした。**
IOKit の非公開 API で **DCP に仮想 EDID を直接食わせ**、**タイミング表を作り直させる**のが答えでした。
常駐エージェントが接続のたびに自動で再適用するので、再起動・ケーブル抜き差し・スリープ復帰でも 360Hz に戻ります。

実測（`CVDisplayLinkSetOutputHandler` で vsync を実計数）:

```
モード申告   : 360.0000 Hz
vsync 実計数 : 359.9977 Hz  (1801 回 / 5.000s)   ← 実出力
フレーム間隔 : 中央値 2.7775 ms  (= 1/360)
```

採用タイミング: `1920x1080  htotal 2120 / vtotal 1160  (hblank 200 / vblank 80)  pclk 885.31MHz  H 417.6kHz`

## 仕組み（要点は 2 つ）

```c
IOAVServiceSetVirtualEDIDMode(av, 1, <360Hz 入り EDID>);  // ① 仮想 EDID を注入
IODPDeviceSetUpdated(dp, 1);                              // ② タイミング表を作り直させる
```

- **① だけでは効かない。** 注入自体は成功して `IOAVServiceCopyEDID` も改変 EDID を返すが、
  タイミング表は接続時に作られたままなので 360Hz は生えない。
- **`IOAVControllerForceHotPlugDetect` を使ってはいけない。** AV サービスごと作り直されるため、
  ①の設定が道連れで消え、再列挙時には配線上の EDID が使われる（実際に 2 回失敗した）。
  必要なのは「サービスを壊さずに再パースだけさせる」**②**。
- `IODPPortSetVirtualEDID`（ポート側・切断しても残る）は **`IODPPortSetVirtual` で
  ポートを virtual にしない限り参照されない**らしく、単独では効かなかった。

呼び出し規約は dyld キャッシュ上の実装を逆アセンブルして確定させた:

| 関数 | 引数 | user client selector |
|---|---|---|
| `IOAVServiceSetVirtualEDIDMode` | `(IOAVServiceRef, uint32_t mode, CFDataRef edid)` | 23 |
| `IODPDeviceSetUpdated` | `(IODPDeviceRef, uint32_t)` | 5 |
| `IOAVServiceReadI2C` | `(ref, chip, off, buf, len)` | 24 |
| `IOAVServiceWriteI2C` | `(ref, chip, off, buf, len)` | 25 |
| `IODPPortSetVirtual` | `(IODPPortRef, uint32_t)` | 0 |
| `IODPPortSetVirtualEDID` | `(IODPPortRef, CFDataRef)` | 4 |
| `IODPPortGetAddress` | `(ref, uint32_t*, uint32_t*, uint32_t*)` ← **出力 3 つ** | — |

## macOS が 360Hz を蹴っていた理由

配線上の EDID の 360Hz は **`PreferredTimingElements`（候補表）には居るのに `TimingElements`
（使用可能表）から落とされる**。score は最高（16846 > 300Hz の 15922）で `UnsafeColorElementIDs`
も空なのに落ちる。

**規則はブランキングの「行数」ではなく「時間」**（採用側 16 本の最小と、蹴られた 2 本）:

| | vblank 時間 | hblank 時間 | pclk |
|---|---:|---:|---:|
| 採用側の最小 | **174.4 µs** | 0.224 µs | 713.86MHz |
| ❌ 純正 360Hz (hblank140/vblank30) | **75.1 µs** | 0.170 µs | 823.17MHz |
| ❌ 純正 200Hz (hblank80/vblank20) | **90.9 µs** | 0.182 µs | 440.00MHz |

行数の規則（当初 hblank≥160/vblank≥35 と考えた）は**誤り**。640x480@60 は vblank 20 行、
4096x2160@60 は hblank 80 で通っており、行数では説明できない。時間なら全件を説明できる。
帯域でも pclk でもない（441MHz が落ち 571MHz が通る）。

投入した 4 候補のうち使用可能表に入ったのは A と D の 2 本:

| | htotal | vtotal | hbl | vbl | pclk | vblank µs | hblank µs | 結果 |
|---|---:|---:|---:|---:|---:|---:|---:|:--|
| A | 2120 | 1160 | 200 | 80 | 885.31MHz | 191.6 | 0.226 | ✅ 採用（preferred） |
| B | 2136 | 1170 | 216 | 90 | 899.68MHz | 213.7 | 0.240 | — |
| C | 2080 | 1160 | 160 | 80 | 868.61MHz | 191.6 | 0.184 | — |
| D | 2080 | 1144 | 160 | 64 | 856.63MHz | 155.4 | 0.187 | ✅ 採用 |

B・C が出てこないのは**規則で蹴られたとは限らない**: 丸めた表示レートが A/B、C/D で同値になるため
（359.999 と 360.001）、同一レートの重複排除で片方だけ残ったと見るのが素直。判別したいなら
レートをずらした候補で試すこと。

## 使い方

**通常は何もしなくてよい。** ログイン時に LaunchAgent が起動し、接続を検知して自動で適用する。

```
~/display360/display360.log            エージェントのログ
launchctl print gui/$(id -u)/com.local.display360    稼働確認
~/display360/enable360.sh              手動で今すぐ適用
~/display360/uninstall.sh              撤去（300Hz へ戻す）
```

エージェントの方針:
- **接続直後・起動時** は 360Hz へ切り替える。
- **30 秒ごとの点検**では、360Hz が消えていたときだけ入れ直す。利用者が意図的に 300Hz を
  選んでいる場合は切り替えない（ただし次の抜き差しでは 360Hz に戻る）。
- EDID の製造者/製品 ID（`430f/0025`）が一致しないモニタには**何もしない**。

## 制約と注意

- **仮想 EDID は揮発する。** 再起動・抜き差し・スリープ復帰で消えるため常駐が必要。
  ログイン前（ログインウィンドウ）は 300Hz のまま。
- モニタ側は pclk 885.31MHz（純正 823.17MHz の +7.5%）・H 417.6kHz（+4.5%）で駆動している。
  EDID 申告の上限 900MHz 内には収まっている。不安定なら `edid_v2.hex` の候補 A を外して
  D（856.63MHz）だけにすれば純正に近くなる。
- **SIP は無効の状態で作業した**が、この手法自体は SIP を切らなくても動くはず（未検証）。
- `/Library/Displays/.../DisplayProductID-2500`（旧 EDID override）は表示名を変えるだけで
  タイミングには無関係。残っていても害はない。

## ファイル

| | |
|---|---|
| `vedid.c` / `vedid` | **本体**。仮想 EDID の注入・ポート操作・常駐エージェント |
| `edid_v2.hex` | 注入する EDID（360Hz 候補 4 本入り。block0/1 は純正のまま） |
| `build_edid2.py` | その生成器（DisplayID Type I を継ぎ足し・両チェックサム再計算） |
| `set360.py` | 360Hz へ切替＋vsync 実計数（`revert` で 300Hz） |
| `enable360.sh` | 注入→再構築→切替をまとめて実行 |
| `check.py` | 現状判定（override/使用可能表/CG モード一覧） |
| `timings.py` | DCP の候補表・使用可能表を対で読む |
| `parse_edid.py` / `parse2.py` | EDID 解析（引数に hex ファイル） |
| `cgs_modes.py` | 非公開 CGS API で隠しモードまで列挙 |
| `edid.hex` | **純正 EDID（復元用・消さないこと）** |
| `uninstall.sh` | 撤去 |

### vedid のコマンド

```
vedid info              EDID 取得・I2C 読み出し・プロパティ表示
vedid set <hex>         仮想 EDID を注入（AV サービス側）
vedid clear             仮想 EDID を解除
vedid devupd [n]        タイミング表を作り直させる  ← set とセットで使う
vedid ports             IODPPortService 一覧
vedid pset <hex>        全 DP ポートに仮想 EDID（単独では効かない）
vedid hpd               全外部コントローラにホットプラグ強制（切断/復帰のトグル）
vedid daemon [hex]      常駐（LaunchAgent が使う）
```

## 解析の落とし穴（2 回踏んだ）

- `TimingElements` の各要素は `HorizontalAttributes`/`VerticalAttributes` の**入れ子**。内側 dict
  だけを拾うと**水平周波数 (kHz) を垂直レート (Hz) と取り違える**（H 343kHz を「343Hz」と読む）。
- `SyncRate` は **0.5 刻みに丸められている**。実値は `PreciseSyncRate`（どちらも 1/65536 単位）。
- DisplayID Type I の pclk は **(格納値+1) × 10kHz**。+1 を忘れると 0.01MHz ずれる。
- `IODPPortGetAddress` は**出力引数を 3 つ**取る。1 つで呼ぶと即 SIGSEGV。
- `CVDisplayLinkGetActualOutputVideoRefreshPeriod` は**出力ハンドラを付けないと 0 を返す**。
  `CVDisplayLinkSetOutputHandler` のブロックは戻り値が **`(0, 0)` の 2-タプル**でなければ落ちる。
