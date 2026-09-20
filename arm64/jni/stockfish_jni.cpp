// JNI shim that wraps Fairy-Stockfish for Wrist Chess (net.kusik.wristchess).
//
// Re-implements the contract of the app's original libstockfish.so (reverse
// engineered from the armeabi-v7a Play split, see ../build.sh for details):
//
//   * JNI_OnLoad caches the JavaVM, looks up
//       net.kusik.wristchess.shared.chessengine.UCIChessEngineAndroid#engineToClient(String)
//     and swaps std::cin / std::cout for a command queue and a line sink.
//   * clientToEngine(String) (Kotlin: `private external fun clientToEngine(cmd: String)`)
//     keeps a global ref to the calling object the first time it is called,
//     lazily starts the engine thread, and queues the command (the Kotlin side
//     already appends "\n").
//   * Every '\n'-terminated line the engine writes to std::cout is delivered as
//     ONE call to engineToClient(String) (without the newline), from whichever
//     engine thread produced it (attached to the JVM on demand).
//   * "quit" ends UCI::loop(); the engine thread exits. Unlike the original
//     (which would std::terminate if used again), the next clientToEngine()
//     transparently starts a fresh engine thread.
//   * Like the original, the shim sets `Threads` to the core count on startup.
//
// Everything is logged under the tag WristChessJNI (debug level for traffic).
//
// GPL-3.0, like Fairy-Stockfish.

#include <jni.h>
#include <android/log.h>

#include <atomic>
#include <condition_variable>
#include <deque>
#include <iostream>
#include <mutex>
#include <streambuf>
#include <string>
#include <thread>

#include "bitboard.h"
#include "endgame.h"
#include "position.h"
#include "psqt.h"
#include "search.h"
#include "syzygy/tbprobe.h"
#include "thread.h"
#include "tt.h"
#include "uci.h"
#include "piece.h"
#include "variant.h"
#include "xboard.h"

#define LOG_TAG "WristChessJNI"
#define LOGD(...) __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG, __VA_ARGS__)
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

using namespace Stockfish;

namespace {

const char* const kEngineClass = "net/kusik/wristchess/shared/chessengine/UCIChessEngineAndroid";
const char* const kCallbackName = "engineToClient";
const char* const kCallbackSig = "(Ljava/lang/String;)V";

JavaVM* g_vm = nullptr;
jmethodID g_engineToClient = nullptr;
jobject g_engineObj = nullptr;  // global ref, set on first clientToEngine()

// Attach the current thread to the JVM if needed; detach automatically when the
// thread exits. Engine threads (UCI loop, search threads) are long-lived, so
// attaching once per thread is cheap.
struct ThreadAttachment {
    bool attached = false;
    ~ThreadAttachment() {
        if (attached && g_vm)
            g_vm->DetachCurrentThread();
    }
};
thread_local ThreadAttachment t_attachment;

JNIEnv* env_for_this_thread() {
    JNIEnv* env = nullptr;
    jint rc = g_vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6);
    if (rc == JNI_OK)
        return env;
    if (rc == JNI_EDETACHED) {
        JavaVMAttachArgs args;
        args.version = JNI_VERSION_1_6;
        args.name = const_cast<char*>("StockfishEngine");
        args.group = nullptr;
        if (g_vm->AttachCurrentThread(&env, &args) == JNI_OK) {
            t_attachment.attached = true;
            return env;
        }
        LOGE("AttachCurrentThread failed");
        return nullptr;
    }
    LOGE("GetEnv failed: %d", rc);
    return nullptr;
}

// std::cin replacement: blocking queue of commands pushed by clientToEngine().
class jni_source : public std::streambuf {
public:
    void push(std::string cmd) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            queue_.push_back(std::move(cmd));
        }
        cv_.notify_one();
    }

    // Drop anything still queued (used when the engine thread has exited).
    void clear() {
        std::lock_guard<std::mutex> lock(mutex_);
        queue_.clear();
        setg(nullptr, nullptr, nullptr);
    }

protected:
    int underflow() override {
        if (gptr() < egptr())
            return traits_type::to_int_type(*gptr());
        std::unique_lock<std::mutex> lock(mutex_);
        do {
            cv_.wait(lock, [this] { return !queue_.empty(); });
            current_ = std::move(queue_.front());
            queue_.pop_front();
        } while (current_.empty());
        char* base = &current_[0];
        setg(base, base, base + current_.size());
        return traits_type::to_int_type(*gptr());
    }

private:
    std::mutex mutex_;
    std::condition_variable cv_;
    std::deque<std::string> queue_;
    std::string current_;
};

// std::cout replacement: delivers each complete line to engineToClient(String).
class jni_sink : public std::streambuf {
protected:
    int overflow(int c) override {
        if (c == traits_type::eof())
            return traits_type::not_eof(c);
        std::lock_guard<std::mutex> lock(mutex_);
        if (c != '\n') {
            line_.push_back(static_cast<char>(c));
            return c;
        }
        deliver(line_);
        line_.clear();
        return c;
    }

private:
    void deliver(const std::string& line) {
        LOGD("engine -> client: %s", line.c_str());
        if (!g_engineObj || !g_engineToClient) {
            LOGE("dropping engine output, no Java receiver: %s", line.c_str());
            return;
        }
        JNIEnv* env = env_for_this_thread();
        if (!env)
            return;
        jstring js = env->NewStringUTF(line.c_str());
        if (!js) {
            env->ExceptionClear();
            LOGE("NewStringUTF failed for: %s", line.c_str());
            return;
        }
        env->CallVoidMethod(g_engineObj, g_engineToClient, js);
        if (env->ExceptionCheck()) {
            LOGE("engineToClient threw; clearing");
            env->ExceptionDescribe();
            env->ExceptionClear();
        }
        env->DeleteLocalRef(js);
    }

