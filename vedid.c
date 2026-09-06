// 仮想 EDID 注入ツール（macOS 26 / Apple Silicon）
//   IOKit の非公開 API IOAVServiceSetVirtualEDIDMode で、配線上の EDID の代わりに
//   任意の EDID を DCP に食わせられるかを試す。ハードウェア不要。
//
//   ビルド: clang -O2 -o vedid vedid.c -framework IOKit -framework CoreFoundation -framework CoreGraphics
//   使い方: ./vedid info
//           ./vedid set <edid.hex>     仮想 EDID を有効化
//           ./vedid devupd 1           タイミング表を作り直させる（set とセットで使う）
//           ./vedid clear              解除
//           ./vedid hpd                ホットプラグ再検出を強制
//           ./vedid daemon <edid.hex>  常駐（LaunchAgent が使う）
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOKitKeys.h>
#include <unistd.h>
#include <time.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include <ctype.h>

typedef CFTypeRef IOAVServiceRef;
typedef CFTypeRef IOAVControllerRef;

extern IOAVServiceRef IOAVServiceCreateWithService(CFAllocatorRef, io_service_t);
extern IOReturn IOAVServiceCopyEDID(IOAVServiceRef, CFDataRef *);
extern IOReturn IOAVServiceReadI2C(IOAVServiceRef, uint32_t chip, uint32_t off, void *buf, uint32_t len);
extern IOReturn IOAVServiceWriteI2C(IOAVServiceRef, uint32_t chip, uint32_t off, void *buf, uint32_t len);
extern IOReturn IOAVServiceSetVirtualEDIDMode(IOAVServiceRef, uint32_t mode, CFDataRef edid);
extern CFDictionaryRef IOAVServiceCopyProperties(IOAVServiceRef);
extern IOAVControllerRef IOAVControllerCreateWithService(CFAllocatorRef, io_service_t);
extern IOReturn IOAVControllerForceHotPlugDetect(IOAVControllerRef);

typedef CFTypeRef IODPDeviceRef;
extern IODPDeviceRef IODPDeviceCreateWithService(CFAllocatorRef, io_service_t);
extern IOReturn IODPDeviceSetUpdated(IODPDeviceRef, uint32_t);
extern IOReturn IODPDeviceSetUpdateMode(IODPDeviceRef, uint32_t);

typedef CFTypeRef IODPPortRef;
extern IODPPortRef IODPPortCreateWithService(CFAllocatorRef, io_service_t);
// どちらも出力引数を取る（GetAddress は 3 つ）
extern IOReturn IODPPortGetAddress(IODPPortRef, uint32_t *, uint32_t *, uint32_t *);
extern IOReturn IODPPortGetVirtual(IODPPortRef, uint32_t *);
extern IOReturn IODPPortSetVirtual(IODPPortRef, uint32_t);
extern IOReturn IODPPortSetVirtualEDID(IODPPortRef, CFDataRef);
extern IOReturn IODPPortSetPortEvent(IODPPortRef, uint32_t);

