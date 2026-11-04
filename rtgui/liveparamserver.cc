#include "liveparamserver.h"
#include "liveparamcontroller.h"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <map>
#include <mutex>
#include <vector>
#include <glib.h>
#include <gdk/gdk.h>

#ifdef __APPLE__
#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/ucred.h>
#include <sys/un.h>
#include <unistd.h>
#endif

namespace art {
namespace liveparam {

#ifdef __APPLE__

struct LiveParamServer::Runtime: std::enable_shared_from_this<Runtime> {
    static constexpr size_t maxFrame = 65536;
    static constexpr size_t maxPending = 32;
    static constexpr size_t maxClients = 64;

    struct Pending {
        enum State { WAITING, EXECUTING, DONE, CANCELLED } state = WAITING;
        uint64_t id = 0;
        guint source = 0;
        std::string request;
        std::string response;
    };
    struct Client {
        std::string input;
        std::string output;
        size_t sent = 0;
        bool closing = false;
        std::shared_ptr<Pending> pending;
    };
    struct Dispatch {
        std::weak_ptr<Runtime> runtime;
        std::shared_ptr<Pending> pending;
    };

    explicit Runtime(std::string session): sessionId(std::move(session)) {}
    ~Runtime()
    {
        if (listenFd >= 0) {
            close(listenFd);
        }
        if (bound) {
            unlink(path.c_str());
        }
    }

    static bool configureFd(int fd)
    {
        const int flags = fcntl(fd, F_GETFL);
        const int fdFlags = fcntl(fd, F_GETFD);
        int yes = 1;
        return flags >= 0 && fdFlags >= 0 &&
            fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0 &&
            fcntl(fd, F_SETFD, fdFlags | FD_CLOEXEC) == 0 &&
            setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, sizeof(yes)) == 0;
    }

    bool prepare()
    {
        const uid_t uid = geteuid();
        const std::string dir = "/tmp/art-liveparam-" + std::to_string(uid);
        if (mkdir(dir.c_str(), 0700) != 0 && errno != EEXIST) {
            return false;
        }
        struct stat st{};
        if (lstat(dir.c_str(), &st) || !S_ISDIR(st.st_mode) ||
            st.st_uid != uid || (st.st_mode & 0777) != 0700) {
            return false;
        }
        path = dir + "/art-" + std::to_string(getpid()) + "-" + sessionId + ".sock";
        sockaddr_un addr{};
        if (path.size() >= sizeof(addr.sun_path)) {
            return false;
        }
        listenFd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (listenFd < 0 || !configureFd(listenFd)) {
            return false;
        }
        addr.sun_family = AF_UNIX;
        std::memcpy(addr.sun_path, path.c_str(), path.size() + 1);
        if (bind(listenFd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr))) {
            return false;
        }
        bound = true;
        return chmod(path.c_str(), 0600) == 0 && listen(listenFd, 32) == 0;
    }

    static bool authenticated(int fd)
    {
        return LiveParamServer::authenticatePeer(fd);
    }

    std::string error(const char *code, const char *message, bool retryable) const
    {
        return makeTransportError(sessionId, code, message, retryable) + "\n";
    }

