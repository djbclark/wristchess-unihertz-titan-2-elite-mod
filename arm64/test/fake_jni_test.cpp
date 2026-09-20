// On-device smoke test for libstockfish.so without the app: dlopen() the library,
// hand it a minimal fake JavaVM/JNIEnv, and drive it through the same JNI
// contract and UCI commands Wrist Chess uses. Prints every engineToClient()
// line; exits 0 iff "uciok", "readyok" and "bestmove" all came back and the
// engine survives a "quit" + restart.
//
// Build/run: ../run-device-test.sh (needs an arm64 device on adb).
#include <jni.h>

#include <dlfcn.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <string>
#include <vector>

namespace {

std::mutex g_mutex;
std::condition_variable g_cv;
std::vector<std::string> g_lines;

// jstring is represented by a heap std::string*.
const char* fake_GetStringUTFChars(JNIEnv*, jstring s, jboolean* isCopy) {
    if (isCopy) *isCopy = JNI_FALSE;
    return reinterpret_cast<std::string*>(s)->c_str();
}
void fake_ReleaseStringUTFChars(JNIEnv*, jstring, const char*) {}
jstring fake_NewStringUTF(JNIEnv*, const char* s) {
    return reinterpret_cast<jstring>(new std::string(s));
}
void fake_DeleteLocalRef(JNIEnv*, jobject) {}  // strings from NewStringUTF are leaked; fine for a test
jobject fake_NewGlobalRef(JNIEnv*, jobject o) { return o; }
jclass fake_FindClass(JNIEnv*, const char* name) {
    printf("[fake-jni] FindClass(%s)\n", name);
    return reinterpret_cast<jclass>(1);
}
jmethodID fake_GetMethodID(JNIEnv*, jclass, const char* name, const char* sig) {
    printf("[fake-jni] GetMethodID(%s, %s)\n", name, sig);
    return reinterpret_cast<jmethodID>(2);
}
void fake_DeleteLocalRefClass(JNIEnv*, jobject) {}
jboolean fake_ExceptionCheck(JNIEnv*) { return JNI_FALSE; }
void fake_ExceptionClear(JNIEnv*) {}
void fake_ExceptionDescribe(JNIEnv*) {}
// The single vararg after jmethodID is the jstring argument. The C++ JNIEnv
// wrappers call the va_list ("V") variant, so provide both.
void fake_CallVoidMethodV(JNIEnv*, jobject, jmethodID, va_list ap) {
    jstring js = va_arg(ap, jstring);
    std::string line = *reinterpret_cast<std::string*>(js);
    printf("engineToClient: %s\n", line.c_str());
    std::lock_guard<std::mutex> lock(g_mutex);
    g_lines.push_back(line);
    g_cv.notify_all();
}
void fake_CallVoidMethod(JNIEnv* env, jobject obj, jmethodID mid, ...) {
    va_list ap;
    va_start(ap, mid);
    fake_CallVoidMethodV(env, obj, mid, ap);
    va_end(ap);
}

JNINativeInterface g_functions{};
_JNIEnv g_env{};
JNIInvokeInterface g_vm_functions{};
_JavaVM g_vm{};

jint fake_GetEnv(JavaVM*, void** env, jint) {
    *env = &g_env;
    return JNI_OK;
}
jint fake_AttachCurrentThread(JavaVM*, JNIEnv** env, void*) {
    *env = &g_env;
    return JNI_OK;
}
jint fake_DetachCurrentThread(JavaVM*) { return JNI_OK; }

bool wait_for(const char* prefix, int timeout_ms) {
    std::unique_lock<std::mutex> lock(g_mutex);
    return g_cv.wait_for(lock, std::chrono::milliseconds(timeout_ms), [&] {
        for (auto& l : g_lines)
            if (l.compare(0, strlen(prefix), prefix) == 0)
                return true;
        return false;
    });
}

void clear_lines() {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_lines.clear();
}

}  // namespace

int main(int argc, char** argv) {
    setvbuf(stdout, nullptr, _IONBF, 0);
    const char* path = argc > 1 ? argv[1] : "./libstockfish.so";
    void* h = dlopen(path, RTLD_NOW);
    if (!h) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 2;
    }

    g_functions.GetStringUTFChars = fake_GetStringUTFChars;
    g_functions.ReleaseStringUTFChars = fake_ReleaseStringUTFChars;
    g_functions.NewStringUTF = fake_NewStringUTF;
    g_functions.DeleteLocalRef = fake_DeleteLocalRef;
    g_functions.NewGlobalRef = fake_NewGlobalRef;
    g_functions.FindClass = fake_FindClass;
    g_functions.GetMethodID = fake_GetMethodID;
    g_functions.ExceptionCheck = fake_ExceptionCheck;
    g_functions.ExceptionClear = fake_ExceptionClear;
    g_functions.ExceptionDescribe = fake_ExceptionDescribe;
    g_functions.CallVoidMethod = fake_CallVoidMethod;
    g_functions.CallVoidMethodV = fake_CallVoidMethodV;
    g_env.functions = &g_functions;
    g_vm_functions.GetEnv = fake_GetEnv;
    g_vm_functions.AttachCurrentThread = fake_AttachCurrentThread;
    g_vm_functions.DetachCurrentThread = fake_DetachCurrentThread;
    g_vm.functions = &g_vm_functions;

    auto onload = reinterpret_cast<jint (*)(JavaVM*, void*)>(dlsym(h, "JNI_OnLoad"));
    auto c2e = reinterpret_cast<void (*)(JNIEnv*, jobject, jstring)>(
        dlsym(h, "Java_net_kusik_wristchess_shared_chessengine_UCIChessEngineAndroid_clientToEngine"));
    if (!onload || !c2e) {
        fprintf(stderr, "missing JNI exports\n");
        return 2;
    }
    jint v = onload(&g_vm, nullptr);
    printf("[fake-jni] JNI_OnLoad -> 0x%x\n", v);
    if (v != JNI_VERSION_1_6)
        return 3;

    std::string fake_this_obj = "UCIChessEngineAndroid";
    jobject thiz = reinterpret_cast<jobject>(&fake_this_obj);
    auto send = [&](const char* cmd) {
        std::string s = std::string(cmd) + "\n";  // the Kotlin side appends "\n"
        printf("clientToEngine: %s\n", cmd);
        fflush(stdout);
        c2e(&g_env, thiz, reinterpret_cast<jstring>(&s));
    };

    int failures = 0;
    send("uci");
    if (!wait_for("uciok", 10000)) { fprintf(stderr, "FAIL: no uciok\n"); failures++; }
    send("isready");
    if (!wait_for("readyok", 10000)) { fprintf(stderr, "FAIL: no readyok\n"); failures++; }
    send("setoption name UCI_LimitStrength value true");
    send("setoption name UCI_Elo value 1500");
    send("position fen rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    send("go movetime 1500 depth 20");
    if (!wait_for("bestmove", 15000)) { fprintf(stderr, "FAIL: no bestmove\n"); failures++; }

    // quit, then make sure the shim restarts the engine on the next command.
    send("quit");
    clear_lines();
    send("isready");
    if (!wait_for("readyok", 10000)) { fprintf(stderr, "FAIL: no readyok after restart\n"); failures++; }
    send("quit");

    printf(failures ? "RESULT: FAIL (%d)\n" : "RESULT: OK\n", failures);
    return failures ? 1 : 0;
}
