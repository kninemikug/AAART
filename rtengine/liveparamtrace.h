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

struct CommandMeta {
    std::string requestId;
    std::string sessionId;
    std::string editorId;
    uint64_t createdNs = 0;
    bool finalized = false;
};

class LiveParamTrace {
public:
    static LiveParamTrace &getInstance();

    static bool isEnabled()
    {
        return enabled_.load(std::memory_order_acquire);
    }

    uint64_t allocateCmdId();

    void record(const char *event, uint64_t cmdId = 0,
                const char *requestId = nullptr,
                uint64_t generation = 0, int64_t editRev = -1,
                int64_t viewRev = -1, int changeFlags = 0,
                const char *detail = nullptr,
                const char *sessionId = nullptr,
                const char *editorId = nullptr);

    void bindCommand(uint64_t cmdId, const char *requestId,
                     const char *sessionId = nullptr,
                     const char *editorId = nullptr);

    void finishUnboundCommand(uint64_t cmdId,
                              const char *sessionId = nullptr,
                              const char *reason = nullptr);

    std::string getRequestId(uint64_t cmdId) const;

    void flush(bool force = true);
    void flushIfNeeded(size_t threshold = 128);
    void clear();

    size_t getDropCount() const
    {
        return dropCount_.load(std::memory_order_relaxed);
    }
    size_t getWriteErrorCount() const
    {
        return writeErrorCount_.load(std::memory_order_relaxed);
    }
    size_t getRecordedCount() const
    {
        return recordedCount_.load(std::memory_order_relaxed);
    }
    size_t getCommandMetaSize() const;
    std::vector<TraceRecord> getRecordsSnapshot() const;

    static std::string escapeJsonString(const std::string &input);

private:
    LiveParamTrace();
    ~LiveParamTrace();

    void ensureEnabledLocked();
    void appendRecordLocked(TraceRecord &&r);
    void pruneCommandMetaLocked(uint64_t nowNs);

    static std::atomic<bool> enabled_;
    std::string tracePath_;
    std::atomic<uint64_t> nextCmdId_{0};
    std::atomic<size_t> recordedCount_{0};
    std::atomic<size_t> dropCount_{0};
    std::atomic<size_t> writeErrorCount_{0};
    std::atomic<size_t> bufferedApprox_{0};
    static constexpr size_t kMaxRecords = 65536;
    static constexpr size_t kMaxCommandMeta = 4096;

    mutable std::mutex mutex_;
    std::mutex fileMutex_;
    std::vector<TraceRecord> records_;
    std::map<uint64_t, CommandMeta> cmdMeta_;
};

} // namespace liveparam
} // namespace art