    std::shared_ptr<Pending> enqueue(std::string request)
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (!active.load() || pending.size() >= maxPending) {
            return nullptr;
        }
        auto command = std::make_shared<Pending>();
        command->id = ++nextCommand;
        command->request = std::move(request);
        pending.emplace(command->id, command);
        auto *data = new Dispatch{shared_from_this(), command};
        // The mutex also covers source registration: a fast GUI dispatch cannot
        // finish before its cancellation handle has been published.
        command->source = gdk_threads_add_idle_full(
            G_PRIORITY_DEFAULT_IDLE,
            [](gpointer raw) -> gboolean {
                auto *data = static_cast<Dispatch *>(raw);
                auto runtime = data->runtime.lock();
                auto command = data->pending;
                if (!runtime) {
                    return G_SOURCE_REMOVE;
                }
                {
                    std::lock_guard<std::mutex> lock(runtime->mutex);
                    if (!runtime->active.load() || command->state != Pending::WAITING) {
                        return G_SOURCE_REMOVE;
                    }
                    command->state = Pending::EXECUTING;
                }
                std::string response;
                try {
                    response = LiveParamController::getInstance().handleCommand(
                        command->request);
                } catch (...) {
                    response = makeTransportError(runtime->sessionId,
                        "INTERNAL_ERROR", "Command result is unknown; query state", false);
                }
                {
                    std::lock_guard<std::mutex> lock(runtime->mutex);
                    command->response = std::move(response);
                    command->state = Pending::DONE;
                    command->source = 0;
                    runtime->pending.erase(command->id);
                }
                return G_SOURCE_REMOVE;
            }, data, [](gpointer raw) { delete static_cast<Dispatch *>(raw); });
        return command;
    }

    void cancel(const std::shared_ptr<Pending> &command)
    {
        if (!command) {
            return;
        }
        guint source = 0;
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (command->state != Pending::WAITING) {
                return;
            }
            command->state = Pending::CANCELLED;
            source = command->source;
            command->source = 0;
            pending.erase(command->id);
        }
        if (source) {
            g_source_remove(source);
        }
    }

    void cancelAll()
    {
        std::vector<std::shared_ptr<Pending>> commands;
        {
            std::lock_guard<std::mutex> lock(mutex);
            for (auto &entry : pending) {
                commands.push_back(entry.second);
            }
        }
        for (auto &command : commands) {
            cancel(command);
        }
    }

    void stageResponse(Client &client)
    {
        if (client.pending) {
            std::lock_guard<std::mutex> lock(mutex);
            if (client.pending->state == Pending::DONE) {
                client.output = std::move(client.pending->response);
                if (client.output.size() > maxFrame) {
                    client.output = error("BUSY", "Response exceeds frame capacity", true);
                } else {
                    client.output += '\n';
                }
                client.pending.reset();
            }
        }
        if (!client.pending && client.output.empty() && !client.closing) {
            const auto newline = client.input.find('\n');
            if (newline != std::string::npos) {
                if (newline > maxFrame) {
                    rejectOversized(client);
                } else {
                    auto line = client.input.substr(0, newline);
                    client.input.erase(0, newline + 1);
                    client.pending = enqueue(std::move(line));
                    if (!client.pending) {
                        client.output = error("BUSY", "GUI command queue is full", true);
                    }
                }
            } else if (client.input.size() > maxFrame) {
                rejectOversized(client);
            }
        }
    }

    void rejectOversized(Client &client)
    {
        client.input.clear();
        client.output = error("INVALID_REQUEST", "Frame exceeds 64 KiB", false);
        client.closing = true;
    }

    void run()
    {
        std::map<int, Client> clients;
        while (active.load()) {
            std::vector<pollfd> descriptors;
            descriptors.push_back({listenFd, POLLIN, 0});
            for (auto &entry : clients) {
                auto &client = entry.second;
                stageResponse(client);
                short events = !client.output.empty() ? POLLOUT :
                    (!client.pending && !client.closing ? POLLIN : 0);
                descriptors.push_back({entry.first, events, 0});
            }
            const int result = poll(descriptors.data(), descriptors.size(), 20);
            if (result < 0) {
                if (errno == EINTR) {
                    continue;
                }
                break;
            }
            if (!active.load()) {
                break;
            }
            if (descriptors[0].revents & POLLIN) {
                for (size_t accepted = 0; active.load() && accepted < maxClients; ++accepted) {
                    const int fd = accept(listenFd, nullptr, nullptr);
                    if (fd < 0) {
                        break;
                    }
                    if (!configureFd(fd)) {
                        close(fd);
                        continue;
                    }
                    if (!authenticated(fd)) {
                        const auto response = error("UNAUTHORIZED", "Peer authentication failed", false);
                        send(fd, response.data(), response.size(), 0);
                        close(fd);
                        continue;
                    }
                    if (clients.size() >= maxClients) {
                        const auto response = error("BUSY", "Connection capacity is full", true);
                        send(fd, response.data(), response.size(), 0);
                        close(fd);
                        continue;
                    }
                    clients.emplace(fd, Client{});
                }
            }
            for (size_t i = 1; i < descriptors.size(); ++i) {
                const int fd = descriptors[i].fd;
                auto it = clients.find(fd);
                if (it == clients.end()) {
                    continue;
                }
                auto &client = it->second;
                const short events = descriptors[i].revents;
                bool keep = !(events & (POLLERR | POLLNVAL | POLLHUP));
                if (keep && (events & POLLIN)) {
                    char bytes[2048];
                    // One extra byte detects overflow even when LF never arrives.
                    const auto capacity = maxFrame + 1 - client.input.size();
                    const auto size = std::min(capacity, sizeof(bytes));
                    const auto count = recv(fd, bytes, size, 0);
                    if (count > 0) {
                        client.input.append(bytes, count);
                        stageResponse(client);
                    } else if (count == 0 || (errno != EAGAIN && errno != EINTR)) {
                        keep = false;
                    }
                }
                if (keep && (events & POLLOUT)) {
                    const auto count = send(fd, client.output.data() + client.sent,
                        client.output.size() - client.sent, 0);
                    if (count > 0) {
                        client.sent += count;
                        if (client.sent == client.output.size()) {
                            client.output.clear();
                            client.sent = 0;
                            keep = !client.closing;
                        }
                    } else if (count < 0 && errno != EAGAIN && errno != EINTR) {
                        keep = false;
                    }
                }
                if (!keep) {
                    cancel(client.pending);
                    close(fd);
                    clients.erase(it);
                }
            }
        }
        active.store(false);
        for (auto &entry : clients) {
            cancel(entry.second.pending);
            close(entry.first);
        }
    }

    const std::string sessionId;
    std::string path;
    int listenFd = -1;
    bool bound = false;
    std::atomic<bool> active{true};
    std::mutex mutex;
    std::map<uint64_t, std::shared_ptr<Pending>> pending;
    uint64_t nextCommand = 0;
};

