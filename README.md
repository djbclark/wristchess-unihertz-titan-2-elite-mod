# AGENTS.md — djbclark's working notes for Wrist Chess on phones (local only, git-excluded)

Excluded via `.git/info/exclude`; `CLAUDE.md` symlinks here. Written 2026-09-20
by Claude Code; update in place. This repo has no remote — it holds a
redistributed proprietary app, keep it private.

## What this is

Wrist Chess (`net.kusik.wristchess`, v1.10.1 / versionCode 173, by kusik) is a
**Wear OS-only** Play Store app. Goal: run it on Android phones, specifically the
operator's **Unihertz Titan 2 Elite (t2e)** — `ro.product.cpu.abilist=arm64-v8a`
only, Android 16, adb `TITAN20000040244` (USB) / `100.73.253.10:5555` (Tailscale).
Play ships only **armeabi-v7a** native code, so the phone build needed an arm64
rebuild of the engine.

## Artifacts (repo root)

- `net.kusik.wristchess.apk` — original Play base APK; `splits/…/config.armeabi_v7a.apk`
  etc. — the Play splits (only ABI Play has). `splits64*/` were arm64 attempts (Play
  returned v7a anyway).
- `wristchess-phone.apk` — 32-bit phone build (runs on 32-bit-capable devices,
  e.g. Fire HD8 `100.124.55.39:5555`; t2e rejects it: NO_MATCHING_ABIS).
- **`wristchess-phone-universal.apk`** — both ABIs, 6.9 MB, the one installed on
  t2e (2026-09-20). Signed with `phone-debug.keystore` (alias/storepass/keypass
  `wristchess`, throwaway).
- `wristchess_phone_build.py` — single-file, no-arg script: prompts for Google
  email + `oauth2_4/` code (or `aas_et/` token), downloads via apkeep with the
  embedded Ticwatch E spoof profile, decodes, patches manifest (`patch_manifest`,
  incl. the shim `<activity>`) and `res/values/styles.xml` (`patch_styles`:
  Theme.App → `Theme.DeviceDefault.NoActionBar.Fullscreen`), merges v7a split
  libs + `prebuilt-libs/arm64-v8a/*.so`, `build_shims()` copies
  `phone-shims/smali/` → next `smali_classesN/` and compiles `phone-shims/java/`
  with javac+d8 → next `classesN.dex` (raw dex; apktool copies `classes*.dex`
  found in the decoded root), rebuilds, signs → `out/wristchess-phone-universal.apk`.
- `phone-shims/` — phone-only additions, never edits existing smali:
  `smali/com/google/wear/Sdk$VERSION.smali` (WEAR_SDK_INT=0),
  `smali/com/google/android/wearable/{WearableSharedLib, compat/WearableActivityController,
  compat/WearableActivityController$AmbientCallback}.smali` (no-op ambient stubs;
  method set = what `androidx/wear/ambient/AmbientDelegate.smali` calls;
  `$AmbientCallback` must declare all four callbacks non-abstractly because
  `WearableControllerProvider.a()` reflects on `onEnterAmbient(Bundle)`),
  `java/net/kusik/wristchess/phoneshim/RemoteInputActivity.java` (handler for
  `android.support.wearable.input.action.REMOTE_INPUT`, dialog-themed, exported).
