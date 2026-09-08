# display360

[English](README.md) · [![ci](https://github.com/owomocha/display360/actions/workflows/ci.yml/badge.svg)](https://github.com/owomocha/display360/actions)

手持ちのモニタは 360Hz 対応。なのに macOS は 300Hz までしか出さない。残りの 60Hz を何も買わずに取り返した方法がこれ: 少し書き換えた EDID を非公開の IOKit API 経由でディスプレイ用コプロセッサ（DCP）に渡し、そのモードを捨てていたタイミング表を作り直させる。EDID と目当てのレートを渡すだけで、抜き差しのたびに小さな常駐エージェントが入れ直す。

「設定画面に 360 と出た」ではなく、vsync を数えて確認している:

```
モード申告     : 360.0000 Hz
vsync 実計数   : 359.9977 Hz   (5.000 秒で 1801 フレーム・CVDisplayLink のコールバックで計数)
フレーム間隔   : 中央値 2.7775 ms
```

環境は MacBook Pro 16" M2 Pro (Mac14,10)、macOS 26.5.2、Pixio PX259PS を USB-C（DP alt mode）で接続。非公開の `IOAVService*` / `IODP*` を叩き、パネルを規定よりわずかに速いタイミングで駆動する——8月末から問題なく使えているが、注意点は先に読んでほしい。

360 固有の部分は無い。`build_edid.py` とデーモンは解像度とレートを引数で受け取り、モニタは EDID 内の製造者/製品 ID で照合するので、その EDID 用でないモニタには触らない。前提は、Apple Silicon（タイミング表を持つのが DCP なので）と DisplayPort 接続、タイミングを DisplayID Type I ブロックに持つモニタ（Type VII や CTA の DTD はまだ非対応）、そして macOS が下記のブランキング規則で蹴っているモードであること——リンクが物理的に運べないモードは EDID では直らない。検証はモニタ1台。それ以外はその1台での DCP の挙動からの外挿。

## なぜ DCP はモードを落とすのか

PX259PS の EDID には最初から 1920x1080 @ 360Hz が入っていて、DCP が検討する様子まで見える: 候補表 `PreferredTimingElements` で全候補中最高スコア（16846・300Hz は 15922）、`UnsafeColorElementIDs` も空——なのに実際に使われる表 `TimingElements` には無い。DCP が落としたモードを公開 API から足す手段は無く、昔の `DisplayProductID-xxxx` の override はもう DCP まで届かない（うちでは表示名が変わっただけ）。

そこで受理された 16 本と蹴られた 2 本を全部ダンプして規則を探した。ブランキング行数の下限ではない——640x480@60 は vblank 20 行で通る。帯域やピクセルクロックでもない——441MHz が落ちて 571MHz は通る。きれいに分かれたのはブランキングの「時間」だった:

| | vblank | hblank | pclk |
|---|---:|---:|---:|
| 受理側で最小 | **174.4 µs** | 0.224 µs | 713.86 MHz |
| 純正 360Hz（却下） | **75.1 µs** | 0.170 µs | 823.17 MHz |
| 純正 200Hz（却下） | **90.9 µs** | 0.182 µs | 440.00 MHz |

受理されたモードは vblank 174µs 以上、蹴られた 2 本はそれよりずっと短い。純正 360Hz は DCP には詰めすぎ。そこで、ブロック 0 と 1 はバイト単位でそのまま、純正 300Hz も残し、ブランキングを太らせた 360Hz 候補を 4 本足した EDID を作った:

| | htotal | vtotal | hblank | vblank | pclk | vblank 時間 | |
|---|---:|---:|---:|---:|---:|---:|---|
| A | 2120 | 1160 | 200 | 80 | 885.31 MHz | 191.6 µs | 受理・preferred |
| B | 2136 | 1170 | 216 | 90 | 899.68 MHz | 213.7 µs | 出てこない |
| C | 2080 | 1160 | 160 | 80 | 868.61 MHz | 191.6 µs | 出てこない |
| D | 2080 | 1144 | 160 | 64 | 856.63 MHz | 155.4 µs | 受理 |

出てきたのは A と D。A と B はどちらも 359.999Hz に、C と D は 360.001Hz に丸まるので、B と C は却下ではなく重複として畳まれたのだと思う。面白いのは D で、vblank 155µs は最初に測った下限 174µs より短いのに通る——本当の閾値は 91〜155µs のどこか。使っているのは A: `1920x1080, htotal 2120 / vtotal 1160, pclk 885.31 MHz, H 417.6 kHz`。

この数字を読むのにも罠がある。`SyncRate` は 0.5Hz 刻みに丸められていて、本当の値は `PreciseSyncRate`（どちらも 1/65536 単位）。DisplayID Type I のピクセルクロックは `(値 + 1) × 10kHz` で、+1 を忘れると全レートが 0.01MHz 低く出る。Range Limits には offset flag があり、bit 1 が立つと V 上限に 255 が足される——このパネルが「48〜105Hz」でなく「48〜360Hz」を申告しているのはこれ（H レンジ欄は `255〜255kHz` と壊れているので使わない）。

## 効いた 2 つの呼び出し

```c
IOAVServiceSetVirtualEDIDMode(av, 1, edid);   // DCP に差し替え用の EDID を渡す          (selector 23)
IODPDeviceSetUpdated(dp, 1);                  // 再パースしてタイミング表を作り直させる  (selector 5)
```

1 つ目だけだと、成功したように見えて何も起きない: `IOAVServiceCopyEDID` は渡したバイト列を返すのに、タイミング表は接続時に作られたままで誰も作り直さない。それをやらせるのが 2 つ目。手を出してはいけないのが `IOAVControllerForceHotPlugDetect`——EDID は読み直すが、配線上のやつを。ホットプラグで AV サービスごと作り直され、仮想 EDID も一緒に消える（2 回やって 2 回真っ暗になった）。どれもヘッダが無いので、シグネチャは dyld 共有キャッシュ上の実装を逆アセンブルして確定した:

| 関数 | 引数 | selector |
|---|---|---|
| `IOAVServiceSetVirtualEDIDMode` | `(IOAVServiceRef, uint32_t mode, CFDataRef edid)` | 23 |
| `IODPDeviceSetUpdated` | `(IODPDeviceRef, uint32_t)` | 5 |
| `IOAVServiceReadI2C` / `WriteI2C` | `(ref, chip, offset, buf, len)` | 24 / 25 |
| `IODPPortSetVirtual` | `(IODPPortRef, uint32_t)` | 0 |
| `IODPPortSetVirtualEDID` | `(IODPPortRef, CFDataRef)` | 4 |
| `IODPPortGetAddress` | `(ref, uint32_t*, uint32_t*, uint32_t*)` | |

`IODPPortGetAddress` は出力ポインタを 3 つ取る。1 つで呼んだら即 SIGSEGV、メッセージ無し。入れ子も刺さる: `TimingElements` の各要素は `HorizontalAttributes` / `VerticalAttributes` を包んでいて、よく見ずに内側の dict を取ると水平周波数（kHz）を垂直レートとして読む。「343Hz のモードって何だ」としばらく悩んだ。

## 使い方

Apple Silicon、Xcode Command Line Tools（`clang`・`make`）、切替と計測のスクリプト用に PyObjC の Quartz を入れた Python 3（`pip install pyobjc-framework-Quartz`）。生成器と解析器は素の Python で動く。

```sh
git clone https://github.com/owomocha/display360 && cd display360
make
./vedid edid > edid/mine.hex                    # モニタの純正 EDID を 1 行 hex で（読み取り専用）
python3 parse_edid.py edid/mine.hex             # 何が申告され、目当てのタイミングがどこにあるか
python3 build_edid.py edid/mine.hex --rate 360  # -> edid/mine-360.hex と候補一覧
./enable.sh edid/mine-360.hex 1920 360          # 注入・再構築・切替・5 秒 vsync 計数
python3 check.py --rate 360                      # 360 が DCP の使用可能表にあるか・CoreGraphics に見えるか
```

別の解像度/レートなら `build_edid.py edid/mine.hex --rate 240 --width 2560 --height 1440`。既定候補はうちで通った 4 組のブランキング（`--blanking 200x80,216x90,160x80,160x64`・hblank×vblank・先頭が preferred）。生成器は候補ごとの vblank 時間を出し、155µs 未満に印を付ける。ピクセルクロック上限は EDID の Range Limits から読む（`--force` で無視）。同梱の `edid/pixio-px259ps.hex`（シリアル無し・確認済み）と `-360` 版は `enable.sh` / `install.sh` の既定値でもあるので、同じモニタなら引数なしで動く。戻すにはシステム設定で元のレートを選ぶか `setmode.py revert --rate 300`、またはケーブルを抜く。

仮想 EDID は抜き差しで消えるので、ずっと有効にするには:

```sh
./install.sh edid/mine-360.hex 1920 360    # ~/Library/LaunchAgents/com.local.display360.plist を書いて起動
./uninstall.sh                             # 停止して削除・sudo 不要
```

`vedid daemon` は `DCPAVServiceProxy` の IOKit マッチング通知を待ち、ディスプレイ接続時に注入・再構築・切替を行う。30 秒ごとに再確認して消えていた時だけ入れ直し（スリープ復帰で消える）、目当てのモードが選べる状態で自分が別レートを選んでいれば張り合わず、EDID の 8〜11 バイト目でモニタを照合するので別のモニタには何もしない。ログはバイナリと同じ場所の `display360.log`。候補が出てこないときは `python3 timings.py 100` が DCP の候補表と使用可能表を並べ、各行に `[usable]`/`[dropped]` を付ける——一番速いフィードバックループ。全部落ちるならブランキングを太らせ、候補にすら出ないなら注入自体が効いていない。

## 注意点

`IOAVService*` / `IODP*` はどれも文書化されておらず、macOS のアップデートで黙って壊れうる（`cgs_modes.py` も隠しモード列挙に非公開の `CGSGetDisplayModeDescriptionOfLength` を使う）。候補 A はパネルを 885.31MHz で駆動し、純正 360Hz より 7.5%・水平 417.6kHz も 4.5% 高い——EDID 申告の上限 900MHz の内側で手元は問題ないが、ちらつくなら控えめな候補 1 本に（`--blanking 160x64`・D の 856.63MHz）。仮想 EDID は揮発する: 再起動・抜き差し・スリープで消え、ログイン画面（セッション前）は元のレートのまま。別件で SIP を切った状態で作ったので SIP 有効は未検証——ユーザークライアントには届くはずだが確認していない推測。画面が真っ暗になったら `./vedid hpd` で配線上の EDID に戻せる。システムに書き込むのはホームの LaunchAgent plist だけ。

## ファイル

`vedid.c` が本体——EDID の取得と注入、DP デバイス/ポート操作、ホットプラグ、常駐（サブコマンド `info edid set clear devupd ports pset hpd daemon`・ソース冒頭に一行ずつ説明）。Python 側は、`build_edid.py` が DisplayID Type I ブロックを書き換えて両チェックサムを計算し直し、`parse_edid.py` が全ブロック（base・CTA-861・DisplayID）を解読、`setmode.py` がモードの一覧/選択と vsync 実計数（`revert` で戻す）、`check.py` が 1 発の状態判定、`timings.py` が候補表と使用可能表の差分、`cgs_modes.py` が非公開 CGS API で隠しモードまで列挙。`enable.sh` は注入→再構築→切替→計測を繋ぎ、`install.sh` / `uninstall.sh` が LaunchAgent の導入と撤去。`tests/` は生成器が同梱 EDID をバイト単位で再現できることと境界のテスト（`make test`）。CI は macOS ランナーで回すが注入自体は試せない——実機とモニタが要る。

MIT。
