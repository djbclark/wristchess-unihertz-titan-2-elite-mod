#!/usr/bin/env bash
# Build an arm64-v8a libstockfish.so for Wrist Chess from upstream Fairy-Stockfish
# plus the JNI shim in jni/stockfish_jni.cpp, and drop it into
# ../prebuilt-libs/arm64-v8a/ where wristchess_phone_build.py picks it up.
#
# Why Fairy-Stockfish, and why this commit:
#   The original armeabi-v7a libstockfish.so (from the Play split) identifies as
#   "Fairy-Stockfish <DDMMYY> by Fabian Fichter" with an empty Version string and
#   __DATE__ "Jun 16 2026", i.e. a dev build of Fairy-Stockfish master around
#   2026-06-16. FS_COMMIT below is master as of that date. It was built with
#   NDK r28c (clang 19.0.1 / build 13676358, found in the .so), no NNUE
#   embedding (-DNNUE_EMBEDDING_OFF; the lib is 1.3 MB and the APK ships no
#   .nnue asset, so the engine runs on the classical evaluation), no
#   LARGEBOARDS (Bitboard is 64-bit in the mangled symbols), no ALLVARS.
#
# Compiler flags mirror `make build ARCH=armv8 COMP=ndk` from the Fairy-Stockfish
# Makefile (armv8 = -DIS_64BIT -DUSE_POPCNT -DUSE_NEON; NNUE is off so the
# dotprod variant is irrelevant). We drive clang directly because that Makefile
# keys host flags on `uname`, which is wrong when cross-compiling from macOS.
#
# Requirements: Android NDK (default r28c under $ANDROID_SDK_ROOT/ndk), git, curl.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$HERE")"

FS_REPO="https://github.com/fairy-stockfish/Fairy-Stockfish.git"
FS_COMMIT="${FS_COMMIT:-1b5bdd40499bd5c7417bdc532d52fef8847bdf3f}"  # master @ 2026-05-23, current on 2026-06-16
FS_DIR="${FS_DIR:-$HERE/Fairy-Stockfish}"

NDK_VERSION="${NDK_VERSION:-28.2.13676358}"
ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
NDK="${ANDROID_NDK_HOME:-$ANDROID_SDK_ROOT/ndk/$NDK_VERSION}"
API=21

case "$(uname -s)" in
  Darwin) HOST_TAG=darwin-x86_64 ;;
  Linux)  HOST_TAG=linux-x86_64 ;;
  *) echo "unsupported host $(uname -s)" >&2; exit 1 ;;
esac
TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin"
CXX="$TOOLCHAIN/aarch64-linux-android$API-clang++"
STRIP="$TOOLCHAIN/llvm-strip"
[ -x "$CXX" ] || { echo "NDK clang not found at $CXX (install with: sdkmanager \"ndk;$NDK_VERSION\")" >&2; exit 1; }

OUT="$HERE/out/arm64-v8a"
DEST="$REPO_ROOT/prebuilt-libs/arm64-v8a"
JOBS="${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || nproc)}"

# --- 1. source -----------------------------------------------------------------
if [ ! -d "$FS_DIR/.git" ]; then
  git clone -q "$FS_REPO" "$FS_DIR"
fi
git -C "$FS_DIR" fetch -q origin "$FS_COMMIT" 2>/dev/null || true
git -C "$FS_DIR" checkout -q "$FS_COMMIT"
SRC="$FS_DIR/src"

# Source list straight from the pinned Makefile (minus main.cpp, replaced by the shim).
SRCS=$(make -s -C "$SRC" -f Makefile -f <(printf 'print-srcs:\n\t@echo $(SRCS)\n') print-srcs \
       | tr ' ' '\n' | grep -v '^main\.cpp$')

# --- 2. compile ----------------------------------------------------------------
CXXFLAGS=(
  -std=c++17 -Wall -Wcast-qual -fno-exceptions -fno-strict-aliasing
  -O3 -DNDEBUG -flto -fPIC -fvisibility=hidden -stdlib=libc++
  -DUSE_PTHREADS -DIS_64BIT -DUSE_POPCNT -DUSE_NEON -DNNUE_EMBEDDING_OFF
  -Wno-profile-instr-out-of-date
)

rm -rf "$OUT"
for s in $SRCS; do mkdir -p "$OUT/obj/$(dirname "$s")"; done

echo "Compiling Fairy-Stockfish ($FS_COMMIT) for arm64-v8a with $JOBS jobs..."
# Object for syzygy/tbprobe.cpp lands at obj/syzygy/tbprobe.cpp.o, etc.
printf '%s\n' $SRCS | xargs -P "$JOBS" -n 1 -I{} \
  "$CXX" "${CXXFLAGS[@]}" -c -o "$OUT/obj/{}.o" "$SRC/{}"

"$CXX" "${CXXFLAGS[@]}" -I"$SRC" -c -o "$OUT/obj/stockfish_jni.o" "$HERE/jni/stockfish_jni.cpp"

# --- 3. link -------------------------------------------------------------------
echo "Linking libstockfish.so..."
"$CXX" -shared -O3 -flto -fPIC -stdlib=libc++ -static-libstdc++ \
  -Wl,-soname,libstockfish.so -Wl,-z,max-page-size=16384 -Wl,--no-undefined \
  -Wl,--gc-sections -Wl,--exclude-libs,ALL \
  -o "$OUT/libstockfish.unstripped.so" $(find "$OUT/obj" -name '*.o') -llog -lm -latomic

# AGP strips bundled native libs with --strip-unneeded; do the same.
"$STRIP" --strip-unneeded -o "$OUT/libstockfish.so" "$OUT/libstockfish.unstripped.so"

mkdir -p "$DEST"
cp "$OUT/libstockfish.so" "$DEST/libstockfish.so"
ls -la "$DEST/libstockfish.so"
"$TOOLCHAIN/llvm-nm" -D --defined-only "$DEST/libstockfish.so" | grep -E 'JNI_OnLoad|clientToEngine' || {
  echo "expected JNI exports missing" >&2; exit 1; }
echo "Done: $DEST/libstockfish.so"
