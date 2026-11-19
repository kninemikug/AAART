#include "liveparamtrace.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>

namespace art {
namespace liveparam {

std::atomic<bool> LiveParamTrace::enabled_{false};

LiveParamTrace &LiveParamTrace::getInstance()
{
    static LiveParamTrace *instance = new LiveParamTrace();
    return *instance;
}

LiveParamTrace::LiveParamTrace()
{
    const char *path = std::getenv("ART_LIVE_PARAM_TRACE");
    if (path && *path) {
        tracePath_ = path;
        enabled_.store(true, std::memory_order_release);
    }
}

LiveParamTrace::~LiveParamTrace()
{
    flush(true);
}

uint64_t LiveParamTrace::allocateCmdId()
{
    return nextCmdId_.fetch_add(1, std::memory_order_relaxed) + 1;
}

std::string LiveParamTrace::escapeJsonString(const std::string &input)
{
    std::string out;
    out.reserve(input.size() + 8);
    for (unsigned char c : input) {
        switch (c) {
        case '"':
            out += "\\\"";
            break;
        case '\\':
            out += "\\\\";
            break;
        case '\b':
            out += "\\b";
            break;
        case '\f':
            out += "\\f";
            break;
        case '\n':
            out += "\\n";
            break;
        case '\r':
            out += "\\r";
            break;
        case '\t':
            out += "\\t";
            break;
        default:
            if (c < 0x20) {
                char buf[7];
                std::snprintf(buf, sizeof(buf), "\\u%04x",
                              static_cast<unsigned int>(c));
                out += buf;
            } else {
                out += static_cast<char>(c);
            }
            break;
        }
    }
    return out;
}

void LiveParamTrace::ensureEnabledLocked()
{
    if (!enabled_.load(std::memory_order_acquire)) {
        const char *path = std::getenv("ART_LIVE_PARAM_TRACE");
        if (path && *path) {
            tracePath_ = path;
            enabled_.store(true, std::memory_order_release);
        }
    } else if (tracePath_.empty()) {
        const char *path = std::getenv("ART_LIVE_PARAM_TRACE");
        if (path && *path) {
            tracePath_ = path;
        }
    }
}

void LiveParamTrace::pruneCommandMetaLocked(uint64_t nowNs)
{
    if (cmdMeta_.size() < kMaxCommandMeta) {
        return;
    }
    constexpr uint64_t kStaleNs = 5000000000ULL;
    for (auto it = cmdMeta_.begin(); it != cmdMeta_.end();) {
        if (it->second.finalized ||
            (nowNs > it->second.createdNs &&
             (nowNs - it->second.createdNs) > kStaleNs)) {
            it = cmdMeta_.erase(it);
        } else {
            ++it;
        }
        if (cmdMeta_.size() <= kMaxCommandMeta / 2) {
            return;
        }
    }
    while (cmdMeta_.size() >= kMaxCommandMeta && !cmdMeta_.empty()) {
        cmdMeta_.erase(cmdMeta_.begin());
    }
}

void LiveParamTrace::appendRecordLocked(TraceRecord &&r)
{
    if (records_.size() >= kMaxRecords) {
        dropCount_.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    records_.push_back(std::move(r));
    bufferedApprox_.store(records_.size(), std::memory_order_relaxed);
    recordedCount_.fetch_add(1, std::memory_order_relaxed);
}

void LiveParamTrace::record(const char *event, uint64_t cmdId,
                            const char *requestId, uint64_t generation,
                            int64_t editRev, int64_t viewRev, int changeFlags,
                            const char *detail, const char *sessionId,
                            const char *editorId)
{
    if (!enabled_.load(std::memory_order_relaxed)) {
        const char *path = std::getenv("ART_LIVE_PARAM_TRACE");
        if (path && *path) {
            std::lock_guard<std::mutex> lock(mutex_);
            ensureEnabledLocked();
        } else {
            return;
        }
    }

    const uint64_t now = static_cast<uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    std::lock_guard<std::mutex> lock(mutex_);
    if (!enabled_.load(std::memory_order_acquire)) {
        return;
    }

    TraceRecord r;
    r.event = event ? event : "";
    r.timestampNs = now;
    r.cmdId = cmdId;
    if (requestId && *requestId) {
        r.requestId = requestId;
    }
    if (sessionId && *sessionId) {
        r.sessionId = sessionId;
    }
    if (editorId && *editorId) {
        r.editorId = editorId;
    }

    if (cmdId) {
        auto it = cmdMeta_.find(cmdId);
        if (it != cmdMeta_.end()) {
            if (r.requestId.empty()) {
                r.requestId = it->second.requestId;
            }
            if (r.sessionId.empty()) {
                r.sessionId = it->second.sessionId;
            }
            if (r.editorId.empty()) {
                r.editorId = it->second.editorId;
            }
            if (r.event == "SS" || r.event == "SR" || r.event == "REPLAY") {
                it->second.finalized = true;
            }
        } else if (!r.sessionId.empty() || !r.requestId.empty() ||
                   !r.editorId.empty()) {
            pruneCommandMetaLocked(now);
            CommandMeta meta;
            meta.requestId = r.requestId;
            meta.sessionId = r.sessionId;
            meta.editorId = r.editorId;
            meta.createdNs = now;
            meta.finalized =
                (r.event == "SS" || r.event == "SR" || r.event == "REPLAY");
            cmdMeta_.emplace(cmdId, std::move(meta));
        }
    }

    r.generation = generation;
    r.editRevision = editRev;
    r.viewRevision = viewRev;
    r.changeFlags = changeFlags;
    if (detail && *detail) {
        r.detail = detail;
    }

    appendRecordLocked(std::move(r));
}

void LiveParamTrace::bindCommand(uint64_t cmdId, const char *requestId,
                                 const char *sessionId, const char *editorId)
{
    if (!enabled_.load(std::memory_order_relaxed)) {
        const char *path = std::getenv("ART_LIVE_PARAM_TRACE");
        if (path && *path) {
            std::lock_guard<std::mutex> lock(mutex_);
            ensureEnabledLocked();
        } else {
            return;
        }
    }
    if (!cmdId) {
        return;
    }

    const uint64_t now = static_cast<uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    std::lock_guard<std::mutex> lock(mutex_);
    if (!enabled_.load(std::memory_order_acquire)) {
        return;
    }
    pruneCommandMetaLocked(now);
    auto &meta = cmdMeta_[cmdId];
    if (meta.createdNs == 0) {
        meta.createdNs = now;
    }
    if (requestId && *requestId) {
        meta.requestId = requestId;
    }
    if (sessionId && *sessionId) {
        meta.sessionId = sessionId;
    }
    if (editorId && *editorId) {
        meta.editorId = editorId;
    }
}

void LiveParamTrace::finishUnboundCommand(uint64_t cmdId, const char *sessionId,
                                          const char *reason)
{
    if (!enabled_.load(std::memory_order_relaxed) || !cmdId) {
        return;
    }
    const uint64_t now = static_cast<uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    std::lock_guard<std::mutex> lock(mutex_);
    if (!enabled_.load(std::memory_order_acquire)) {
        return;
    }
    pruneCommandMetaLocked(now);
    auto &meta = cmdMeta_[cmdId];
    if (meta.createdNs == 0) {
        meta.createdNs = now;
    }
    if (sessionId && *sessionId && meta.sessionId.empty()) {
        meta.sessionId = sessionId;
    }
    meta.finalized = true;

    if (reason && *reason) {
        TraceRecord r;
        r.event = std::strcmp(reason, "QUEUE_FULL") == 0 ? "REJECT" : "CANCEL";
        r.timestampNs = now;
        r.cmdId = cmdId;
        r.requestId = meta.requestId;
        r.sessionId = meta.sessionId;
        r.editorId = meta.editorId;
        r.detail = reason;
        appendRecordLocked(std::move(r));
    }
}

std::string LiveParamTrace::getRequestId(uint64_t cmdId) const
{
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = cmdMeta_.find(cmdId);
    return it != cmdMeta_.end() ? it->second.requestId : "";
}

size_t LiveParamTrace::getCommandMetaSize() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return cmdMeta_.size();
}

std::vector<TraceRecord> LiveParamTrace::getRecordsSnapshot() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return records_;
}

void LiveParamTrace::flushIfNeeded(size_t threshold)
{
    if (!enabled_.load(std::memory_order_acquire)) {
        return;
    }
    if (bufferedApprox_.load(std::memory_order_relaxed) >= threshold) {
        flush(false);
    }
}

void LiveParamTrace::flush(bool force)
{
    std::vector<TraceRecord> toWrite;
    std::string path;
    size_t drops = 0;
    size_t writeErrs = 0;

    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (tracePath_.empty()) {
            const char *envPath = std::getenv("ART_LIVE_PARAM_TRACE");
            if (envPath && *envPath) {
                tracePath_ = envPath;
            }
        }
        if (tracePath_.empty() || records_.empty()) {
            return;
        }
        path = tracePath_;
        const uint64_t now = static_cast<uint64_t>(
            std::chrono::steady_clock::now().time_since_epoch().count());
        constexpr uint64_t kUnboundHoldNs = 5000000000ULL;

        std::vector<TraceRecord> deferred;
        toWrite.reserve(records_.size());
        for (auto &r : records_) {
            if (r.cmdId) {
                auto it = cmdMeta_.find(r.cmdId);
                if (it != cmdMeta_.end()) {
                    if (r.requestId.empty()) {
                        r.requestId = it->second.requestId;
                    }
                    if (r.sessionId.empty()) {
                        r.sessionId = it->second.sessionId;
                    }
                    if (r.editorId.empty()) {
                        r.editorId = it->second.editorId;
                    }
                    if (!force && r.requestId.empty() && !it->second.finalized &&
                        !(now > it->second.createdNs &&
                          (now - it->second.createdNs) > kUnboundHoldNs)) {
                        deferred.push_back(std::move(r));
                        continue;
                    }
                } else if (!force && r.requestId.empty()) {
                    deferred.push_back(std::move(r));
                    continue;
                }
            }
            toWrite.push_back(std::move(r));
        }
        records_ = std::move(deferred);
        bufferedApprox_.store(records_.size(), std::memory_order_relaxed);
        pruneCommandMetaLocked(now);
        drops = dropCount_.load(std::memory_order_relaxed);
        writeErrs = writeErrorCount_.load(std::memory_order_relaxed);
    }