// IODPPortService を全部まわして cb を呼ぶ
static int each_port(int (*cb)(IODPPortRef, io_service_t, int, void *), void *ctx) {
    io_iterator_t it = 0;
    IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IODPPortService"), &it);
    io_service_t s; int n = 0;
    while ((s = IOIteratorNext(it))) {
        IODPPortRef p = IODPPortCreateWithService(kCFAllocatorDefault, s);
        if (p) { cb(p, s, n++, ctx); CFRelease(p); }
        IOObjectRelease(s);
    }
    IOObjectRelease(it);
    return n;
}
static int prop_int(io_service_t s, CFStringRef k) {
    CFNumberRef v = IORegistryEntryCreateCFProperty(s, k, kCFAllocatorDefault, 0);
    int x = -1;
    if (v) { CFNumberGetValue(v, kCFNumberIntType, &x); CFRelease(v); }
    return x;
}
static int cb_info(IODPPortRef p, io_service_t s, int i, void *ctx) {
    uint32_t a = 0, b = 0, c = 0, virt = 0xFFFF;
    IOReturn ra = IODPPortGetAddress(p, &a, &b, &c);
    IOReturn rv = IODPPortGetVirtual(p, &virt);
    printf("  port[%d] PortNumber=%d PortVariant=%d PortType=%d  addr=(%u,%u,%u) rc=0x%x"
           "  virtual=%u rc=0x%x\n",
           i, prop_int(s, CFSTR("PortNumber")), prop_int(s, CFSTR("PortVariant")),
           prop_int(s, CFSTR("PortType")), a, b, c, ra, virt, rv);
    return 0;
}
static int cb_setedid(IODPPortRef p, io_service_t s, int i, void *ctx) {
    IOReturn r = IODPPortSetVirtualEDID(p, (CFDataRef)ctx);
    printf("  port[%d] PortNumber=%d PortVariant=%d SetVirtualEDID rc=0x%08x %s\n", i,
           prop_int(s, CFSTR("PortNumber")), prop_int(s, CFSTR("PortVariant")), r,
           r == 0 ? "OK" : "");
    return 0;
}

static void hexdump(const uint8_t *b, size_t n) {
    for (size_t i = 0; i < n; i++) { printf("%02x", b[i]); if ((i & 31) == 31) printf("\n"); }
    if (n & 31) printf("\n");
}

// class 名と Location で IORegistry を引く
static io_service_t find_service(const char *cls, const char *location) {
    io_iterator_t it = 0;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching(cls), &it) != KERN_SUCCESS)
        return 0;
    io_service_t s, found = 0;
    while ((s = IOIteratorNext(it))) {
        CFStringRef loc = IORegistryEntryCreateCFProperty(s, CFSTR("Location"), kCFAllocatorDefault, 0);
        char buf[64] = "";
        if (loc) { CFStringGetCString(loc, buf, sizeof buf, kCFStringEncodingUTF8); CFRelease(loc); }
        if (!location || strcmp(buf, location) == 0) { found = s; break; }
        IOObjectRelease(s);
    }
    IOObjectRelease(it);
    return found;
}

static CFDataRef load_hex(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); return NULL; }
    char txt[8192]; size_t n = fread(txt, 1, sizeof txt - 1, f); txt[n] = 0; fclose(f);
    uint8_t bin[4096]; size_t m = 0;
    for (size_t i = 0; i + 1 < n && m < sizeof bin; ) {
        if (isxdigit((unsigned char)txt[i]) && isxdigit((unsigned char)txt[i+1])) {
            char h[3] = { txt[i], txt[i+1], 0 };
            bin[m++] = (uint8_t)strtol(h, NULL, 16); i += 2;
        } else i++;
    }
    printf("  %s から %zu バイト読み込み\n", path, m);
    return CFDataCreate(kCFAllocatorDefault, bin, m);
}


// ================= 常駐エージェント =================
// ディスプレイが接続されるたびに仮想 EDID を入れ直し、360Hz へ切り替える。
// 仮想 EDID は揮発（再起動・抜き差し・スリープ復帰で消える）ので常駐が要る。

static CFDataRef g_edid;                       // 注入する EDID
static const uint8_t PIXIO_ID[4] = { 0x43, 0x0f, 0x00, 0x25 };   // 製造者/製品 ID

static void logf_ts(const char *fmt, ...) {
    time_t t = time(NULL); struct tm tm; localtime_r(&t, &tm);
    char b[32]; strftime(b, sizeof b, "%Y-%m-%d %H:%M:%S", &tm);
    printf("[%s] ", b);
    va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap);
    fflush(stdout);
}

