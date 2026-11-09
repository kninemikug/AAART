#include "liveparamtrace.h"

#include <cstdlib>
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
    flush();
}

void LiveParamTrace::record(const char *event, uint64_t cmdId,
                            const char *requestId,
                            uint64_t generation, int64_t editRev,
                            int64_t viewRev, int changeFlags,
                            const char *detail)
{
    if (!enabled_.load(std::memory_order_relaxed)) {
        const char *path = std::getenv("ART_LIVE_PARAM_TRACE");
        if (path && *path) {
            std::lock_guard<std::mutex> lock(mutex_);
            tracePath_ = path;
            enabled_.store(true, std::memory_order_release);
        } else {
            return;
        }
    }

    const auto now = std::chrono::steady_clock::now().time_since_epoch().count();
    std::lock_guard<std::mutex> lock(mutex_);
    if (records_.size() >= kMaxRecords) {
        dropCount_.fetch_add(1, std::memory_order_relaxed);
        return;
    }

    TraceRecord r;
    r.event = event ? event : "";
    r.timestampNs = static_cast<uint64_t>(now);
    r.cmdId = cmdId;
    if (requestId && *requestId) {
        r.requestId = requestId;
    } else if (cmdId) {
        auto it = cmdToRequest_.find(cmdId);
        if (it != cmdToRequest_.end()) {
            r.requestId = it->second;
        }
    }
    if (cmdId) {
        auto se = cmdToSessionEditor_.find(cmdId);
        if (se != cmdToSessionEditor_.end()) {
            r.sessionId = se->second.first;
            r.editorId = se->second.second;
        }
    }
    if (r.sessionId.empty()) {
        r.sessionId = defaultSessionId_;
    }
    if (r.editorId.empty()) {
        r.editorId = defaultEditorId_;
    }
    r.generation = generation;
    r.editRevision = editRev;
    r.viewRevision = viewRev;
    r.changeFlags = changeFlags;
    if (detail && *detail) {
        r.detail = detail;
    }
    records_.push_back(std::move(r));
    recordedCount_.fetch_add(1, std::memory_order_relaxed);
    if (event && (std::strcmp(event, "SS") == 0 || std::strcmp(event, "SR") == 0)) {
        flushInternalLocked();
    }
}

void LiveParamTrace::bindCommand(uint64_t cmdId, const char *requestId,
                                 const char *sessionId,
                                 const char *editorId)
{
    if (!enabled_.load(std::memory_order_relaxed)) {
        const char *path = std::getenv("ART_LIVE_PARAM_TRACE");
        if (path && *path) {
            std::lock_guard<std::mutex> lock(mutex_);
            tracePath_ = path;
            enabled_.store(true, std::memory_order_release);
        } else {
            return;
        }
    }
    if (!cmdId) {
        return;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (requestId && *requestId) {
        cmdToRequest_[cmdId] = requestId;
    }
    if (sessionId && *sessionId) {
        cmdToSessionEditor_[cmdId].first = sessionId;
        defaultSessionId_ = sessionId;
    }
    if (editorId && *editorId) {
        cmdToSessionEditor_[cmdId].second = editorId;
        defaultEditorId_ = editorId;
    }
}

std::string LiveParamTrace::getRequestId(uint64_t cmdId) const
{
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = cmdToRequest_.find(cmdId);
    return it != cmdToRequest_.end() ? it->second : "";
}

std::vector<TraceRecord> LiveParamTrace::getRecordsSnapshot() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return records_;
}

void LiveParamTrace::flushInternalLocked(bool force)
{
    if (tracePath_.empty()) {
        const char *envPath = std::getenv("ART_LIVE_PARAM_TRACE");
        if (envPath && *envPath) {
            tracePath_ = envPath;
        }
    }
    if (tracePath_.empty() || records_.empty()) {
        return;
    }

    std::ofstream out(tracePath_, std::ios::app);
    if (!out.is_open()) {
        return;
    }

    std::vector<TraceRecord> deferred;
    for (const auto &r : records_) {
        std::string reqId = r.requestId;
        std::string sessId = r.sessionId;
        std::string edId = r.editorId;
        if (reqId.empty() && r.cmdId) {
            auto it = cmdToRequest_.find(r.cmdId);
            if (it != cmdToRequest_.end()) {
                reqId = it->second;
            } else if (!force) {
                deferred.push_back(r);
                continue;
            }
        }
        if (sessId.empty() && r.cmdId) {
            auto it = cmdToSessionEditor_.find(r.cmdId);
            if (it != cmdToSessionEditor_.end()) {
                sessId = it->second.first;
            }
        }
        if (edId.empty() && r.cmdId) {
            auto it = cmdToSessionEditor_.find(r.cmdId);
            if (it != cmdToSessionEditor_.end()) {
                edId = it->second.second;
            }
        }
        out << "{\"event\":\"" << r.event << "\""
            << ",\"timestamp_ns\":" << r.timestampNs;
        if (r.cmdId) {
            out << ",\"cmdId\":" << r.cmdId;
        }
        if (!reqId.empty()) {
            out << ",\"requestId\":\"" << reqId << "\"";
        }
        if (!sessId.empty()) {
            out << ",\"sessionId\":\"" << sessId << "\"";
        }
        if (!edId.empty()) {
            out << ",\"editorId\":\"" << edId << "\"";
        }
        if (r.generation) {
            out << ",\"generation\":" << r.generation;
        }
        if (r.editRevision >= 0) {
            out << ",\"editRev\":" << r.editRevision;
        }
        if (r.viewRevision >= 0) {
            out << ",\"viewRev\":" << r.viewRevision;
        }
        if (r.changeFlags) {
            out << ",\"changeFlags\":" << r.changeFlags;
        }
        if (!r.detail.empty()) {
            out << ",\"detail\":\"" << r.detail << "\"";
        }
        out << "}\n";
    }
    out.flush();
    records_ = std::move(deferred);
}

void LiveParamTrace::flush()
{
    std::lock_guard<std::mutex> lock(mutex_);
    flushInternalLocked(true);
}

void LiveParamTrace::clear()
{
    std::lock_guard<std::mutex> lock(mutex_);
    records_.clear();
    cmdToRequest_.clear();
    cmdToSessionEditor_.clear();
    recordedCount_.store(0, std::memory_order_relaxed);
    dropCount_.store(0, std::memory_order_relaxed);
}

} // namespace liveparam
} // namespace art