    if (toWrite.empty()) {
        return;
    }

    std::ostringstream buffer;
    for (const auto &r : toWrite) {
        buffer << "{\"event\":\"" << escapeJsonString(r.event) << "\""
               << ",\"timestamp_ns\":" << r.timestampNs;
        if (r.cmdId) {
            buffer << ",\"cmdId\":" << r.cmdId;
        }
        if (!r.requestId.empty()) {
            buffer << ",\"requestId\":\"" << escapeJsonString(r.requestId)
                   << "\"";
        }
        if (!r.sessionId.empty()) {
            buffer << ",\"sessionId\":\"" << escapeJsonString(r.sessionId)
                   << "\"";
        }
        if (!r.editorId.empty()) {
            buffer << ",\"editorId\":\"" << escapeJsonString(r.editorId)
                   << "\"";
        }
        if (r.generation) {
            buffer << ",\"generation\":" << r.generation;
        }
        if (r.editRevision >= 0) {
            buffer << ",\"editRev\":" << r.editRevision;
        }
        if (r.viewRevision >= 0) {
            buffer << ",\"viewRev\":" << r.viewRevision;
        }
        if (r.changeFlags) {
            buffer << ",\"changeFlags\":" << r.changeFlags;
        }
        if (!r.detail.empty()) {
            buffer << ",\"detail\":\"" << escapeJsonString(r.detail) << "\"";
        }
        if (drops > 0) {
            buffer << ",\"drops\":" << drops;
        }
        if (writeErrs > 0) {
            buffer << ",\"writeErrors\":" << writeErrs;
        }
        buffer << "}\n";
    }

    const std::string payload = buffer.str();
    std::lock_guard<std::mutex> flock(fileMutex_);
    std::ofstream out(path, std::ios::app);
    if (!out.is_open()) {
        writeErrorCount_.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    out.write(payload.data(), static_cast<std::streamsize>(payload.size()));
    out.flush();
    if (!out.good()) {
        writeErrorCount_.fetch_add(1, std::memory_order_relaxed);
    }
}

void LiveParamTrace::clear()
{
    std::lock_guard<std::mutex> lock(mutex_);
    records_.clear();
    bufferedApprox_.store(0, std::memory_order_relaxed);
    cmdMeta_.clear();
    recordedCount_.store(0, std::memory_order_relaxed);
    dropCount_.store(0, std::memory_order_relaxed);
    writeErrorCount_.store(0, std::memory_order_relaxed);
    const char *path = std::getenv("ART_LIVE_PARAM_TRACE");
    if (path && *path) {
        tracePath_ = path;
        enabled_.store(true, std::memory_order_release);
    } else {
        tracePath_.clear();
        enabled_.store(false, std::memory_order_release);
    }
}

} // namespace liveparam
} // namespace art