// 対象ディスプレイ（1920x1080 を持つ外部）を探し、360Hz モードがあれば *out に返す
static CGDirectDisplayID find_target(CGDisplayModeRef *out360, CGDisplayModeRef *out_cur) {
    CGDirectDisplayID ids[16]; uint32_t n = 0;
    if (CGGetOnlineDisplayList(16, ids, &n) != kCGErrorSuccess) return 0;
    for (uint32_t i = 0; i < n; i++) {
        if (CGDisplayIsBuiltin(ids[i])) continue;
        CFArrayRef ms = CGDisplayCopyAllDisplayModes(ids[i], NULL);
        if (!ms) continue;
        CGDisplayModeRef best = NULL;
        for (CFIndex k = 0; k < CFArrayGetCount(ms); k++) {
            CGDisplayModeRef m = (CGDisplayModeRef)CFArrayGetValueAtIndex(ms, k);
            if (CGDisplayModeGetRefreshRate(m) > 355 && CGDisplayModeGetWidth(m) == 1920
                && CGDisplayModeIsUsableForDesktopGUI(m)) best = m;
        }
        if (best) *out360 = CGDisplayModeRetain(best); else *out360 = NULL;
        CFRelease(ms);
        if (out_cur) *out_cur = CGDisplayCopyDisplayMode(ids[i]);
        return ids[i];
    }
    return 0;
}

// 対象モニタかどうかを EDID の製造者/製品 ID で判定
static int is_target_monitor(IOAVServiceRef av) {
    CFDataRef e = NULL;
    if (IOAVServiceCopyEDID(av, &e) != 0 || !e) return 0;
    int ok = CFDataGetLength(e) >= 16 && memcmp(CFDataGetBytePtr(e) + 8, PIXIO_ID, 4) == 0;
    CFRelease(e);
    return ok;
}

// allow_switch=1 … 接続直後/起動時。360Hz へ切り替え、経過もログに書く
// allow_switch=0 … 定期点検。注入が要ったときだけ動き、何もしなければ黙る
//                  （ユーザーが意図的に 300Hz を選んだ状態を壊さないため）
static void apply_once(int allow_switch) {
    const int verbose = allow_switch;
    io_service_t avs = find_service("DCPAVServiceProxy", "External");
    if (!avs) { if (verbose) logf_ts("外部ディスプレイなし — 何もしない\n"); return; }
    IOAVServiceRef av = IOAVServiceCreateWithService(kCFAllocatorDefault, avs);
    IOObjectRelease(avs);
    if (!av) { logf_ts("IOAVServiceCreateWithService 失敗\n"); return; }
    if (!is_target_monitor(av)) {
        if (verbose) logf_ts("対象外のモニタ（製造者/製品 ID 不一致）— 何もしない\n");
        CFRelease(av); return;
    }

    CGDisplayModeRef m360 = NULL, cur = NULL;
    CGDirectDisplayID did = find_target(&m360, &cur);

    int injected = 0;
    if (!m360) {                                   // まだ 360Hz が無い → 注入
        injected = 1;
        IOReturn r = IOAVServiceSetVirtualEDIDMode(av, 1, g_edid);
        logf_ts("仮想 EDID 注入 rc=0x%08x\n", r);
        io_service_t ds = find_service("DCPDPDeviceProxy", "External");
        if (ds) {
            IODPDeviceRef d = IODPDeviceCreateWithService(kCFAllocatorDefault, ds);
            IOObjectRelease(ds);
            if (d) {
                r = IODPDeviceSetUpdated(d, 1);
                logf_ts("タイミング表 再構築 rc=0x%08x\n", r);
                CFRelease(d);
            }
        }
        for (int i = 0; i < 40 && !m360; i++) {     // 反映を最大 4 秒待つ
            usleep(100000);
            if (cur) { CGDisplayModeRelease(cur); cur = NULL; }
            did = find_target(&m360, &cur);
        }
    }
    CFRelease(av);

    if (!m360) { logf_ts("360Hz モードが生えなかった\n"); if (cur) CGDisplayModeRelease(cur); return; }

    double now = cur ? CGDisplayModeGetRefreshRate(cur) : 0;
    if (now > 355) {
        if (verbose) logf_ts("既に %.3fHz — 切替不要\n", now);
    } else if (!injected && !allow_switch) {
        /* 360Hz は選択可能で、利用者が別のレートを選んでいる。黙って尊重する。 */
    } else {
        CGDisplayConfigRef cfg;
        if (CGBeginDisplayConfiguration(&cfg) == kCGErrorSuccess) {
            CGConfigureDisplayWithDisplayMode(cfg, did, m360, NULL);
            CGError e = CGCompleteDisplayConfiguration(cfg, kCGConfigurePermanently);
            logf_ts("360Hz へ切替 (%.3fHz→360) rc=%d\n", now, e);
        }
    }
    CGDisplayModeRelease(m360);
    if (cur) CGDisplayModeRelease(cur);
}

