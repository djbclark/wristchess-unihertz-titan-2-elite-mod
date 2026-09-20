# Stub for com.google.wear.Sdk.VERSION from the Wear OS shared library
# (com.google.android.wearable), which does not exist on phones. The app reads
# WEAR_SDK_INT on API >= 34 and crashed with NoClassDefFoundError; 0 is what it
# uses below API 34.
.class public final Lcom/google/wear/Sdk$VERSION;
.super Ljava/lang/Object;


# static fields
.field public static final RELEASE:I = 0x0

.field public static final WEAR_SDK_INT:I = 0x0
