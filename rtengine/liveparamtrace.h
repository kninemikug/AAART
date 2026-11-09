#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <map>
#include <mutex>
#include <string>
#include <vector>

namespace art {
namespace liveparam {

struct TraceRecord {
    std::string event;
    uint64_t timestampNs = 0;
    uint64_t cmdId = 0;
    std::string requestId;
    std::string sessionId;
    std::string editorId;
    uint64_t generation = 0;
    int64_t editRevision = -1;
    int64_t viewRevision = -1;
    int changeFlags = 0;
    std::string detail;
};

class LiveParamTrace {
public:
    static LiveParamTrace &getInstance();

    static bool isEnabled()
    {
        return enabled_.load(std::memory_order_relaxed);
    }

    void record(const char *event, uint64_t cmdId = 0,
                const char *requestId = nullptr,
                uint64_t generation = 0, int64_t editRev = -1,
                int64_t viewRev = -1, int changeFlags = 0,
                const char *detail = nullptr);

    void bindCommand(uint64_t cmdId, const char *requestId,
                     const char *sessionId = nullptr,
                     const char *editorId = nullptr);

    std::string getRequestId(uint64_t cmdId) const;

    void flush();
    void clear();

    size_t getDropCount() const { return dropCount_.load(std::memory_order_relaxed); }
    size_t getRecordedCount() const { return recordedCount_.load(std::memory_order_relaxed); }
    std::vector<TraceRecord> getRecordsSnapshot() const;

private:
    LiveParamTrace();
    ~LiveParamTrace();

    void flushInternalLocked(bool force = false);

    static std::atomic<bool> enabled_;
    std::string tracePath_;
    std::atomic<size_t> recordedCount_{0};
    std::atomic<size_t> dropCount_{0};
    static constexpr size_t kMaxRecords = 65536;

    mutable std::mutex mutex_;
    std::vector<TraceRecord> records_;
    std::map<uint64_t, std::string> cmdToRequest_;
    std::map<uint64_t, std::pair<std::string, std::string>> cmdToSessionEditor_;
    std::string defaultSessionId_;
    std::string defaultEditorId_;
};

} // namespace liveparam
} // namespace art
