#!/usr/bin/env bash
# Fetch the arm64-v8a builds of the six non-engine native libs Wrist Chess 1.10.1
# bundles, straight from the exact library versions the app was built with, and
# place them in ../prebuilt-libs/arm64-v8a/.
#
# Versions were identified from the decoded APK and verified by hashing the
# armeabi-v7a .so files in these AARs against the ones in the Play split
# (all six match byte-for-byte after `llvm-strip --strip-unneeded`, which is
# what AGP applies when packaging):
#   com.google.firebase:firebase-crashlytics-ndk:20.0.6   (CrashlyticsNdkRegistrar "fire-cls-ndk" -> "20.0.6")
#       libcrashlytics.so, libcrashlytics-common.so, libcrashlytics-handler.so, libcrashlytics-trampoline.so
#   androidx.graphics:graphics-path:1.0.1                 (META-INF/androidx.graphics_graphics-path.version)
#       libandroidx.graphics.path.so
#   androidx.datastore:datastore-core-android:1.2.1       (META-INF/androidx.datastore_datastore-core.version)
#       libdatastore_shared_counter.so
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$HERE")"
DEST="$REPO_ROOT/prebuilt-libs/arm64-v8a"
WORK="$HERE/out/aars"

NDK_VERSION="${NDK_VERSION:-28.2.13676358}"
ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
NDK="${ANDROID_NDK_HOME:-$ANDROID_SDK_ROOT/ndk/$NDK_VERSION}"
case "$(uname -s)" in Darwin) HOST_TAG=darwin-x86_64 ;; *) HOST_TAG=linux-x86_64 ;; esac
STRIP="$NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin/llvm-strip"
[ -x "$STRIP" ] || { echo "llvm-strip not found at $STRIP" >&2; exit 1; }

MAVEN="https://dl.google.com/android/maven2"
AARS=(
  "com/google/firebase/firebase-crashlytics-ndk/20.0.6/firebase-crashlytics-ndk-20.0.6.aar"
  "androidx/graphics/graphics-path/1.0.1/graphics-path-1.0.1.aar"
  "androidx/datastore/datastore-core-android/1.2.1/datastore-core-android-1.2.1.aar"
)

mkdir -p "$WORK" "$DEST"
for path in "${AARS[@]}"; do
  aar="$WORK/$(basename "$path")"
  [ -s "$aar" ] || curl -sfL -o "$aar" "$MAVEN/$path"
  dir="${aar%.aar}"
  rm -rf "$dir"; mkdir -p "$dir"
  unzip -qo "$aar" 'jni/arm64-v8a/*' -d "$dir"
  for so in "$dir"/jni/arm64-v8a/*.so; do
    "$STRIP" --strip-unneeded -o "$DEST/$(basename "$so")" "$so"
    echo "$(basename "$aar") -> $DEST/$(basename "$so")"
  done
done
ls -la "$DEST"
