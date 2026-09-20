# Phone stub for the Wear OS shared library (com.google.android.wearable).
# androidx.wear.ambient (AmbientDelegate / WearableControllerProvider) needs this
# class to exist -- SharedLibraryVersion checks Class.forName() on it and throws
# IllegalStateException otherwise. On a phone there is no ambient mode, so every
# method is a no-op and isAmbient() is always false. Method set and signatures
# are exactly what androidx/wear/ambient/AmbientDelegate.smali calls.
.class public Lcom/google/android/wearable/compat/WearableActivityController;
.super Ljava/lang/Object;


# direct methods
.method public constructor <init>(Ljava/lang/String;Landroid/app/Activity;Lcom/google/android/wearable/compat/WearableActivityController$AmbientCallback;)V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method


# virtual methods
.method public dump(Ljava/lang/String;Ljava/io/FileDescriptor;Ljava/io/PrintWriter;[Ljava/lang/String;)V
    .locals 0

    return-void
.end method

.method public isAmbient()Z
    .locals 1

    const/4 v0, 0x0

    return v0
.end method

.method public onCreate()V
    .locals 0

    return-void
.end method

.method public onDestroy()V
    .locals 0

    return-void
.end method

.method public onPause()V
    .locals 0

    return-void
.end method

.method public onResume()V
    .locals 0

    return-void
.end method

.method public onStop()V
    .locals 0

    return-void
.end method

.method public setAmbientEnabled()V
    .locals 0

    return-void
.end method

.method public setAmbientOffloadEnabled(Z)V
    .locals 0

    return-void
.end method

.method public setAutoResumeEnabled(Z)V
    .locals 0

    return-void
.end method
