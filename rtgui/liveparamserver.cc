#include "liveparamserver.h"
#include "liveparamcontroller.h"

#include <atomic>
#include <chrono>
#include <cstring>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
#include <glib.h>
#include <gdk/gdk.h>

#ifdef __APPLE__
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/ucred.h>
#include <sys/un.h>
#include <unistd.h>
#endif

namespace art {
namespace liveparam {

namespace {

std::atomic<int> g_pendingGuiCommands{0};

#ifdef __APPLE__

void handleClient(int clientFd, const std::string &sessionId,
                  std::atomic<bool> &serverRunning)
{
    struct xucred cred;
    socklen_t cred_len = sizeof(cred);
    if (getsockopt(clientFd, SOL_LOCAL, LOCAL_PEERCRED, &cred, &cred_len) < 0 ||
        cred.cr_version != XUCRED_VERSION || cred.cr_uid != getuid()) {
        std::string err =
            "{\"protocolVersion\":1,\"requestId\":null,\"sessionId\":\"" +
            sessionId +
            "\",\"editorId\":\"\",\"status\":\"ERROR\",\"error\":{\"code\":"
            "\"UNAUTHORIZED\",\"message\":\"Peer authentication failed\","
            "\"details\":{},\"retryable\":false}}\n";
        send(clientFd, err.c_str(), err.size(), 0);
        close(clientFd);
        return;
    }

    std::string buffer;
    buffer.reserve(4096);
    char chunk[2048];

    while (serverRunning.load()) {
        ssize_t n = recv(clientFd, chunk, sizeof(chunk), 0);
        if (n <= 0) {
            break;
        }
        buffer.append(chunk, n);

        size_t newlinePos = buffer.find('\n');
        while (newlinePos != std::string::npos) {
            std::string line = buffer.substr(0, newlinePos);
            buffer.erase(0, newlinePos + 1);

            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }

            if (line.size() > 65536) {
                std::string err =
                    "{\"protocolVersion\":1,\"requestId\":null,\"sessionId\":\"" +
                    sessionId +
                    "\",\"editorId\":\"\",\"status\":\"ERROR\",\"error\":{"
                    "\"code\":\"INVALID_REQUEST\",\"message\":\"Frame exceeds "
                    "64 KiB\",\"details\":{},\"retryable\":false}}\n";
                send(clientFd, err.c_str(), err.size(), 0);
                newlinePos = buffer.find('\n');
                continue;
            }

            if (line.empty()) {
                newlinePos = buffer.find('\n');
                continue;
            }

            if (g_pendingGuiCommands.load() >= 32) {
                std::string err =
                    "{\"protocolVersion\":1,\"requestId\":null,\"sessionId\":\"" +
                    sessionId +
                    "\",\"editorId\":\"\",\"status\":\"ERROR\",\"error\":{"
                    "\"code\":\"BUSY\",\"message\":\"Command queue is full\","
                    "\"details\":{},\"retryable\":true}}\n";
                send(clientFd, err.c_str(), err.size(), 0);
                newlinePos = buffer.find('\n');
                continue;
            }

            g_pendingGuiCommands++;
            auto prom = std::make_shared<std::promise<std::string>>();
            auto fut = prom->get_future();

            struct DispatchData {
                std::string req;
                std::shared_ptr<std::promise<std::string>> promise;
            };

            auto *ddata = new DispatchData{line, prom};

            gdk_threads_add_idle_full(
                G_PRIORITY_DEFAULT_IDLE,
                [](gpointer data) -> gboolean {
                    auto *d = static_cast<DispatchData *>(data);
                    std::string resp =
                        LiveParamController::getInstance().handleCommand(
                            d->req);
                    d->promise->set_value(resp);
                    delete d;
                    return FALSE;
                },
                ddata, nullptr);

            std::string response = fut.get();
            g_pendingGuiCommands--;

            response += "\n";
            send(clientFd, response.c_str(), response.size(), 0);

            newlinePos = buffer.find('\n');
        }
    }

    close(clientFd);
}

#endif // __APPLE__

} // namespace

LiveParamServer &LiveParamServer::getInstance()
{
    static LiveParamServer instance;
    return instance;
}

LiveParamServer::LiveParamServer()
{
}

LiveParamServer::~LiveParamServer()
{
    stop();
}

bool LiveParamServer::start()
{
#ifndef __APPLE__
    return false;
#else
    if (running_) {
        return true;
    }

    const char *env = g_getenv("ART_LIVE_PARAM");
    if (!env || std::strcmp(env, "1") != 0) {
        return false;
    }

    LiveParamController::getInstance().init();

    uid_t uid = getuid();
    pid_t pid = getpid();
    std::string dir = "/tmp/art-liveparam-" + std::to_string(uid);

    mkdir(dir.c_str(), 0700);
    chmod(dir.c_str(), 0700);

    socketPath_ = dir + "/art-" + std::to_string(pid) + ".sock";
    unlink(socketPath_.c_str());

    mode_t oldMask = umask(0077);
    serverFd_ = socket(AF_UNIX, SOCK_STREAM, 0);
    if (serverFd_ < 0) {
        umask(oldMask);
        return false;
    }

    struct sockaddr_un addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socketPath_.c_str(),
                 sizeof(addr.sun_path) - 1);

    if (bind(serverFd_, reinterpret_cast<struct sockaddr *>(&addr),
             sizeof(addr)) < 0) {
        close(serverFd_);
        serverFd_ = -1;
        umask(oldMask);
        return false;
    }

    umask(oldMask);
    chmod(socketPath_.c_str(), 0600);

    if (listen(serverFd_, 16) < 0) {
        close(serverFd_);
        serverFd_ = -1;
        unlink(socketPath_.c_str());
        return false;
    }

    running_ = true;

    auto *th = new std::thread([this]() {
        std::atomic<bool> isRunning{true};
        std::vector<std::thread> clientThreads;

        while (running_) {
            struct sockaddr_un clientAddr;
            socklen_t clientLen = sizeof(clientAddr);
            int clientFd =
                accept(serverFd_,
                       reinterpret_cast<struct sockaddr *>(&clientAddr),
                       &clientLen);
            if (clientFd < 0) {
                if (!running_) {
                    break;
                }
                continue;
            }

            std::string sessId =
                LiveParamController::getInstance().getSessionId();
            clientThreads.emplace_back(
                [clientFd, sessId, &isRunning]() {
                    handleClient(clientFd, sessId, isRunning);
                });
        }

        isRunning.store(false);
        for (auto &t : clientThreads) {
            if (t.joinable()) {
                t.join();
            }
        }
    });

    serverThread_ = th;
    return true;
#endif
}

void LiveParamServer::stop()
{
#ifdef __APPLE__
    if (!running_) {
        return;
    }

    running_ = false;

    if (serverFd_ >= 0) {
        shutdown(serverFd_, SHUT_RDWR);
        close(serverFd_);
        serverFd_ = -1;
    }

    if (!socketPath_.empty()) {
        unlink(socketPath_.c_str());
        socketPath_.clear();
    }

    if (serverThread_) {
        auto *th = static_cast<std::thread *>(serverThread_);
        if (th->joinable()) {
            th->join();
        }
        delete th;
        serverThread_ = nullptr;
    }

    LiveParamController::getInstance().cleanup();
#endif
}

} // namespace liveparam
} // namespace art
