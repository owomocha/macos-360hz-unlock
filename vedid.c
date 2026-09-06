// vedid: virtual EDID injection for Apple Silicon Macs (written against macOS 26).
//
// Hands the display coprocessor (DCP) a replacement EDID through the private
// IOAVService / IODPDevice user clients and makes it rebuild its timing table,
// so a timing macOS rejected (for me: my monitor's own 360 Hz mode) becomes a
// normal entry in System Settings. No extra hardware.
//
//   build:  make    (= clang -O2 -o vedid vedid.c -framework IOKit -framework CoreFoundation -framework CoreGraphics)
//
//   vedid info                        dump the wired EDID, I2C reads and AV service properties (read-only)
//   vedid edid                        print the wired EDID as one hex line (feed it to build_edid.py)
//   vedid set <edid.hex>              inject a virtual EDID (AV service side)
//   vedid devupd [n]                  tell the DP device it was updated -> DCP rebuilds its timings (right after set)
//   vedid clear                       remove the virtual EDID
//   vedid ports                       list IODPPortService objects
//   vedid pset <edid.hex>             set a virtual EDID on every DP port (does nothing on its own)
//   vedid hpd                         force hot-plug detect on external controllers (drops the display, re-enumerates)
//   vedid daemon <edid.hex> [width] [rate]
//                                     stay resident: inject on every connect and switch to the <width>-wide
//                                     mode at <rate> Hz (defaults 1920 / 360). This is what the LaunchAgent runs.
//
// None of the private functions below have public headers; the signatures were
// recovered by disassembling the implementations in the dyld shared cache.
#include <CoreFoundation/CoreFoundation.h>
#include <CoreGraphics/CoreGraphics.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOKitKeys.h>
#include <unistd.h>
#include <time.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include <ctype.h>

typedef CFTypeRef IOAVServiceRef;
typedef CFTypeRef IOAVControllerRef;

extern IOAVServiceRef IOAVServiceCreateWithService(CFAllocatorRef, io_service_t);
extern IOReturn IOAVServiceCopyEDID(IOAVServiceRef, CFDataRef *);
extern IOReturn IOAVServiceReadI2C(IOAVServiceRef, uint32_t chip, uint32_t off, void *buf, uint32_t len);   // selector 24
extern IOReturn IOAVServiceWriteI2C(IOAVServiceRef, uint32_t chip, uint32_t off, void *buf, uint32_t len);  // selector 25
extern IOReturn IOAVServiceSetVirtualEDIDMode(IOAVServiceRef, uint32_t mode, CFDataRef edid);             // selector 23
extern CFDictionaryRef IOAVServiceCopyProperties(IOAVServiceRef);
extern IOAVControllerRef IOAVControllerCreateWithService(CFAllocatorRef, io_service_t);
extern IOReturn IOAVControllerForceHotPlugDetect(IOAVControllerRef);

typedef CFTypeRef IODPDeviceRef;
extern IODPDeviceRef IODPDeviceCreateWithService(CFAllocatorRef, io_service_t);
extern IOReturn IODPDeviceSetUpdated(IODPDeviceRef, uint32_t);                                             // selector 5
extern IOReturn IODPDeviceSetUpdateMode(IODPDeviceRef, uint32_t);

typedef CFTypeRef IODPPortRef;
extern IODPPortRef IODPPortCreateWithService(CFAllocatorRef, io_service_t);
// Both take out-parameters; GetAddress takes three (calling it with one segfaults).
extern IOReturn IODPPortGetAddress(IODPPortRef, uint32_t *, uint32_t *, uint32_t *);
extern IOReturn IODPPortGetVirtual(IODPPortRef, uint32_t *);
extern IOReturn IODPPortSetVirtual(IODPPortRef, uint32_t);                                                 // selector 0
extern IOReturn IODPPortSetVirtualEDID(IODPPortRef, CFDataRef);                                            // selector 4
extern IOReturn IODPPortSetPortEvent(IODPPortRef, uint32_t);

// Call cb for every IODPPortService.
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

// Look up an IORegistry service by class name and (optionally) its Location property.
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