// IOKit のサービス出現通知（＝ディスプレイ接続）で叩かれる
static void on_match(void *ref, io_iterator_t it) {
    io_service_t s; int n = 0;
    while ((s = IOIteratorNext(it))) { IOObjectRelease(s); n++; }
    if (n == 0) return;
    logf_ts("ディスプレイ接続を検知（%d 件）\n", n);
    usleep(1200000);                               // 列挙が落ち着くまで待つ
    apply_once(1);
}

static int run_daemon(const char *edidpath) {
    g_edid = load_hex(edidpath);
    if (!g_edid) return 1;
    logf_ts("常駐開始 (EDID %ld バイト)\n", (long)CFDataGetLength(g_edid));
    apply_once(1);

    IONotificationPortRef np = IONotificationPortCreate(kIOMainPortDefault);
    CFRunLoopAddSource(CFRunLoopGetCurrent(), IONotificationPortGetRunLoopSource(np),
                       kCFRunLoopDefaultMode);
    io_iterator_t it = 0;
    IOServiceAddMatchingNotification(np, kIOMatchedNotification,
                                     IOServiceMatching("DCPAVServiceProxy"),
                                     on_match, NULL, &it);
    io_service_t s;                                 // 既存分を空読みして通知を有効化
    while ((s = IOIteratorNext(it))) IOObjectRelease(s);

    // 保険: スリープ復帰など通知が来ない経路のために 30 秒ごとに点検する。
    // 360Hz が消えていたときだけ入れ直し、モード切替は勝手にしない。
    CFRunLoopTimerRef t = CFRunLoopTimerCreateWithHandler(
        kCFAllocatorDefault, CFAbsoluteTimeGetCurrent() + 30, 30,
        0, 0, ^(CFRunLoopTimerRef _t) { apply_once(0); });
    CFRunLoopAddTimer(CFRunLoopGetCurrent(), t, kCFRunLoopDefaultMode);

    CFRunLoopRun();
    return 0;
}

