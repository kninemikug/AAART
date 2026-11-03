#pragma once

#include <atomic>
#include <string>

namespace art {
namespace liveparam {

class LiveParamServer {
public:
    static LiveParamServer &getInstance();

    bool start();
    void stop();

    bool isRunning() const { return running_.load(std::memory_order_acquire); }
    const std::string &getSocketPath() const { return socketPath_; }

private:
    LiveParamServer();
    ~LiveParamServer();

    std::atomic<bool> running_{false};
    std::string socketPath_;
    int serverFd_ = -1;
    void *serverThread_ = nullptr;
};

} // namespace liveparam
} // namespace art