// Read an EDID from a hex text file (whitespace and line breaks are ignored).
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
    printf("  read %zu bytes from %s\n", m, path);
    return CFDataCreate(kCFAllocatorDefault, bin, m);
}


// ================= resident agent =================
// Re-injects the virtual EDID whenever a display connects and switches to the
// target mode. The virtual EDID is volatile (reboot, replug and sleep all clear
// it), so something has to stay resident.

static CFDataRef g_edid;                 // EDID to inject
static uint8_t   g_target_id[4];         // manufacturer/product ID (EDID bytes 8..11) of the monitor the EDID is for
static size_t    g_width = 1920;         // target mode: horizontal pixels ...
static double    g_rate  = 360.0;        // ... and refresh rate in Hz, matched within +-1.5 Hz

static void logf_ts(const char *fmt, ...) {
    time_t t = time(NULL); struct tm tm; localtime_r(&t, &tm);
    char b[32]; strftime(b, sizeof b, "%Y-%m-%d %H:%M:%S", &tm);
    printf("[%s] ", b);
    va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap);
    fflush(stdout);
}

static int is_target_mode(CGDisplayModeRef m) {
    return CGDisplayModeGetWidth(m) == g_width
        && fabs(CGDisplayModeGetRefreshRate(m) - g_rate) < 1.5
        && CGDisplayModeIsUsableForDesktopGUI(m);
}

// The first external display. *out_mode gets the target mode (retained) or NULL
// if it does not exist yet; *out_cur gets the display's current mode.
static CGDirectDisplayID find_target(CGDisplayModeRef *out_mode, CGDisplayModeRef *out_cur) {
    CGDirectDisplayID ids[16]; uint32_t n = 0;
    if (CGGetOnlineDisplayList(16, ids, &n) != kCGErrorSuccess) return 0;
    for (uint32_t i = 0; i < n; i++) {
        if (CGDisplayIsBuiltin(ids[i])) continue;
        CFArrayRef ms = CGDisplayCopyAllDisplayModes(ids[i], NULL);
        if (!ms) continue;
        CGDisplayModeRef best = NULL;
        for (CFIndex k = 0; k < CFArrayGetCount(ms); k++) {
            CGDisplayModeRef m = (CGDisplayModeRef)CFArrayGetValueAtIndex(ms, k);
            if (is_target_mode(m)) best = m;
        }
        *out_mode = best ? CGDisplayModeRetain(best) : NULL;
        CFRelease(ms);
        if (out_cur) *out_cur = CGDisplayCopyDisplayMode(ids[i]);
        return ids[i];
    }
    return 0;
}

// Only touch the monitor the EDID was made for (manufacturer/product ID match).
static int is_target_monitor(IOAVServiceRef av) {
    CFDataRef e = NULL;
    if (IOAVServiceCopyEDID(av, &e) != 0 || !e) return 0;
    int ok = CFDataGetLength(e) >= 16 && memcmp(CFDataGetBytePtr(e) + 8, g_target_id, 4) == 0;
    CFRelease(e);
    return ok;
}

