#pragma once

#include <atomic>
#include <memory>
#include <string>
#include <thread>

namespace art {
namespace liveparam {

class LiveParamServer {
public:
    static LiveParamServer &getInstance();

    bool start(bool explicitlyEnabled = false);
    void stop();

    bool isRunning() const { return running_.load(std::memory_order_acquire); }
    const std::string &getSocketPath() const { return socketPath_; }

private:
    friend struct LiveParamServerTestAccess;
    static bool authenticatePeer(int fd);
    LiveParamServer();
    ~LiveParamServer();

    std::atomic<bool> running_{false};
    std::string socketPath_;
    struct Runtime;
    std::shared_ptr<Runtime> runtime_;
    std::thread serverThread_;
};

} // namespace liveparam
} // namespace art