- `prebuilt-libs/arm64-v8a/` — 7 committed arm64 .so files (built here).
- `arm64/` — `build.sh` (Fairy-Stockfish + `jni/stockfish_jni.cpp` shim, NDK
  28.2.13676358 via sdkmanager), `fetch-aar-libs.sh` (other 6 libs from
  Google Maven), `run-device-test.sh` + `test/fake_jni_test.cpp` (on-device
  harness that drives the real lib with the app's command sequence).
  `arm64/Fairy-Stockfish/` and `arm64/out/` are git-ignored build state.
- `decoded/` — apktool 3.0.3 decode (git-ignored, regenerable). Manifest
  patches: `com.google.android.wearable` uses-library required=false; watch
  uses-feature required=false; `requiredSplitTypes`/`splitTypes`/
  `isSplitRequired` removed; `com.android.vending.splits.required=false` and
  the `splits` meta-data removed; `extractNativeLibs=true` (apktool compresses
  .so files, so the uncompressed-libs mode fails with res=-2).
- `twa.properties` (+ tw_e/twb/twc/twd, pixel_watch_3) — apkeep device
  profiles. **Only `twa` (Ticwatch E, SDK 26 + Features line, colons escaped,
  lowercase section name) is served the app.** apkeep's configparser
  lowercases section names and treats bare `:` as a delimiter.

## Getting the APK from Play (if a new version is needed)

- Play only serves Wear apps to watch device profiles; apkeep's built-in list
- Token: EmbeddedSetup login → DevTools cookie `oauth_token` (`oauth2_4/…`,
  single-use, minutes) → `apkeep -e <email> --oauth-token …` prints the
  long-lived `aas_et/` token. Stored in secretspec as **[REDACTED]**
  open play.google.com once signed in — or every catalog call returns empty).
  Aurora's anonymous dispenser is Cloudflare-gated from this Mac and phone.
- apkeep prints per-app errors only on a TTY: wrap with `script -q /dev/null`.
  "Invalid app response" = Play won't serve to that profile/account.

## Engine / JNI facts (from disassembly of the v7a lib)

- Engine is **Fairy-Stockfish** (dev master ~2026-06-16, pinned `1b5bdd40`),
  classical eval, **no NNUE** (`NNUE_EMBEDDING_OFF`), no LARGEBOARDS/ALLVARS.
- Contract: one JNI entry `Java_net_kusik_wristchess_shared_chessengine_UCIChessEngineAndroid_clientToEngine(JNIEnv*, jobject, jstring)`
  (Kotlin appends "\n"); native calls back `engineToClient(String)`
  (`GetMethodID "(Ljava/lang/String;)V"`) **one line per call, no newline,
  from the engine thread** (attach-per-thread, global ref to the object).
  `JNI_OnLoad` swaps cin/cout rdbufs for a queue/sink; engine thread starts
  lazily on first command; `Threads` = `hardware_concurrency()` (8 on t2e).
  App sends: `isready`, `setoption name UCI_LimitStrength value …`,
  `setoption name UCI_Elo value N`, `position fen …`, `go movetime 1500 depth 20`;
  never `quit`. Our shim makes `quit` synchronous and restartable.
- Shim logs every line at debug under tag **`WristChessJNI`**:
  `adb -s TITAN20000040244 logcat -s WristChessJNI`.
- Other libs, exact versions from Google Maven: firebase-crashlytics-ndk 20.0.6,
  androidx.graphics:graphics-path 1.0.1, androidx.datastore:datastore-core-android
  1.2.1 (v7a .so hashes matched the APK after `llvm-strip --strip-unneeded`).
- **Wear SDK stub**: on Android 14+ the app calls `com.google.wear.Sdk$VERSION.WEAR_SDK_INT`
  (class `fl5.a`), absent on phones → NoClassDefFoundError at launch. An
  additive smali stub returning 0 (`phone-shims/smali/com/google/wear/Sdk$VERSION.smali`,
  copied into `smali_classes3/` by the script) fixes it. Fire HD8 (API < 34) never
  hit this. Same mechanism for the androidx.wear.ambient stubs (see `phone-shims/`).

## Status / handoff 2026-09-20

**Installed on t2e right now:** `wristchess-phone-universal.apk` from commit
`0c2d979` (built 15:21, installed ~15:22 local), user 0 only — the copies that
`adb install` had put into user 10 (Island) and 11 (cloneUser) were removed with
`pm uninstall --user 10|11 net.kusik.wristchess`. Working tree clean; `decoded/`
matches that build (manifest activity, `smali_classes3/` stubs, `classes4.dex`,
`res/values/styles.xml` Theme.App patch) — no half-applied smali anywhere.

