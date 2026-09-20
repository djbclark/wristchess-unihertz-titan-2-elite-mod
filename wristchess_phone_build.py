#!/usr/bin/env python3
"""Download Wrist Chess (net.kusik.wristchess) from Google Play and rebuild it
so it installs on ordinary Android phones instead of only Wear OS watches.

Usage: run with no arguments. It prompts for a Google account email and a
token, which can be either:
  * an OAuth code from https://accounts.google.com/EmbeddedSetup (DevTools >
    Application > Cookies > accounts.google.com > oauth_token; starts with
    "oauth2_4/"; single-use, expires within minutes), or
  * an already-exchanged long-lived AAS token (starts with "aas_et/").

What it does:
  1. exchanges the OAuth code for an AAS token with apkeep (and prints it so
     you can reuse it next time instead of logging in again)
  2. downloads the app's base + split APKs from Play while spoofing a real
     Wear OS device (Ticwatch E), because Play only serves it to watches
  3. decodes the base APK with apktool, makes the Wear shared library and the
     watch hardware feature optional, removes the split-APK requirement,
     merges the native libraries from the ABI split, and rebuilds
  4. zipaligns and signs the result with a throwaway key

Requirements on PATH / disk: apkeep, apktool, java, keytool, and Android
build-tools (zipalign + apksigner) under $ANDROID_HOME, $ANDROID_SDK_ROOT, or
~/Library/Android/sdk.

Output: ./out/wristchess-phone.apk (relative to the current directory).
Note: the app ships only 32-bit (armeabi-v7a) native code. If a directory
prebuilt-libs/arm64-v8a/ exists next to this script (arm64 builds of the same
libraries, produced by arm64/build.sh + arm64/fetch-aar-libs.sh), its *.so are
merged in too, so the result also installs on 64-bit-only devices (Pixel 7+,
recent Galaxy S, Unihertz Titan 2 Elite); without it those devices refuse the
APK with INSTALL_FAILED_NO_MATCHING_ABIS.
"""
import getpass
import glob
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP_ID = "net.kusik.wristchess"
DEVICE = "twa"
OUT_DIR = Path("out")
WORK = OUT_DIR / "work"
HERE = Path(__file__).resolve().parent

# Phone shims (see phone-shims/README in each file's header comment):
#  - phone-shims/smali/: stub classes from the Wear OS shared library that the
#    app touches on phones (com.google.wear.Sdk$VERSION, the
#    androidx.wear.ambient controller classes). Copied into a new dex so no
#    existing smali is edited.
#  - phone-shims/java/: RemoteInputActivity, a phone handler for the wearable
#    REMOTE_INPUT intent the app uses to ask for the Lichess token. Compiled with
#    javac + d8 when both are available; skipped (with a warning) otherwise.
SHIM_SMALI_DIR = HERE / "phone-shims" / "smali"
SHIM_JAVA_DIR = HERE / "phone-shims" / "java"
SHIM_MANIFEST_ACTIVITY = """\
        <activity android:excludeFromRecents="true" android:exported="true" android:label="@string/app_name" \
android:name="net.kusik.wristchess.phoneshim.RemoteInputActivity" \
android:theme="@android:style/Theme.DeviceDefault.Dialog.NoActionBar.MinWidth" \
android:windowSoftInputMode="stateVisible|adjustResize">
            <intent-filter>
                <action android:name="android.support.wearable.input.action.REMOTE_INPUT"/>
                <category android:name="android.intent.category.DEFAULT"/>
            </intent-filter>
        </activity>
"""