#else
struct LiveParamServer::Runtime {};
#endif

bool LiveParamServer::authenticatePeer(int fd)
{
#ifdef __APPLE__
    struct xucred cred{};
    socklen_t length = sizeof(cred);
    return getsockopt(fd, SOL_LOCAL, LOCAL_PEERCRED, &cred, &length) == 0 &&
        length == sizeof(cred) && cred.cr_version == XUCRED_VERSION &&
        cred.cr_uid == geteuid();
#else
    return false;
#endif
}

LiveParamServer &LiveParamServer::getInstance()
{
    // The server must be destroyed before the controller it calls on shutdown.
    LiveParamController::getInstance();
    static LiveParamServer instance;
    return instance;
}

LiveParamServer::LiveParamServer() {}
LiveParamServer::~LiveParamServer() { stop(); }

bool LiveParamServer::start(bool explicitlyEnabled)
{
#ifndef __APPLE__
    return false;
#else
    if (running_.load()) {
        return true;
    }
    const char *env = g_getenv("ART_LIVE_PARAM");
    if (!explicitlyEnabled && (!env || std::strcmp(env, "1"))) {
        return false;
    }
    stop();
    auto &controller = LiveParamController::getInstance();
    controller.init();
    auto runtime = std::make_shared<Runtime>(controller.getSessionId());
    if (!runtime->prepare()) {
        controller.cleanup();
        return false;
    }
    runtime_ = runtime;
    socketPath_ = runtime->path;
    running_.store(true);
    try {
        serverThread_ = std::thread([this, runtime] {
            runtime->run();
            running_.store(false);
        });
    } catch (...) {
        running_.store(false);
        runtime_.reset();
        socketPath_.clear();
        controller.cleanup();
        return false;
    }
    return true;
#endif
}

void LiveParamServer::stop()
{
#ifdef __APPLE__
    running_.store(false);
    if (!runtime_ && !serverThread_.joinable()) {
        socketPath_.clear();
        return;
    }
    if (runtime_) {
        runtime_->active.store(false);
        runtime_->cancelAll();
    }
    if (serverThread_.joinable()) {
        serverThread_.join();
    }
    runtime_.reset();
    socketPath_.clear();
    LiveParamController::getInstance().cleanup();
#endif
}

} // namespace liveparam
} // namespace art
