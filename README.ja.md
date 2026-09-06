# display360

[English](README.md) · [![ci](https://github.com/owomocha/display360/actions/workflows/ci.yml/badge.svg)](https://github.com/owomocha/display360/actions)

手持ちのモニタは 360Hz 対応。なのに macOS は 300Hz までしか出してくれない。残りの 60Hz を何も買わずに取り返した話と、その過程でできた道具です。モニタの EDID と欲しいリフレッシュレートを渡すと、macOS が捨てていたタイミングを受け入れさせます。

ざっくり言うと、Mac のディスプレイ用コプロセッサ（DCP）が、モニタの EDID に入っている 360Hz のタイミングを捨てているのが原因でした。なので、少しだけ書き換えた EDID を非公開の IOKit API 経由で DCP に渡して、タイミング表を作り直させます。これで 360Hz が「システム設定」の選択肢に普通に出てきます。抜き差しや再起動で消えるので、小さな常駐エージェントが毎回入れ直します。

「設定画面に 360 と出た」ではなく、実際に vsync を数えて確認しています。

```
モード申告     : 360.0000 Hz
vsync 実計数   : 359.9977 Hz   (5.000 秒で 1801 フレーム・CVDisplayLink のコールバックで計数)
フレーム間隔   : 中央値 2.7775 ms
```

環境は MacBook Pro 16" M2 Pro (Mac14,10)、macOS 26.5.2、Pixio PX259PS を USB-C（DP alt mode）で接続。

先に断っておくと、これは非公開の IOKit 関数（`IOAVService*` と `IODP*`）を叩いていて、パネルを規定よりわずかに速いタイミングで駆動しています。8 月末からずっと使っていて問題は出ていませんが、ハックであることに変わりはないので、[注意点](#注意点)を読んでから試してください。

## 対応範囲

名前が 360 なのは、うちのモニタが 300 から 360 になったからというだけです。ツールの中に 360Hz 固有の部分はありません。`build_edid.py` は欲しい解像度とレートを引数で受け取り、デーモンも引数で受け取ります。デーモンはモニタの製造者/製品 ID を渡された EDID から読むので、その EDID 用でないモニタには手を出しません。

それでも前提にしていることがあります。

- Apple Silicon（タイミング表を持っているのが DCP なので）と DisplayPort 接続（USB-C alt mode か Thunderbolt）。HDMI は未検証。
- モニタがタイミングを DisplayID Type I ブロックに持っていること。`build_edid.py` が書き換えるのはそこです。Type VII ブロックや CTA の DTD にある場合はまだ扱えないので、EDID を添えて issue を立ててください。
- macOS がそのモードを蹴っている理由が、下で説明するブランキング時間の規則であること。リンクの帯域が足りない、DSC が無い、といった理由で出てこないモードは、EDID をいじっても出ません。
- 検証したのはモニタ 1 台。それ以外は、その 1 台で DCP がどう振る舞ったかからの外挿です。別のモニタで試したら結果を教えてもらえると嬉しいです。

## 何が起きているのか

PX259PS の EDID には最初から 1920x1080 @ 360Hz のタイミングが入っています（DisplayID Type I ブロック）。DCP がそれを検討している様子まで見えます。候補表 `PreferredTimingElements` には載っていて、スコアは全候補中で最高（16846。300Hz は 15922）、`UnsafeColorElementIDs` も空。それなのに、実際に使われる表 `TimingElements` には入っていません。DCP が落としたモードを公開 API から足す手段はなく、昔ながらの `/Library/Displays/.../DisplayProductID-xxxx` の override はそもそも DCP まで届きません。うちの環境では表示名が変わっただけでした。

というわけで問いは「なぜそのタイミングだけ落ちるのか。落ちないタイミングを食わせられないか」になりました。

## なぜ落とされるのか

DCP が受け入れたタイミング 16 本と、蹴った 2 本を全部ダンプして規則を探しました。最初に疑ったのはブランキングの行数の下限。これは外れで、640x480@60 は vblank 20 行で通っているし、4096x2160@60 は hblank 80 ピクセルで通っています。帯域やピクセルクロックでもない。441MHz が落ちて 571MHz が通るので説明がつきません。

きれいに分かれたのはブランキングの「時間」でした。

| | vblank | hblank | pclk |
|---|---:|---:|---:|
| 受理側で最小のもの | **174.4 µs** | 0.224 µs | 713.86 MHz |
| 純正 360Hz（却下） | **75.1 µs** | 0.170 µs | 823.17 MHz |
| 純正 200Hz（却下） | **90.9 µs** | 0.182 µs | 440.00 MHz |

受理されたモードはどれも vblank が 174µs 以上で、蹴られた 2 本はそれよりずっと短い。モニタ純正の 360Hz は DCP の好みには詰めすぎだった、ということです。そこで、ブロック 0 と 1 はバイト単位でそのまま、純正の 300Hz も残したまま、ブランキングを太らせた 360Hz 候補を 4 本足した EDID を作りました。

| | htotal | vtotal | hblank | vblank | pclk | vblank 時間 | |
|---|---:|---:|---:|---:|---:|---:|---|
| A | 2120 | 1160 | 200 | 80 | 885.31 MHz | 191.6 µs | 受理・preferred |
| B | 2136 | 1170 | 216 | 90 | 899.68 MHz | 213.7 µs | 出てこない |
| C | 2080 | 1160 | 160 | 80 | 868.61 MHz | 191.6 µs | 出てこない |
| D | 2080 | 1144 | 160 | 64 | 856.63 MHz | 155.4 µs | 受理 |

出てきたのは A と D。B と C は規則で蹴られたのではなく、丸めた表示レートが A/B、C/D で同じ値（359.999 と 360.001）になるので重複として畳まれたのだと思っています。白黒つけたければレートを少しずらして試せば分かりますが、A が通った時点で満足して止めました。面白いのは D で、vblank 155µs は最初に測った下限 174µs より短いのに通っています。つまり本当の閾値は 91〜155µs のどこか。実用上はこれで十分。

使っているのは A です。`1920x1080, htotal 2120 / vtotal 1160, pclk 885.31 MHz, H 417.6 kHz`。

## 効いた 2 つの呼び出し

```c
IOAVServiceSetVirtualEDIDMode(av, 1, edid);   // DCP に差し替え用の EDID を渡す         (user client selector 23)
IODPDeviceSetUpdated(dp, 1);                  // 再パースしてタイミング表を作り直させる  (selector 5)
```

1 つ目だけだと、成功したように見えて何も起きません。`IOAVServiceCopyEDID` は渡したバイト列を返してくるのに、タイミング表は接続時に作られたままで、誰も作り直してくれない。それをやらせるのが 2 つ目です。

やってはいけないのが `IOAVControllerForceHotPlugDetect`。いかにも「EDID を読み直すボタン」に見えるし、実際 EDID は読み直されます。ただし配線上のやつを。ホットプラグで AV サービスごと作り直されるので、仮想 EDID も一緒に消えます。これを 2 回やって 2 回画面が真っ暗になり、もっと穏やかな方法を探しに行きました。ポート側の `IODPPortSetVirtualEDID`（切断しても残る）も単独では効かず。`IODPPortSetVirtual` でポートを virtual にしてからでないと参照されないようですが、`IODPDeviceSetUpdated` が効いた時点で不要になりました。

どれもヘッダが無いので、シグネチャは dyld 共有キャッシュ上の実装を逆アセンブルして確定させました。

| 関数 | 引数 | selector |
|---|---|---|
| `IOAVServiceSetVirtualEDIDMode` | `(IOAVServiceRef, uint32_t mode, CFDataRef edid)` | 23 |
| `IODPDeviceSetUpdated` | `(IODPDeviceRef, uint32_t)` | 5 |
| `IOAVServiceReadI2C` / `WriteI2C` | `(ref, chip, offset, buf, len)` | 24 / 25 |
| `IODPPortSetVirtual` | `(IODPPortRef, uint32_t)` | 0 |
| `IODPPortSetVirtualEDID` | `(IODPPortRef, CFDataRef)` | 4 |
| `IODPPortGetAddress` | `(ref, uint32_t*, uint32_t*, uint32_t*)` | |

最後のやつは出力ポインタを 3 つ取ります。最初 1 つで呼んだら即 SIGSEGV。メッセージも何も無し。勉強になりました。

## 使い方

Apple Silicon の Mac、Xcode Command Line Tools（`clang` と `make`）、それと切替と計測のスクリプト用に PyObjC の Quartz が入った Python 3（`pip install pyobjc-framework-Quartz`）が要ります。生成器と解析器は素の Python で動きます。

```sh
git clone https://github.com/owomocha/display360 && cd display360
make                                              # vedid をビルド

./vedid edid > edid/mine.hex                      # モニタの純正 EDID を 1 行の hex で保存（読み取り専用）
python3 parse_edid.py edid/mine.hex               # 何が申告されていて、目当てのタイミングがどこにあるか
python3 build_edid.py edid/mine.hex --rate 360    # -> edid/mine-360.hex と、候補の一覧表
./enable.sh edid/mine-360.hex 1920 360            # 注入 → 再構築 → 切替 → 5 秒間 vsync を数える
python3 check.py --rate 360                       # 今 360Hz が DCP の使用可能表にあるか、CoreGraphics に見えているか
```

解像度やレートが違うなら `build_edid.py edid/mine.hex --rate 240 --width 2560 --height 1440` のように指定します。既定の候補は、うちで通った 4 組のブランキング（`--blanking 200x80,216x90,160x80,160x64`、hblank x vblank。先頭が preferred になる）。生成器は候補ごとの垂直ブランキング時間を表示して、DCP が受理したのを見た最短の 155µs を下回るものに印を付けます。ピクセルクロックの上限は EDID 自身の Range Limits から読みます（`--force` で無視）。

`edid/pixio-px259ps.hex` は手元の PX259PS の純正 EDID（シリアル番号は入っていません。確認済み）、`edid/pixio-px259ps-360.hex` は生成器がそれから作ったものです。`enable.sh` と `install.sh` の既定値もこの 2 つなので、同じモニタなら引数なしで動きます。

戻すには、システム設定で元のレートを選ぶか、`python3 setmode.py revert --rate 300`、あるいはケーブルを抜けば OK。仮想 EDID は抜き差しで消えます。それが次の節がある理由です。

### ずっと有効にしておく

```sh
./install.sh edid/mine-360.hex 1920 360    # 必要なら vedid をビルドし、~/Library/LaunchAgents/com.local.display360.plist を書いて起動
./uninstall.sh                             # 停止して削除（sudo 不要）
```

`vedid daemon <edid> <width> <rate>` は `DCPAVServiceProxy` の IOKit マッチング通知を待っていて、ディスプレイが接続されたら注入・再構築・切替を行い、幅 `<width>` で `<rate>` Hz のモードに合わせます。30 秒ごとにモードがまだあるかも見ていて、消えていた時だけ入れ直します（スリープ復帰で消えます）。勝手に張り合わないようにもしてあって、目当てのモードが選べる状態であなたが別のレートを選んでいるなら、次の抜き差しまでそっとしておきます。モニタの製造者/製品 ID は渡された EDID の 8〜11 バイト目と照合するので、別のモニタを挿しても何もしません。

ログはバイナリと同じ場所の `display360.log`、状態は `launchctl print gui/$(id -u)/com.local.display360` で見られます。

## 候補が出てこないとき

`python3 timings.py 100` で DCP の候補表と使用可能表を並べて出せます。候補ごとに `[usable]` か `[dropped]` が付くので、どれが通ったか一目で分かります。これが一番速いフィードバックループでした。全部落ちるならブランキングを太らせる（`--blanking 240x100,200x80`）。候補表にすら出てこないなら注入自体が効いていないので、`display360.log` を見て、上のホットプラグの注意も読んでください。

## 注意点

- **非公開 API。** `IOAVService*` と `IODP*` はどれも文書化されていません。macOS のアップデートで黙って壊れる可能性があります。`cgs_modes.py` も隠しモードを列挙するのに非公開の `CGSGetDisplayModeDescriptionOfLength` を使っています。
- **少しだけ規定外。** 候補 A はうちのパネルをピクセルクロック 885.31MHz で駆動していて、モニタ自身の 360Hz タイミングより 7.5% 高く、水平周波数 417.6kHz も 4.5% 高い。EDID が申告する上限 900MHz の内側で、手元では問題なしですが、ちらつくようなら控えめな候補 1 本にしてください（`--blanking 160x64`、D の 856.63MHz）。
- **揮発する。** 再起動、抜き差し、スリープ。どれでも仮想 EDID は消えます。ログイン画面（セッションに入る前）は元のレートのまま。
- **SIP。** 別件の都合で SIP を切った状態で作りました。その環境では一般ユーザー権限で動いています。SIP 有効では未検証。IOKit のユーザークライアントには届くはずだと思っていますが、確認していない推測です。
- **画面が真っ暗になったら**: `./vedid hpd` で外部コントローラにホットプラグを強制すると、配線上の EDID で復帰します。ケーブルの抜き差しでも同じ。システムに書き込むものはホームディレクトリの LaunchAgent plist 以外にありません。

## ファイル

| | |
|---|---|
| `vedid.c` | 本体。EDID の取得と注入、DP デバイス/ポート操作、ホットプラグ、常駐 |
| `build_edid.py` | 生成器。DisplayID Type I ブロックを書き換えて両チェックサムを計算し直す |
| `parse_edid.py` | EDID の全ブロックを解読（base、CTA-861、DisplayID） |
| `enable.sh` | 注入 → 再構築 → 切替 → 計測 |
| `setmode.py` | 目当てのモードの一覧と選択、vsync の実計数。`revert` で戻す |
| `check.py` | 現状を 1 発で判定。`--set` で切替と計測まで |
| `timings.py` | DCP の候補表と使用可能表を並べて表示 |
| `cgs_modes.py` | 非公開の CGS API で隠しモードまで全部列挙 |
| `install.sh` / `uninstall.sh` | LaunchAgent の導入と撤去 |
| `edid/` | うちのモニタの純正 EDID と、生成したもの |
| `tests/` | 生成器が同梱の EDID をバイト単位で再現できること、ほか境界のテスト（`make test`） |

`vedid` のサブコマンド: `info`、`edid`、`set <hex>`、`clear`、`devupd [n]`、`ports`、`pset <hex>`、`hpd`、`daemon <hex> [width] [rate]`。ソースの冒頭に一行ずつ説明があります。

CI は macOS のランナーでビルドとテストを回します。注入そのものは試せません。実機とモニタが要るので。

## ハマったところ

- `TimingElements` の各要素は `HorizontalAttributes` / `VerticalAttributes` の入れ子。よく見ずに内側の dict を取ると、水平周波数（kHz）を垂直レートとして読んでしまう。「343Hz のモードって何だ」としばらく悩みました。
- `SyncRate` は 0.5Hz 刻みに丸められています。本当の値は `PreciseSyncRate`。どちらも 1/65536 単位。
- DisplayID Type I のピクセルクロックは `(値 + 1) × 10kHz`。最初の生成器は +1 を忘れていて、全部のレートが 0.01MHz 低く出ていました。壊れはしないけど数字が合わなくて気持ち悪い。
- EDID の Range Limits には offset flag があります。bit 1 が立つと V の上限に 255 が足されて、このパネルは「48〜105Hz」ではなく「48〜360Hz」を申告している。H のレンジ欄は壊れていて（`255〜255kHz`）、判断には使えません。
- `CVDisplayLinkGetActualOutputVideoRefreshPeriod` は出力ハンドラを付けるまで 0 を返します。Python からだとハンドラは `(0, 0)` のタプルを返さないとプロセスごと落ちます。

## ライセンス

MIT。