**Verified working:** installs (arm64), launches, **operator played a full
offline game against the engine** (arm64 Fairy-Stockfish + JNI shim), no
crashes since the ambient stubs (crash buffer clean). Fullscreen/no-title theme
applied (window shows FLAG_FULLSCREEN).

**Enter-token (REMOTE_INPUT) crash — fixed in the APK, operator verified working.**
Root cause was two-fold: (1) with `android:exported="false"` the app's own
implicit `startActivityForResult(Intent(REMOTE_INPUT))` did not resolve on this
Android 16 build (shell `query-activities` listed it, the app got
ActivityNotFoundException) → activity is now `exported="true"`; (2) the APK was
installed into all three users, so the resolver saw two identical candidates
and returned the chooser (`ResolverActivity`) → keep it in user 0 only
(`adb -s TITAN20000040244 install -r --user 0 …` for future installs). Shell
proof after both: `am start -a android.support.wearable.input.action.REMOTE_INPUT`
→ `Displayed net.kusik.wristchess/.phoneshim.RemoteInputActivity`, resolve-activity
returns it directly. The intent the app builds (`jr1.B`) has no package/
component/extra categories; result is read from string extra `result_text` or
`RemoteInput.getResultsFromIntent()["result"]` (`kl1`), both provided.
Next step if the operator still sees a crash: `adb logcat -b crash`, and check
`cmd package query-activities -a …REMOTE_INPUT` shows exactly one entry.

**Puzzles screen and main board UI — Fixed and verified.** The `wristchess_phone_build.py` script now explicitly patches `xd0.smali` so the board uses `smallestScreenWidthDp` (filling the width), patches `fz3.smali` to fix the Puzzles text sizes, and sizes the board to `smallestScreenWidthDp - 100` (which naturally pushes the player names in from the corners to avoid the camera hole while leaving exactly enough room on the left for the resign and draw buttons).

**Rebuild / reinstall (from `decoded/` as it is now):**
`export JAVA_HOME=/opt/homebrew/opt/openjdk@21; BT=~/Library/Android/sdk/build-tools/37.0.0;
apktool b -q -o /tmp/u.apk decoded && $BT/zipalign -p -f 4 /tmp/u.apk /tmp/ua.apk &&
$BT/apksigner sign --ks phone-debug.keystore --ks-pass pass:wristchess --key-pass pass:wristchess --ks-key-alias wristchess --out wristchess-phone-universal.apk /tmp/ua.apk &&
adb -s TITAN20000040244 install -r --user 0 wristchess-phone-universal.apk`.
After editing `phone-shims/java/`, recompile with the javac+d8 lines in
`build_shims()` of the script and copy the dex to `decoded/classes4.dex`.
Full from-Play path: `wristchess_phone_build.py` (does all patches itself).
Scratch artifacts (session-only, disposable): `/private/tmp/claude-501/…/scratchpad/`
(AAR extracts, shim classes, unsigned/aligned APKs, pulled base.apk).

- Open choices: pin engine `Threads` lower than 8 for battery (edit
  `ensure_engine_running()` in the shim, rebuild via `arm64/build.sh`).
- Google Drive: APKs go to My Drive `A-Z/Software/APKs`
  (folder id `[REDACTED]`). Both APKs uploaded 2026-09-20 via
  rclone remote `gdrive-default:` (rclone's shared client, being retired in 2026).
  The operator's own remote `google-drive:` has a custom OAuth client that still
  needs `http://127.0.0.1:53682/` added as an authorized redirect URI in Google
  Cloud Console before `rclone config reconnect google-drive:` will work.

## Conventions

- Commit trailers: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`,
  `Claude-Session: https://claude.ai/code/session_01EW1AVLdCJH8EZDaGRqbsfw`.
- Don't publish the APKs or the decoded app anywhere public (proprietary app);
  the arm64 shim + scripts are ours (GPLv3 via Fairy-Stockfish) if ever split out.