// allow_switch=1: right after a connect or at startup. Switch to the target mode and log the steps.
// allow_switch=0: periodic check. Only acts if the mode vanished and needs re-injecting; stays
//                 quiet otherwise, so a rate the user picked on purpose is left alone.
static void apply_once(int allow_switch) {
    const int verbose = allow_switch;
    io_service_t avs = find_service("DCPAVServiceProxy", "External");
    if (!avs) { if (verbose) logf_ts("no external display, nothing to do\n"); return; }
    IOAVServiceRef av = IOAVServiceCreateWithService(kCFAllocatorDefault, avs);
    IOObjectRelease(avs);
    if (!av) { logf_ts("IOAVServiceCreateWithService failed\n"); return; }
    if (!is_target_monitor(av)) {
        if (verbose) logf_ts("not the monitor this EDID is for (manufacturer/product ID mismatch), nothing to do\n");
        CFRelease(av); return;
    }

    CGDisplayModeRef want = NULL, cur = NULL;
    CGDirectDisplayID did = find_target(&want, &cur);

    int injected = 0;
    if (!want) {                                   // target mode not there yet -> inject
        injected = 1;
        IOReturn r = IOAVServiceSetVirtualEDIDMode(av, 1, g_edid);
        logf_ts("virtual EDID injected rc=0x%08x\n", r);
        io_service_t ds = find_service("DCPDPDeviceProxy", "External");
        if (ds) {
            IODPDeviceRef d = IODPDeviceCreateWithService(kCFAllocatorDefault, ds);
            IOObjectRelease(ds);
            if (d) {
                r = IODPDeviceSetUpdated(d, 1);
                logf_ts("timing table rebuild rc=0x%08x\n", r);
                CFRelease(d);
            }
        }
        for (int i = 0; i < 40 && !want; i++) {     // give it up to 4 s to show up
            usleep(100000);
            if (cur) { CGDisplayModeRelease(cur); cur = NULL; }
            did = find_target(&want, &cur);
        }
    }
    CFRelease(av);

    if (!want) { logf_ts("the %.0f Hz mode did not appear\n", g_rate); if (cur) CGDisplayModeRelease(cur); return; }

    double now = cur ? CGDisplayModeGetRefreshRate(cur) : 0;
    if (fabs(now - g_rate) < 1.5) {
        if (verbose) logf_ts("already at %.3f Hz, nothing to do\n", now);
    } else if (!injected && !allow_switch) {
        /* The mode is available and the user picked something else. Leave it alone. */
    } else {
        CGDisplayConfigRef cfg;
        if (CGBeginDisplayConfiguration(&cfg) == kCGErrorSuccess) {
            CGConfigureDisplayWithDisplayMode(cfg, did, want, NULL);
            CGError e = CGCompleteDisplayConfiguration(cfg, kCGConfigurePermanently);
            logf_ts("switched to %.0f Hz (%.3f -> %.0f) rc=%d\n", g_rate, now, g_rate, e);
        }
    }
    CGDisplayModeRelease(want);
    if (cur) CGDisplayModeRelease(cur);
}

// IOKit matching notification: fires when a display connects.
static void on_match(void *ref, io_iterator_t it) {
    io_service_t s; int n = 0;
    while ((s = IOIteratorNext(it))) { IOObjectRelease(s); n++; }
    if (n == 0) return;
    logf_ts("display connected (%d), applying\n", n);
    usleep(1200000);                               // let the enumeration settle
    apply_once(1);
}

static int run_daemon(const char *edidpath) {
    g_edid = load_hex(edidpath);
    if (!g_edid) return 1;
    if (CFDataGetLength(g_edid) < 128) { fprintf(stderr, "EDID is shorter than 128 bytes\n"); return 1; }
    memcpy(g_target_id, CFDataGetBytePtr(g_edid) + 8, 4);
    logf_ts("resident: EDID %ld bytes, monitor %02x%02x/%02x%02x, target %zu-wide at %.0f Hz\n",
            (long)CFDataGetLength(g_edid), g_target_id[0], g_target_id[1], g_target_id[2], g_target_id[3],
            g_width, g_rate);
    apply_once(1);

    IONotificationPortRef np = IONotificationPortCreate(kIOMainPortDefault);
    CFRunLoopAddSource(CFRunLoopGetCurrent(), IONotificationPortGetRunLoopSource(np),
                       kCFRunLoopDefaultMode);
    io_iterator_t it = 0;
    IOServiceAddMatchingNotification(np, kIOMatchedNotification,
                                     IOServiceMatching("DCPAVServiceProxy"),
                                     on_match, NULL, &it);
    io_service_t s;                                 // drain the existing entries to arm the notification
    while ((s = IOIteratorNext(it))) IOObjectRelease(s);

    // Safety net for paths that send no notification (sleep/wake): check every
    // 30 s, re-inject only if the mode vanished, never switch on our own.
    CFRunLoopTimerRef t = CFRunLoopTimerCreateWithHandler(
        kCFAllocatorDefault, CFAbsoluteTimeGetCurrent() + 30, 30,
        0, 0, ^(CFRunLoopTimerRef _t) { apply_once(0); });
    CFRunLoopAddTimer(CFRunLoopGetCurrent(), t, kCFRunLoopDefaultMode);

    CFRunLoopRun();
    return 0;
}