    std::mutex mutex_;
    std::string line_;
};

jni_source g_source;
jni_sink g_sink;

std::mutex g_engine_mutex;  // guards g_thread / g_finished / g_engineObj
// Heap-allocated on purpose: a joinable std::thread global would std::terminate
// in static destructors if the process ever exit()s while the engine runs.
std::thread* g_thread = nullptr;
std::atomic<bool> g_finished{false};

// Mirrors Fairy-Stockfish's main(), reading std::cin (g_source) and writing
// std::cout (g_sink) until "quit".
void engine_main() {
    static char arg0[] = "stockfish";
    static char* argv[] = {arg0, nullptr};
    const int argc = 1;

    LOGI("engine thread started");

    std::cout << engine_info() << std::endl;

    pieceMap.init();
    variants.init();
    CommandLine::init(argc, argv);
    UCI::init(Options);
    Tune::init();
    PSQT::init(variants.find(Options["UCI_Variant"])->second);
    Bitboards::init();
    Position::init();
    Bitbases::init();
    Endgames::init();
    Threads.set(size_t(Options["Threads"]));
    Search::clear();  // After threads are up
    Eval::NNUE::init();

    UCI::loop(argc, argv);

    Threads.set(0);
    variants.clear_all();
    pieceMap.clear_all();
    delete XBoard::stateMachine;
    XBoard::stateMachine = nullptr;

    LOGI("engine thread exiting (quit received)");
    g_finished.store(true);
}

// Called with g_engine_mutex held. Waits for the engine thread to exit.
void join_engine() {
    if (!g_thread)
        return;
    g_thread->join();
    delete g_thread;
    g_thread = nullptr;
    g_finished.store(false);
    g_source.clear();
}

// Called with g_engine_mutex held.
void ensure_engine_running() {
    if (g_thread) {
        if (!g_finished.load())
            return;
        join_engine();
        LOGI("restarting engine after quit");
    }
    unsigned cores = std::thread::hardware_concurrency();
    if (cores == 0)
        cores = 1;
    LOGI("starting engine thread, Threads=%u", cores);
    g_source.push("setoption name Threads value " + std::to_string(cores) + "\n");
    g_thread = new std::thread(engine_main);
}

}  // namespace

extern "C" JNIEXPORT jint JNI_OnLoad(JavaVM* vm, void*) {
    g_vm = vm;
    JNIEnv* env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) {
        LOGE("JNI_OnLoad: GetEnv failed");
        return JNI_ERR;
    }
    jclass cls = env->FindClass(kEngineClass);
    if (!cls) {
        LOGE("JNI_OnLoad: class %s not found", kEngineClass);
        return JNI_ERR;
    }
    g_engineToClient = env->GetMethodID(cls, kCallbackName, kCallbackSig);
    env->DeleteLocalRef(cls);
    if (!g_engineToClient) {
        LOGE("JNI_OnLoad: method %s%s not found", kCallbackName, kCallbackSig);
        return JNI_ERR;
    }

    std::cin.rdbuf(&g_source);
    std::cout.rdbuf(&g_sink);
    std::cin.clear();
    std::cout.clear();

    LOGI("JNI_OnLoad: Fairy-Stockfish shim ready (%s)", engine_info().c_str());
    return JNI_VERSION_1_6;
}

extern "C" JNIEXPORT void JNICALL
Java_net_kusik_wristchess_shared_chessengine_UCIChessEngineAndroid_clientToEngine(
    JNIEnv* env, jobject thiz, jstring jcmd) {
    std::string cmd;
    if (jcmd) {
        const char* chars = env->GetStringUTFChars(jcmd, nullptr);
        if (chars) {
            cmd.assign(chars);
            env->ReleaseStringUTFChars(jcmd, chars);
        }
    }
    if (cmd.empty())
        return;
    if (cmd.back() != '\n')
        cmd.push_back('\n');

    LOGD("client -> engine: %.*s", static_cast<int>(cmd.size() - 1), cmd.c_str());

    std::lock_guard<std::mutex> lock(g_engine_mutex);
    if (!g_engineObj)
        g_engineObj = env->NewGlobalRef(thiz);

    // "quit" is handled synchronously: hand it to the engine, wait for the
    // engine thread to finish, and drop the queue. The next command starts a
    // fresh engine. (The original library would std::terminate on reuse.)
    if (cmd == "quit\n") {
        if (!g_thread) {
            LOGD("quit with no engine running; ignored");
            return;
        }
        g_source.push(std::move(cmd));
        join_engine();
        LOGI("engine stopped");
        return;
    }

    ensure_engine_running();
    g_source.push(std::move(cmd));
}
