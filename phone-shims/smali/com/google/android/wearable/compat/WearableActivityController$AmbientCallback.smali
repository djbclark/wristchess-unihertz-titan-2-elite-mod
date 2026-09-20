# Phone stub for the Wear OS shared library (com.google.android.wearable).
# Base class of androidx/wear/ambient/WearableControllerProvider$1. All four
# callbacks must be DECLARED here (not abstract): WearableControllerProvider.a()
# does getDeclaredMethod("onEnterAmbient", Bundle.class) on this class and
# throws IllegalStateException on NoSuchMethodException. They are never invoked
# on a phone because the stub WearableActivityController never enters ambient.
.class public abstract Lcom/google/android/wearable/compat/WearableActivityController$AmbientCallback;
.super Ljava/lang/Object;


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method


# virtual methods
.method public onEnterAmbient(Landroid/os/Bundle;)V
    .locals 0

    return-void
.end method

.method public onExitAmbient()V
    .locals 0

    return-void
.end method

.method public onInvalidateAmbientOffload()V
    .locals 0

    return-void
.end method

.method public onUpdateAmbient()V
    .locals 0

    return-void
.end method