# Ticwatch E profile from Aurora OSS GPlayApi (GPL-3.0), plus a Features line
# borrowed from a Pixel profile with android.hardware.type.watch prepended.
# Colons are escaped because the Rust configparser used by apkeep treats a
# bare ":" as a key/value delimiter.
DEVICE_PROPERTIES = r"""[twa]
UserReadableName=Ticwatch E
Build.HARDWARE=mooneye
Build.RADIO=976_GEN_PACK-1.103654.1.105572.1,976_GEN_PACK-1.103654.1.105572.1
Build.BOOTLOADER=mooneye0.5.30.0.0.5
Build.FINGERPRINT=mobvoi/mooneye/mooneye\:8.0.0/OWDR.180307.020/5000261\:user/release-keys
Build.BRAND=mobvoi
Build.DEVICE=mooneye
Build.VERSION.SDK_INT=26
Build.MODEL=Ticwatch E
Build.MANUFACTURER=Mobvoi
Build.PRODUCT=mooneye
Build.ID=OWDR.180307.020
Build.VERSION.RELEASE=8.0.0
TouchScreen=3
Keyboard=1
Navigation=1
ScreenLayout=1
HasHardKeyboard=false
HasFiveWayNavigation=false
GL.Version=131072
Screen.Density=280
Screen.Width=400
Screen.Height=400
Platforms=armeabi-v7a,armeabi
SharedLibraries=com.google.android.wearable,clockwork-system,android.ext.services,android.ext.shared,android.test.runner,com.android.future.usb.accessory,com.android.location.provider,com.google.android.gms,com.google.android.wearable,javax.obex,org.apache.http.legacy Features = android.hardware.audio.output,android.hardware.bluetooth,android.hardware.bluetooth_le,android.hardware.faketouch,android.hardware.location,android.hardware.location.gps,android.hardware.microphone,android.hardware.screen.portrait,android.hardware.sensor.accelerometer,android.hardware.sensor.compass,android.hardware.sensor.gyroscope,android.hardware.sensor.heartrate,android.hardware.sensor.stepcounter,android.hardware.sensor.stepdetector,android.hardware.touchscreen,android.hardware.touchscreen.multitouch,android.hardware.type.watch,android.hardware.usb.accessory,android.hardware.wifi,android.software.activities_on_secondary_displays,android.software.connectionservice,android.software.cts,android.software.device_admin,android.software.home_screen,android.software.input_methods,android.software.live_wallpaper,android.software.voice_recognizers,com.google.wearable.hardware.sensor.heartrate.fitness,oem.tw.hardware.ticwatch
Locales=ar,ar_SA,ast,be,be_BY,bg,bg_BG,bh_IN,ca,ca_ES,cs,cy_GB,da,da_DK,de,de_DE,el,el_GR,en,en_GB,en_US,en_XA,es,es_ES,es_US,et,et_EE,fi,fi_FI,fr,fr_CA,fr_FR,gl,gl_ES,hi,hi_IN,hr,hr_HR,hu,hu_HU,in,in_ID,it,it_IT,iw,iw_IL,ja,ja_JP,kab_DZ,ko,ko_KR,lt,lt_LT,nb,nb_NO,nl,nl_BE,nl_NL,pa,pa_IN,pl,pl_PL,pt,pt_BR,pt_PT,ro,ro_RO,ru,ru_RU,sc_IT,sk,sk_SK,sr,sv,sv_SE,th,th_TH,tr,tr_TR,uk,uk_UA,vi,vi_VN,zh_CN,zh_HK,zh_TW
GSF.version=201516070
Vending.version=81932605
Vending.versionString=19.3.26-all [5] [PR] 301645536
CellOperator=26203
SimOperator=26207
TimeZone=Europe/Berlin
GL.Extensions=GL_ARM_mali_program_binary,GL_ARM_mali_shader_binary,GL_ARM_rgba8,GL_EXT_blend_minmax,GL_EXT_debug_marker,GL_EXT_discard_framebuffer,GL_EXT_multisampled_render_to_texture,GL_EXT_robustness,GL_EXT_shader_texture_lod,GL_EXT_texture_format_BGRA8888,GL_KHR_debug,GL_OES_EGL_image,GL_OES_EGL_image_external,GL_OES_EGL_sync,GL_OES_byte_coordinates,GL_OES_compressed_ETC1_RGB8_texture,GL_OES_compressed_paletted_texture,GL_OES_depth24,GL_OES_depth_texture,GL_OES_depth_texture_cube_map,GL_OES_draw_texture,GL_OES_extended_matrix_palette,GL_OES_fixed_point,GL_OES_framebuffer_object,GL_OES_get_program_binary,GL_OES_matrix_get,GL_OES_matrix_palette,GL_OES_packed_depth_stencil,GL_OES_point_size_array,GL_OES_point_sprite,GL_OES_query_matrix,GL_OES_read_format,GL_OES_rgb8_rgba8,GL_OES_single_precision,GL_OES_standard_derivatives,GL_OES_stencil8,GL_OES_texture_cube_map,GL_OES_texture_npot,GL_OES_vertex_half_float
Roaming=mobile-notroaming
Client=android-google
Features=android.hardware.type.watch,android.hardware.sensor.proximity,com.google.android.feature.CONTEXTUAL_SEARCH,com.verizon.hardware.telephony.lte,com.google.android.feature.PIXEL_2024_EXPERIENCE,com.verizon.hardware.telephony.ehrpd,android.hardware.sensor.accelerometer,android.software.controls,android.hardware.faketouch,android.software.telecom,com.google.android.feature.D2D_CABLE_MIGRATION_FEATURE,android.hardware.usb.accessory,android.hardware.sensor.dynamic.head_tracker,android.software.backup,android.hardware.touchscreen,android.hardware.touchscreen.multitouch,android.software.erofs,android.software.print,android.software.activities_on_secondary_displays,android.hardware.wifi.rtt,com.android.systemui.SUPPORTS_DRAG_ASSISTANT_TO_SPLIT,android.software.device_lock,com.google.android.feature.PIXEL_2017_EXPERIENCE,com.google.android.feature.PIXEL_2024_MIDYEAR_EXPERIENCE,android.software.voice_recognizers,android.software.picture_in_picture,android.hardware.fingerprint,android.hardware.sensor.gyroscope,android.hardware.audio.low_latency,android.software.vulkan.deqp.level,android.software.cant_save_state,com.google.android.feature.PIXEL_2018_EXPERIENCE,android.hardware.security.model.compatible,com.google.android.feature.PIXEL_2019_EXPERIENCE,android.hardware.opengles.aep,android.hardware.bluetooth,com.google.android.feature.PIXEL_2023_MIDYEAR_EXPERIENCE,android.software.window_magnification,android.hardware.camera.autofocus,com.google.android.feature.GOOGLE_BUILD,android.software.incremental_delivery,android.hardware.se.omapi.ese,android.software.opengles.deqp.level,vendor.android.hardware.camera.preview-dis.front,com.google.android.feature.PIXEL_2022_MIDYEAR_EXPERIENCE,android.hardware.camera.concurrent,android.hardware.usb.host,android.hardware.audio.output,android.software.ipsec_tunnel_migration,android.software.verified_boot,android.hardware.camera.flash,android.hardware.camera.front,android.hardware.sensor.hifi_sensors,android.hardware.se.omapi.uicc,android.hardware.strongbox_keystore,android.hardware.screen.portrait,android.hardware.nfc,com.google.android.feature.TURBO_PRELOAD,com.nxp.mifare,com.google.android.feature.PIXEL_2021_MIDYEAR_EXPERIENCE,android.hardware.sensor.stepdetector,android.software.home_screen,android.hardware.context_hub,vendor.android.hardware.camera.preview-dis.back,android.hardware.microphone,android.software.autofill,android.software.securely_removes_users,com.google.android.feature.PIXEL_EXPERIENCE,android.hardware.bluetooth_le,android.hardware.sensor.compass,com.google.android.feature.GOOGLE_FI_BUNDLED,android.hardware.touchscreen.multitouch.jazzhand,android.hardware.sensor.barometer,android.software.app_widgets,com.google.android.feature.PIXEL_2020_MIDYEAR_EXPERIENCE,android.software.sdksandbox.sdk_install_work_profile,android.software.input_methods,android.hardware.sensor.light,android.hardware.vulkan.version,android.software.companion_device_setup,android.software.device_admin,com.google.android.feature.WELLBEING,android.hardware.wifi.passpoint,android.hardware.camera,android.software.credentials,android.hardware.device_unique_attestation,android.hardware.screen.landscape,android.software.device_id_attestation,com.google.android.feature.AER_OPTIMIZED,android.hardware.ram.normal,com.google.android.feature.NEXT_GENERATION_ASSISTANT,com.google.android.feature.PIXEL_2019_MIDYEAR_EXPERIENCE,android.software.managed_users,android.software.webview,android.hardware.sensor.stepcounter,android.hardware.camera.capability.manual_post_processing,android.hardware.camera.any,android.hardware.camera.capability.raw,android.hardware.vulkan.compute,android.hardware.touchscreen.multitouch.distinct,android.hardware.location.network,android.software.cts,android.hardware.camera.capability.manual_sensor,android.software.app_enumeration,com.google.android.apps.dialer.SUPPORTED,android.hardware.camera.level.full,com.google.android.feature.GMS_GAME_SERVICE,android.software.game_service,android.hardware.wifi.direct,android.software.live_wallpaper,com.google.android.feature.GOOGLE_EXPERIENCE,android.software.ipsec_tunnels,com.google.android.feature.EXCHANGE_6_2,com.google.android.feature.DREAMLINER,android.hardware.audio.pro,android.hardware.nfc.hcef,android.hardware.location.gps,com.google.android.feature.ADAPTIVE_CHARGING,android.software.midi,android.hardware.nfc.any,android.hardware.nfc.ese,android.hardware.nfc.hce,android.hardware.hardware_keystore,com.google.android.feature.PIXEL_2020_EXPERIENCE,android.hardware.wifi,android.hardware.location,android.hardware.vulkan.level,android.software.virtualization_framework,com.google.android.feature.PIXEL_2021_EXPERIENCE,android.hardware.keystore.app_attest_key,com.google.android.feature.QUICK_TAP,android.software.wallet_location_based_suggestions,android.hardware.wifi.aware,com.google.android.feature.PIXEL_2022_EXPERIENCE,android.software.secure_lock_screen,android.hardware.biometrics.face,com.google.android.feature.PIXEL_2023_EXPERIENCE,android.software.file_based_encryption
"""


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def need(tool):
    path = shutil.which(tool)
    if not path:
        die(f"{tool} not found on PATH")
    return path