int main(int argc, char **argv) {
    const char *cmd = argc > 1 ? argv[1] : "info";

    if (!strcmp(cmd, "daemon"))
        return run_daemon(argc > 2 ? argv[2] : "edid_v2.hex");

    if (!strcmp(cmd, "devupd")) {          // DP デバイスに「更新された」と通知して再パースさせる
        uint32_t v = argc > 2 ? (uint32_t)atoi(argv[2]) : 1;
        io_service_t ds = find_service("DCPDPDeviceProxy", "External");
        if (!ds) { printf("DCPDPDeviceProxy(External) なし\n"); return 1; }
        IODPDeviceRef d = IODPDeviceCreateWithService(kCFAllocatorDefault, ds);
        printf("IODPDeviceRef = %p\n", d);
        if (!d) return 1;
        IOReturn r = IODPDeviceSetUpdated(d, v);
        printf("IODPDeviceSetUpdated(%u) rc=0x%08x %s\n", v, r, r == 0 ? "★成功" : "");
        return 0;
    }
    if (!strcmp(cmd, "ports")) {                       // 読み取りのみ
        printf("IODPPortService 一覧:\n");
        printf("  合計 %d ポート\n", each_port(cb_info, NULL));
        return 0;
    }
    if (!strcmp(cmd, "pset")) {                        // 全 DP ポートに仮想 EDID を載せる
        if (argc < 3) { printf("使い方: vedid pset <edid.hex>\n"); return 1; }
        CFDataRef d = load_hex(argv[2]);
        if (!d) return 1;
        printf("全 %d ポートに投入\n", each_port(cb_setedid, (void *)d));
        return 0;
    }

    // hpd は切断中でも動く必要があるので、AV サービスに依存させない
    if (!strcmp(cmd, "hpd")) {
        io_iterator_t it = 0;
        IOServiceGetMatchingServices(kIOMainPortDefault,
                                     IOServiceMatching("DCPAVControllerProxy"), &it);
        io_service_t s; int n = 0;
        while ((s = IOIteratorNext(it))) {
            CFStringRef loc = IORegistryEntryCreateCFProperty(s, CFSTR("Location"),
                                                              kCFAllocatorDefault, 0);
            char lb[64] = "";
            if (loc) { CFStringGetCString(loc, lb, sizeof lb, kCFStringEncodingUTF8); CFRelease(loc); }
            if (!strcmp(lb, "External")) {
                IOAVControllerRef c = IOAVControllerCreateWithService(kCFAllocatorDefault, s);
                if (c) {
                    IOReturn r = IOAVControllerForceHotPlugDetect(c);
                    printf("  ForceHotPlugDetect[%d] rc=0x%08x %s\n", n, r, r == 0 ? "OK" : "");
                    CFRelease(c); n++;
                }
            }
            IOObjectRelease(s);
        }
        IOObjectRelease(it);
        printf("外部コントローラ %d 個に HPD を送出\n", n);
        return 0;
    }

    io_service_t avsvc = find_service("DCPAVServiceProxy", "External");
    if (!avsvc) { printf("外部ディスプレイの DCPAVServiceProxy が見つからない\n"); return 1; }
    printf("DCPAVServiceProxy(External) を取得\n");

    IOAVServiceRef av = IOAVServiceCreateWithService(kCFAllocatorDefault, avsvc);
    if (!av) { printf("IOAVServiceCreateWithService 失敗（root 権限が要るかも）\n"); return 1; }
    printf("IOAVServiceRef = %p\n\n", av);

    if (!strcmp(cmd, "info")) {
        CFDataRef edid = NULL;
        IOReturn r = IOAVServiceCopyEDID(av, &edid);
        printf("[1] IOAVServiceCopyEDID  rc=0x%08x  len=%ld\n", r,
               edid ? (long)CFDataGetLength(edid) : -1L);
        if (edid) { hexdump(CFDataGetBytePtr(edid), CFDataGetLength(edid)); CFRelease(edid); }

        uint8_t buf[128];
        for (uint32_t chip = 0x50; chip <= 0x51; chip++) {
            memset(buf, 0xAA, sizeof buf);
            r = IOAVServiceReadI2C(av, chip, 0, buf, sizeof buf);
            printf("\n[2] ReadI2C chip=0x%02x off=0  rc=0x%08x\n", chip, r);
            if (r == 0) hexdump(buf, 32);
        }
        CFDictionaryRef props = IOAVServiceCopyProperties(av);
        printf("\n[3] IOAVServiceCopyProperties = %p\n", props);
        if (props) { CFShow(props); CFRelease(props); }
        return 0;
    }

    if (!strcmp(cmd, "set")) {
        if (argc < 3) { printf("使い方: vedid set <edid.hex>\n"); return 1; }
        CFDataRef d = load_hex(argv[2]);
        if (!d) return 1;
        IOReturn r = IOAVServiceSetVirtualEDIDMode(av, 1, d);
        printf("IOAVServiceSetVirtualEDIDMode(mode=1, %ld バイト) rc=0x%08x %s\n",
               (long)CFDataGetLength(d), r, r == 0 ? "★成功" : "");
        return r != 0;
    }
    if (!strcmp(cmd, "clear")) {
        IOReturn r = IOAVServiceSetVirtualEDIDMode(av, 0, NULL);
        printf("IOAVServiceSetVirtualEDIDMode(mode=0) rc=0x%08x %s\n", r, r == 0 ? "★成功" : "");
        return r != 0;
    }
    printf("不明なコマンド: %s\n", cmd);
    return 1;
}
