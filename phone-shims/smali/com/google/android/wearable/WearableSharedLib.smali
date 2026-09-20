# Phone stub for the Wear OS shared library (com.google.android.wearable).
# androidx/wear/ambient/SharedLibraryVersion$VersionHolder calls version() on
# API >= 25. 1 is the lowest real shared-library version; ambient offload is
# irrelevant since the stub controller never enters ambient anyway.
.class public Lcom/google/android/wearable/WearableSharedLib;
.super Ljava/lang/Object;


# direct methods
.method public static version()I
    .locals 1

    const/4 v0, 0x1

    return v0
.end method