def build_tools_dir():
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
             str(Path.home() / "Library/Android/sdk"), str(Path.home() / "Android/Sdk")]
    for root in filter(None, roots):
        cands = sorted(glob.glob(os.path.join(root, "build-tools", "*")), reverse=True)
        for c in cands:
            if os.path.isfile(os.path.join(c, "zipalign")) and os.path.isfile(os.path.join(c, "apksigner")):
                return Path(c)
    die("Android build-tools with zipalign + apksigner not found; set ANDROID_HOME")


def apkeep_tty(args):
    """apkeep only prints per-app errors when stdout is a TTY, so run it under
    script(1) and return the captured text."""
    cmd = ["script", "-q", "/dev/null"] + args
    print("+", " ".join(args[:6]), "...", flush=True)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    text = p.stdout.replace("\r", "\n")
    for line in text.splitlines():
        if line.strip() and "aas_et/" not in line and not line.startswith("\x1b"):
            print("  " + re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip())
    return text


def get_aas_token(email, token):
    if token.startswith("aas_et/"):
        return token
    if not token.startswith("oauth2_4/"):
        die("token must start with oauth2_4/ or aas_et/")
    p = subprocess.run(["apkeep", "-e", email, "--oauth-token", token],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    m = re.search(r"aas_et/[A-Za-z0-9_=-]+", p.stdout)
    if not m:
        die("could not exchange the OAuth code for an AAS token (codes are "
            "single-use and expire quickly; fetch a fresh one).\n" + p.stdout.strip())
    print("\nAAS token (long-lived; paste this next time instead of logging in):")
    print("  " + m.group(0) + "\n")
    return m.group(0)


def download(email, aas):
    props = WORK / "device.properties"
    props.write_text(DEVICE_PROPERTIES)
    dl = WORK / "download"
    dl.mkdir(parents=True, exist_ok=True)
    text = apkeep_tty(["apkeep", "-a", APP_ID, "-d", "google-play", "-r", "1",
                       "-o", f"device={DEVICE},device_properties_file={props.resolve()},split_apk=1",
                       "-e", email, "-t", aas, "--accept-tos", str(dl)])
    if "Could not log in" in text:
        die("Google Play login failed. If this account has never used Play, "
            "open https://play.google.com/store signed in as it once, then retry.")
    base = dl / APP_ID / f"{APP_ID}.apk"
    if not base.is_file():
        die("download failed (see apkeep output above)")
    splits = sorted((dl / APP_ID).glob(f"{APP_ID}.config.arm*.apk"))
    return base, splits


def patch_manifest(manifest: Path):
    xml = manifest.read_text()
    subs = [
        (r'<uses-feature android:name="android.hardware.type.watch"/>',
         '<uses-feature android:name="android.hardware.type.watch" android:required="false"/>'),
        (r'(<uses-library android:name="com.google.android.wearable" android:required=)"true"', r'\1"false"'),
        (r' android:requiredSplitTypes="[^"]*"', ""),
        (r' android:splitTypes="[^"]*"', ""),
        (r' android:isSplitRequired="true"', ""),
        (r'(<meta-data android:name="com.android.vending.splits.required" android:value=)"true"', r'\1"false"'),
        (r'\s*<meta-data android:name="com.android.vending.splits" android:resource="[^"]*"/>', ""),
        (r'android:extractNativeLibs="false"', 'android:extractNativeLibs="true"'),
    ]
    for pat, rep in subs:
        xml, n = re.subn(pat, rep, xml)
        print(f"  manifest: {n} x {pat[:60]}")
    if 'extractNativeLibs' not in xml:
        xml = xml.replace("<application ", '<application android:extractNativeLibs="true" ', 1)
    if "phoneshim.RemoteInputActivity" not in xml:
        xml, n = re.subn(r"(\n\s*</application>)", "\n" + SHIM_MANIFEST_ACTIVITY.rstrip("\n") + r"\1", xml, count=1)
        print(f"  manifest: {n} x RemoteInputActivity")
    manifest.write_text(xml)



def patch_styles_dialog_wide(decoded: Path):
    styles = decoded / "res" / "values" / "styles.xml"
    if not styles.exists(): return
    xml = styles.read_text()
    
    if 'name="Theme.App.WideDialog"' not in xml:
        custom_style = """
    <style name="Theme.App.WideDialog" parent="@android:style/Theme.DeviceDefault.Dialog.NoActionBar.MinWidth">
        <item name="android:windowMinWidthMajor">100%</item>
        <item name="android:windowMinWidthMinor">100%</item>
        <item name="android:windowIsFloating">true</item>
        <item name="android:windowBackground">@android:color/transparent</item>
    </style>
"""
        xml = xml.replace("</resources>", custom_style + "</resources>")
    
    xml = re.sub(
        r'<style name="Theme\.App" parent=".*?"',
        r'<style name="Theme.App" parent="@style/Theme.App.WideDialog"',
        xml
    )
    styles.write_text(xml)
    print("  patched styles.xml: Theme.App -> Theme.App.WideDialog")

def patch_styles(styles: Path):
    """Theme.App (applied after the splash screen) is plain Theme.DeviceDefault. On a
    watch that is already full-screen and title-less; on a phone it adds an action bar
    with the app title plus a status bar, which pushed the board's top rank under the
    title bar. Use the phone's no-action-bar fullscreen variant so the Compose UI gets
    the whole square it was designed for."""
    xml = styles.read_text()
    xml, n = re.subn(r'(<style name="Theme\.App" parent=")@android:style/Theme\.DeviceDefault(")',
                     r"\1@android:style/Theme.DeviceDefault.NoActionBar.Fullscreen\2", xml)
    print(f"  styles: {n} x Theme.App -> NoActionBar.Fullscreen")
    styles.write_text(xml)



def patch_board(decoded):
    xd0 = decoded / "smali" / "xd0.smali"
    if not xd0.is_file(): return
    xml = xd0.read_text()
    import re
    match = re.search(r"\.method public static final a\(Landroid/content/res/Configuration;\)I.*?\.end method", xml, re.DOTALL)
    if match:
        new_method = """.method public static final a(Landroid/content/res/Configuration;)I
    .locals 0
    invoke-virtual {p0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;
    iget p0, p0, Landroid/content/res/Configuration;->smallestScreenWidthDp:I
    add-int/lit8 p0, p0, -0x64
    return p0
.end method"""
        xml = xml[:match.start()] + new_method + xml[match.end():]
        xd0.write_text(xml)
        print("  patched xd0.smali: board size fits width minus 100dp")

def patch_puzzles(decoded):
    fz3 = decoded / "smali_classes2" / "fz3.smali"
    if not fz3.is_file(): return
    xml = fz3.read_text()
    import re
    style_smali = """sget-object v3, Lad5;->b:Lsv4;
    invoke-virtual {v2, v3}, Lrn1;->m(Ljy3;)Ljava/lang/Object;
    move-result-object v3
    check-cast v3, Lxc5;
    iget-object v3, v3, Lxc5;->o:Lm65;
    move-object/from16 v27, v3"""
    xml, n = re.subn(r"const/16 v27, 0x0", style_smali, xml)
    print(f"  patched fz3.smali: {n} x LocalTypography")
    xml, n1 = re.subn(r"const v31, 0x1fffe", "const v31, 0xfffe", xml)
    xml, n2 = re.subn(r"const v31, 0x1fffa", "const v31, 0xfffa", xml)
    xml, n3 = re.subn(r"const v31, 0x1aefc", "const v31, 0xaefc", xml)
    print(f"  patched fz3.smali: {n1+n2+n3} x default style bits")
    fz3.write_text(xml)

def build_shims(decoded: Path, bt: Path):
    """Add the phone shim classes as extra dex files (nothing existing is edited)."""
    existing = sorted(int(m.group(1) or 1) for p in decoded.iterdir()
                      if (m := re.match(r"smali(?:_classes(\d+))?$", p.name)))
    next_index = max(existing) + 1
    # 1. smali stubs -> smali_classesN (apktool assembles it into classesN.dex)
    if SHIM_SMALI_DIR.is_dir():
        shutil.copytree(SHIM_SMALI_DIR, decoded / f"smali_classes{next_index}")
        print(f"  shims: smali stubs -> classes{next_index}.dex")
        next_index += 1
    # 2. Java shim -> classesN.dex via javac + d8 (apktool copies raw classes*.dex as-is)
    sources = sorted(SHIM_JAVA_DIR.rglob("*.java")) if SHIM_JAVA_DIR.is_dir() else []
    if not sources:
        return
    javac = shutil.which("javac")
    d8 = bt / "d8"
    android_jars = sorted(glob.glob(str(bt.parent.parent / "platforms" / "android-*" / "android.jar")))
    if not javac or not d8.is_file() or not android_jars:
        print("  WARNING: javac/d8/android.jar missing; RemoteInputActivity shim skipped "
              "(Lichess sign-in will crash on phones)")
        return
    classes = WORK / "shim-classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True)
    run([javac, "--release", "11", "-Xlint:-options", "-cp", android_jars[-1], "-d", str(classes)]
        + [str(s) for s in sources], stderr=subprocess.DEVNULL)
    dex_out = WORK / "shim-dex"
    if dex_out.exists():
        shutil.rmtree(dex_out)
    dex_out.mkdir(parents=True)
    run([str(d8), "--release", "--min-api", "26", "--lib", android_jars[-1], "--output", str(dex_out)]
        + [str(c) for c in classes.rglob("*.class")])
    shutil.copy2(dex_out / "classes.dex", decoded / f"classes{next_index}.dex")
    print(f"  shims: {len(sources)} Java file(s) -> classes{next_index}.dex")


def rebuild(base: Path, splits, bt: Path):
    decoded = WORK / "decoded"
    if decoded.exists():
        shutil.rmtree(decoded)
    run(["apktool", "d", "-q", "-f", "-o", str(decoded), str(base)])
    patch_manifest(decoded / "AndroidManifest.xml")
    patch_styles_dialog_wide(decoded)
    patch_board(decoded)
    patch_puzzles(decoded)
    yml = decoded / "apktool.yml"
    yml.write_text(re.sub(r"^\s*(isSplitRequired|requiredSplitTypes):.*\n", "", yml.read_text(), flags=re.M))
    n = 0
    for s in splits:
        with zipfile.ZipFile(s) as z:
            for name in z.namelist():
                if name.startswith("lib/") and name.endswith(".so"):
                    z.extract(name, decoded)
                    n += 1
    print(f"  merged {n} native libraries from {len(splits)} ABI split(s)")
    # Play only ships armeabi-v7a. arm64-v8a builds of the same libraries
    # (see arm64/build.sh and arm64/fetch-aar-libs.sh) live in prebuilt-libs/;
    # merge them so 64-bit-only phones can install the result.
    prebuilt = HERE / "prebuilt-libs" / "arm64-v8a"
    if prebuilt.is_dir():
        dest = decoded / "lib" / "arm64-v8a"
        dest.mkdir(parents=True, exist_ok=True)
        libs = sorted(prebuilt.glob("*.so"))
        for so in libs:
            shutil.copy2(so, dest / so.name)
        print(f"  merged {len(libs)} prebuilt arm64-v8a native libraries")
    build_shims(decoded, bt)
    unsigned = WORK / "unsigned.apk"
    run(["apktool", "b", "-q", "-o", str(unsigned), str(decoded)])
    aligned = WORK / "aligned.apk"
    run([str(bt / "zipalign"), "-p", "-f", "4", str(unsigned), str(aligned)])
    ks = OUT_DIR / "phone-debug.keystore"
    if not ks.is_file():
        run(["keytool", "-genkeypair", "-keystore", str(ks), "-storepass", "wristchess",
             "-keypass", "wristchess", "-alias", "wristchess", "-keyalg", "RSA",
             "-keysize", "2048", "-validity", "10000", "-dname", "CN=Wrist Chess phone build"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    final = OUT_DIR / "wristchess-phone.apk"
    run([str(bt / "apksigner"), "sign", "--ks", str(ks), "--ks-pass", "pass:wristchess",
         "--key-pass", "pass:wristchess", "--ks-key-alias", "wristchess",
         "--out", str(final), str(aligned)], stderr=subprocess.DEVNULL)
    (OUT_DIR / "wristchess-phone.apk.idsig").unlink(missing_ok=True)
    run([str(bt / "apksigner"), "verify", str(final)], stderr=subprocess.DEVNULL)
    return final


def main():
    if len(sys.argv) > 1:
        die("this script takes no arguments")
    for t in ("apkeep", "apktool", "java", "keytool", "script"):
        need(t)
    bt = build_tools_dir()
    email = input("Google account email: ").strip()
    token = getpass.getpass("OAuth code (oauth2_4/...) or AAS token (aas_et/...): ").strip()
    if not email or not token:
        die("email and token are required")
    WORK.mkdir(parents=True, exist_ok=True)
    aas = get_aas_token(email, token)
    base, splits = download(email, aas)
    print(f"downloaded {base.name} + {len(splits)} ABI split(s)")
    final = rebuild(base, splits, bt)
    print(f"\nDone: {final.resolve()}\nInstall with: adb install -r {final}")


if __name__ == "__main__":
    main()