int main(int argc, char **argv) {
    const char *cmd = argc > 1 ? argv[1] : "info";

    if (!strcmp(cmd, "daemon")) {
        if (argc < 3) { fprintf(stderr, "usage: vedid daemon <edid.hex> [width] [rate]\n"); return 1; }
        if (argc > 3) g_width = (size_t)strtoul(argv[3], NULL, 10);
        if (argc > 4) g_rate = strtod(argv[4], NULL);
        if (g_width == 0 || g_rate <= 0) { fprintf(stderr, "bad width/rate\n"); return 1; }
        return run_daemon(argv[2]);
    }

    if (!strcmp(cmd, "devupd")) {          // tell the DP device it was updated so the DCP re-parses
        uint32_t v = argc > 2 ? (uint32_t)atoi(argv[2]) : 1;
        io_service_t ds = find_service("DCPDPDeviceProxy", "External");
        if (!ds) { printf("no DCPDPDeviceProxy(External)\n"); return 1; }
        IODPDeviceRef d = IODPDeviceCreateWithService(kCFAllocatorDefault, ds);
        printf("IODPDeviceRef = %p\n", d);
        if (!d) return 1;
        IOReturn r = IODPDeviceSetUpdated(d, v);
        printf("IODPDeviceSetUpdated(%u) rc=0x%08x %s\n", v, r, r == 0 ? "OK" : "");
        return 0;
    }
    if (!strcmp(cmd, "ports")) {                       // read-only
        printf("IODPPortService objects:\n");
        printf("  %d ports\n", each_port(cb_info, NULL));
        return 0;
    }
    if (!strcmp(cmd, "pset")) {                        // virtual EDID on every DP port
        if (argc < 3) { printf("usage: vedid pset <edid.hex>\n"); return 1; }
        CFDataRef d = load_hex(argv[2]);
        if (!d) return 1;
        printf("set on %d ports\n", each_port(cb_setedid, (void *)d));
        return 0;
    }

    // hpd must work while the display is disconnected, so it does not go through the AV service
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
        printf("sent hot-plug detect to %d external controllers\n", n);
        return 0;
    }

    const int quiet = !strcmp(cmd, "edid");            // keep stdout clean for `vedid edid > file`
    io_service_t avsvc = find_service("DCPAVServiceProxy", "External");
    if (!avsvc) { fprintf(stderr, "no DCPAVServiceProxy(External): is an external display connected?\n"); return 1; }
    if (!quiet) printf("DCPAVServiceProxy(External) found\n");

    IOAVServiceRef av = IOAVServiceCreateWithService(kCFAllocatorDefault, avsvc);
    if (!av) { fprintf(stderr, "IOAVServiceCreateWithService failed\n"); return 1; }
    if (!quiet) printf("IOAVServiceRef = %p\n\n", av);

    if (!strcmp(cmd, "edid")) {
        CFDataRef edid = NULL;
        if (IOAVServiceCopyEDID(av, &edid) != 0 || !edid) { fprintf(stderr, "IOAVServiceCopyEDID failed\n"); return 1; }
        const uint8_t *b = CFDataGetBytePtr(edid);
        for (CFIndex i = 0; i < CFDataGetLength(edid); i++) printf("%02x", b[i]);
        printf("\n");
        CFRelease(edid);
        return 0;
    }
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
        if (argc < 3) { printf("usage: vedid set <edid.hex>\n"); return 1; }
        CFDataRef d = load_hex(argv[2]);
        if (!d) return 1;
        IOReturn r = IOAVServiceSetVirtualEDIDMode(av, 1, d);
        printf("IOAVServiceSetVirtualEDIDMode(mode=1, %ld bytes) rc=0x%08x %s\n",
               (long)CFDataGetLength(d), r, r == 0 ? "OK" : "");
        return r != 0;
    }
    if (!strcmp(cmd, "clear")) {
        IOReturn r = IOAVServiceSetVirtualEDIDMode(av, 0, NULL);
        printf("IOAVServiceSetVirtualEDIDMode(mode=0) rc=0x%08x %s\n", r, r == 0 ? "OK" : "");
        return r != 0;
    }
    fprintf(stderr, "unknown command: %s\n", cmd);
    return 1;
}
