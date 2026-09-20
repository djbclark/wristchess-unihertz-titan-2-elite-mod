#!/usr/bin/env bash
# Smoke-test prebuilt-libs/arm64-v8a/libstockfish.so on a connected arm64 device
# with test/fake_jni_test.cpp (no app needed). Usage: run-device-test.sh [adb serial]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$HERE")"
LIB="$REPO_ROOT/prebuilt-libs/arm64-v8a/libstockfish.so"
SERIAL="${1:-${ANDROID_SERIAL:-}}"
ADB=(adb); [ -n "$SERIAL" ] && ADB=(adb -s "$SERIAL")

NDK_VERSION="${NDK_VERSION:-28.2.13676358}"
ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
NDK="${ANDROID_NDK_HOME:-$ANDROID_SDK_ROOT/ndk/$NDK_VERSION}"
case "$(uname -s)" in Darwin) HOST_TAG=darwin-x86_64 ;; *) HOST_TAG=linux-x86_64 ;; esac
CXX="$NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin/aarch64-linux-android21-clang++"

OUT="$HERE/out/test"
mkdir -p "$OUT"
"$CXX" -std=c++17 -O1 -fPIE -pie -static-libstdc++ -o "$OUT/fake_jni_test" "$HERE/test/fake_jni_test.cpp" -ldl

REMOTE=/data/local/tmp/wristchess-test
"${ADB[@]}" shell "mkdir -p $REMOTE"
"${ADB[@]}" push "$OUT/fake_jni_test" "$LIB" "$REMOTE/" >/dev/null
"${ADB[@]}" shell "cd $REMOTE && chmod 755 fake_jni_test && ./fake_jni_test ./libstockfish.so"
