#include "liveparamcontroller.h"
#include "editorpanel.h"
#include "toolpanelcoord.h"
#include "ppversion.h"
#include "../rtengine/cJSON.h"
#include "../rtengine/rtengine.h"

#include <cmath>
#include <iomanip>
#include <random>
#include <set>
#include <sstream>

namespace art {
namespace liveparam {

namespace {

std::string generateHexId(const std::string &prefix, size_t hexChars)
{
    static std::mt19937_64 rng(std::random_device{}());
    std::uniform_int_distribution<uint64_t> dist;
    uint64_t val = dist(rng);
    std::ostringstream oss;
    oss << prefix << std::hex << std::setfill('0') << std::setw(hexChars)
        << (val & ((1ULL << (hexChars * 4)) - 1));
    return oss.str();
}

bool hasDuplicateKeys(const cJSON *node)
{
    if (!node) {
        return false;
    }
    if (cJSON_IsObject(node)) {
        std::set<std::string> keys;
        for (const cJSON *child = node->child; child != nullptr;
             child = child->next) {
            if (child->string) {
                if (keys.find(child->string) != keys.end()) {
                    return true;
                }
                keys.insert(child->string);
            }
            if (hasDuplicateKeys(child)) {
                return true;
            }
        }
    } else if (cJSON_IsArray(node)) {
        for (const cJSON *child = node->child; child != nullptr;
             child = child->next) {
            if (hasDuplicateKeys(child)) {
                return true;
            }
        }
    }
    return false;
}

std::string makeErrorResponse(int protocolVersion, const std::string &requestId,
                              const std::string &sessionId,
                              const std::string &editorId,
                              const std::string &code,
                              const std::string &message,
                              const std::string &detailsJson, bool retryable)
{
    std::ostringstream oss;
    oss << "{\"protocolVersion\":" << protocolVersion << ",\"requestId\":";
    if (requestId.empty()) {
        oss << "null";
    } else {
        oss << "\"" << requestId << "\"";
    }
    oss << ",\"sessionId\":\"" << sessionId << "\"";
    oss << ",\"editorId\":\"" << editorId << "\"";
    oss << ",\"status\":\"ERROR\",\"error\":{";
    oss << "\"code\":\"" << code << "\",\"message\":\"" << message << "\",";
    oss << "\"details\":" << (detailsJson.empty() ? "{}" : detailsJson) << ",";
    oss << "\"retryable\":" << (retryable ? "true" : "false");
    oss << "}}";
    return oss.str();
}

} // namespace

LiveParamController &LiveParamController::getInstance()
{
    static LiveParamController instance;
    return instance;
}

LiveParamController::LiveParamController()
{
    sessionId_ = generateHexId("run-", 8);
    enabled_.store(false, std::memory_order_release);
}

LiveParamController::~LiveParamController()
{
    cleanup();
}

void LiveParamController::recordGuiAccess()
{
    const auto cur = std::this_thread::get_id();
    if (!hasGuiThreadId_) {
        guiThreadId_ = cur;
        hasGuiThreadId_ = true;
    } else if (cur != guiThreadId_) {
        nonGuiAccessCount_.fetch_add(1, std::memory_order_relaxed);
    }
}

void LiveParamController::init()
{
    guiThreadId_ = std::this_thread::get_id();
    hasGuiThreadId_ = true;
    nonGuiAccessCount_.store(0, std::memory_order_release);
    sessionId_ = generateHexId("run-", 8);
    editors_.clear();
    panelToId_.clear();
    nextEditorIndex_ = 1;
    enabled_.store(true, std::memory_order_release);
}

void LiveParamController::cleanup()
{
    enabled_.store(false, std::memory_order_release);
    for (auto &kv : panelToId_) {
        if (kv.first) {
            kv.first->setEditorId("");
        }
    }
    editors_.clear();
    panelToId_.clear();
}

std::string LiveParamController::registerEditor(EditorPanel *panel,
                                                const std::string &filename)
{
    if (!isEnabled() || !panel) {
        if (panel) {
            panel->setEditorId("");
        }
        return "";
    }
    recordGuiAccess();

    auto it = panelToId_.find(panel);
    if (it != panelToId_.end()) {
        unregisterEditor(panel);
    }

    std::string id = generateHexId("editor-", 8);
    panel->setEditorId(id);

    EditorState st;
    st.panel = panel;
    st.editorId = id;
    st.filename = filename;
    st.currentRevision = 0;
    st.currentViewRevision = 0;
    st.renderedRevision = -1;
    st.renderedViewRevision = -1;

    editors_[id] = st;
    panelToId_[panel] = id;
    return id;
}

void LiveParamController::unregisterEditor(EditorPanel *panel)
{
    if (!panel) {
        return;
    }
    panel->setEditorId("");
    if (editors_.empty() && panelToId_.empty()) {
        return;
    }
    recordGuiAccess();
    auto it = panelToId_.find(panel);
    if (it != panelToId_.end()) {
        std::string id = it->second;
        editors_.erase(id);
        panelToId_.erase(it);
    }
}

void LiveParamController::onEditorParamChanged(EditorPanel *panel)
{
    if (!isEnabled() || !panel) {
        return;
    }
    recordGuiAccess();
    auto it = panelToId_.find(panel);
    if (it == panelToId_.end()) {
        return;
    }
    EditorState &st = editors_[it->second];
    st.currentRevision++;

    if (st.hasInFlightMutation) {
        st.lastMutation.previewStatus = "SUPERSEDED";
        auto cit = st.mutationCache.find(st.inFlightRequestId);
        if (cit != st.mutationCache.end()) {
            cit->second.previewStatus = "SUPERSEDED";
            cit->second.completedTime = std::chrono::steady_clock::now();
            cit->second.isCompleted = true;
        }
        st.hasInFlightMutation = false;
    }
}

void LiveParamController::onEditorViewChanged(EditorPanel *panel)
{
    if (!isEnabled() || !panel) {
        return;
    }
    recordGuiAccess();
    auto it = panelToId_.find(panel);
    if (it == panelToId_.end()) {
        return;
    }
    EditorState &st = editors_[it->second];
    st.currentViewRevision++;
}

void LiveParamController::onEditorSizeChanged(const std::string &sessionId,
                                              const std::string &editorId,
                                              EditorPanel *panel)
{
    if (!isEnabled() || !panel || sessionId.empty() || editorId.empty()) {
        return;
    }
    recordGuiAccess();
    if (sessionId != sessionId_) {
        return;
    }
    auto it = editors_.find(editorId);
    if (it == editors_.end() || it->second.panel != panel) {
        return;
    }
    it->second.currentViewRevision++;
}

void LiveParamController::onPreviewReady(EditorPanel *panel, int64_t editRev,
                                         int64_t viewRev)
{
    if (!isEnabled() || !panel) {
        return;
    }
    recordGuiAccess();
    auto it = panelToId_.find(panel);
    if (it == panelToId_.end()) {
        return;
    }
    EditorState &st = editors_[it->second];
    st.lastPreviewReadyEditRev = editRev;
    st.lastPreviewReadyViewRev = viewRev;

    if (st.lastCropReadyEditRev == editRev &&
        st.lastCropReadyViewRev == viewRev) {
        st.renderedRevision = editRev;
        st.renderedViewRevision = viewRev;

        if (st.hasInFlightMutation && st.inFlightAppliedRev == editRev &&
            st.inFlightAppliedViewRev == viewRev) {
            st.lastMutation.previewStatus = "READY";
            auto cit = st.mutationCache.find(st.inFlightRequestId);
            if (cit != st.mutationCache.end()) {
                cit->second.previewStatus = "READY";
                cit->second.completedTime = std::chrono::steady_clock::now();
                cit->second.isCompleted = true;
            }
            st.hasInFlightMutation = false;
        }
    }
}

void LiveParamController::onCropReady(EditorPanel *panel, int64_t editRev,
                                      int64_t viewRev)
{
    if (!isEnabled() || !panel) {
        return;
    }
    recordGuiAccess();
    auto it = panelToId_.find(panel);
    if (it == panelToId_.end()) {
        return;
    }
    EditorState &st = editors_[it->second];
    st.lastCropReadyEditRev = editRev;
    st.lastCropReadyViewRev = viewRev;

    if (st.lastPreviewReadyEditRev == editRev &&
        st.lastPreviewReadyViewRev == viewRev) {
        st.renderedRevision = editRev;
        st.renderedViewRevision = viewRev;

        if (st.hasInFlightMutation && st.inFlightAppliedRev == editRev &&
            st.inFlightAppliedViewRev == viewRev) {
            st.lastMutation.previewStatus = "READY";
            auto cit = st.mutationCache.find(st.inFlightRequestId);
            if (cit != st.mutationCache.end()) {
                cit->second.previewStatus = "READY";
                cit->second.completedTime = std::chrono::steady_clock::now();
                cit->second.isCompleted = true;
            }
            st.hasInFlightMutation = false;
        }
    }
}

void LiveParamController::onRenderFailed(EditorPanel *panel,
                                         const std::string &err)
{
    if (!isEnabled() || !panel) {
        return;
    }
    recordGuiAccess();
    auto it = panelToId_.find(panel);
    if (it == panelToId_.end()) {
        return;
    }
    onRenderFailed(sessionId_, it->second, panel, err);
}

void LiveParamController::onRenderFailed(const std::string &sessionId,
                                         const std::string &editorId,
                                         EditorPanel *panel,
                                         const std::string &err)
{
    (void)err;
    if (!isEnabled() || !panel || sessionId.empty() || editorId.empty()) {
        return;
    }
    recordGuiAccess();
    if (sessionId != sessionId_) {
        return;
    }
    auto it = editors_.find(editorId);
    if (it == editors_.end() || it->second.panel != panel) {
        return;
    }
    EditorState &st = it->second;
    if (st.hasInFlightMutation) {
        st.lastMutation.previewStatus = "FAILED";
        auto cit = st.mutationCache.find(st.inFlightRequestId);
        if (cit != st.mutationCache.end()) {
            cit->second.previewStatus = "FAILED";
            cit->second.completedTime = std::chrono::steady_clock::now();
            cit->second.isCompleted = true;
        }
        st.hasInFlightMutation = false;
    }
}

void LiveParamController::pruneExpiredCache(EditorState &st)
{
    auto now = std::chrono::steady_clock::now();
    for (auto it = st.mutationCache.begin(); it != st.mutationCache.end();) {
        if (it->second.isCompleted) {
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                               now - it->second.completedTime)
                               .count();
            if (elapsed >= 300) { // 5 minutes
                it = st.mutationCache.erase(it);
                continue;
            }
        }
        ++it;
    }
}

std::string LiveParamController::handleCommand(const std::string &jsonRequest)
{
    recordGuiAccess();
    if (jsonRequest.size() > 65536) {
        return makeErrorResponse(1, "", sessionId_, "", "INVALID_REQUEST",
                                 "Frame exceeds 64 KiB", "{}", false);
    }

    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> root(
        cJSON_Parse(jsonRequest.c_str()), cJSON_Delete);

    if (!root || !cJSON_IsObject(root.get())) {
        return makeErrorResponse(1, "", sessionId_, "", "INVALID_REQUEST",
                                 "Malformed JSON object", "{}", false);
    }

    if (hasDuplicateKeys(root.get())) {
        return makeErrorResponse(1, "", sessionId_, "", "INVALID_REQUEST",
                                 "Duplicate JSON keys rejected", "{}", false);
    }

    cJSON *protoItem =
        cJSON_GetObjectItemCaseSensitive(root.get(), "protocolVersion");
    if (!protoItem || !cJSON_IsNumber(protoItem)) {
        return makeErrorResponse(1, "", sessionId_, "", "INVALID_REQUEST",
                                 "Missing or non-numeric protocolVersion", "{}",
                                 false);
    }
    if (protoItem->valueint != 1) {
        return makeErrorResponse(protoItem->valueint, "", sessionId_, "",
                                 "UNSUPPORTED_VERSION",
                                 "Protocol version must be 1", "{}", false);
    }
    int protocolVersion = protoItem->valueint;

    cJSON *reqIdItem = cJSON_GetObjectItemCaseSensitive(root.get(), "requestId");
    if (!reqIdItem || !cJSON_IsString(reqIdItem) || !reqIdItem->valuestring) {
        return makeErrorResponse(protocolVersion, "", sessionId_, "",
                                 "INVALID_REQUEST",
                                 "Missing or non-string requestId", "{}",
                                 false);
    }
    std::string requestId = reqIdItem->valuestring;
    if (requestId.empty() || requestId.size() > 128) {
        return makeErrorResponse(protocolVersion, "", sessionId_, "",
                                 "INVALID_REQUEST",
                                 "requestId must be 1..128 characters", "{}",
                                 false);
    }

    cJSON *opItem = cJSON_GetObjectItemCaseSensitive(root.get(), "op");
    if (!opItem || !cJSON_IsString(opItem) || !opItem->valuestring) {
        return makeErrorResponse(protocolVersion, requestId, sessionId_, "",
                                 "INVALID_REQUEST", "Missing or non-string op",
                                 "{}", false);
    }
    std::string op = opItem->valuestring;

    cJSON *sessItem = cJSON_GetObjectItemCaseSensitive(root.get(), "sessionId");
    std::string reqSessionId =
        (sessItem && cJSON_IsString(sessItem) && sessItem->valuestring)
            ? sessItem->valuestring
            : "";

    cJSON *edItem = cJSON_GetObjectItemCaseSensitive(root.get(), "editorId");
    std::string reqEditorId =
        (edItem && cJSON_IsString(edItem) && edItem->valuestring)
            ? edItem->valuestring
            : "";

    if (op == "get_state") {
        for (const cJSON *child = root->child; child != nullptr;
             child = child->next) {
            std::string key = child->string ? child->string : "";
            if (key != "protocolVersion" && key != "requestId" && key != "op" &&
                key != "sessionId" && key != "editorId" &&
                key != "mutationRequestId") {
                return makeErrorResponse(
                    protocolVersion, requestId, sessionId_, reqEditorId,
                    "INVALID_REQUEST", "Unknown key in get_state: " + key, "{}",
                    false);
            }
        }

        if (!reqSessionId.empty() && reqSessionId != sessionId_) {
            return makeErrorResponse(protocolVersion, requestId, sessionId_,
                                     reqEditorId, "SESSION_MISMATCH",
                                     "Session ID does not match running GUI",
                                     "{}", false);
        }

        if (reqEditorId.empty()) {
            std::ostringstream oss;
            oss << "{\"protocolVersion\":1,\"requestId\":\"" << requestId
                << "\",\"sessionId\":\"" << sessionId_
                << "\",\"status\":\"OK\",\"result\":{\"sessionId\":\""
                << sessionId_ << "\",\"editors\":[";
            bool first = true;
            for (const auto &pair : editors_) {
                if (!first) {
                    oss << ",";
                }
                first = false;
                oss << "{\"editorId\":\"" << pair.first << "\",\"name\":\""
                    << pair.second.filename << "\"}";
            }
            oss << "]}}";
            return oss.str();
        }

        auto it = editors_.find(reqEditorId);
        if (it == editors_.end()) {
            return makeErrorResponse(protocolVersion, requestId, sessionId_,
                                     reqEditorId, "EDITOR_NOT_FOUND",
                                     "Editor not found or closed", "{}", false);
        }
        EditorState &st = it->second;

        cJSON *mutReqItem =
            cJSON_GetObjectItemCaseSensitive(root.get(), "mutationRequestId");
        std::string mutationReqId =
            (mutReqItem && cJSON_IsString(mutReqItem) &&
             mutReqItem->valuestring)
                ? mutReqItem->valuestring
                : "";

        std::ostringstream oss;
        oss << "{\"protocolVersion\":1,\"requestId\":\"" << requestId
            << "\",\"sessionId\":\"" << sessionId_ << "\",\"editorId\":\""
            << reqEditorId << "\",\"status\":\"OK\",\"result\":{";
        oss << "\"revision\":" << st.currentRevision << ",";
        oss << "\"viewRevision\":" << st.currentViewRevision << ",";
        oss << "\"renderedRevision\":";
        if (st.renderedRevision >= 0) {
            oss << st.renderedRevision;
        } else {
            oss << "null";
        }
        oss << ",\"renderedViewRevision\":";
        if (st.renderedViewRevision >= 0) {
            oss << st.renderedViewRevision;
        } else {
            oss << "null";
        }
        oss << ",";

        if (!mutationReqId.empty()) {
            auto cit = st.mutationCache.find(mutationReqId);
            if (cit != st.mutationCache.end()) {
                oss << "\"lastMutation\":{\"requestId\":\""
                    << cit->second.requestId << "\",\"appliedRevision\":"
                    << cit->second.appliedRevision
                    << ",\"previewStatus\":\"" << cit->second.previewStatus
                    << "\"},\"mutationStatus\":\"" << cit->second.previewStatus
                    << "\"";
            } else {
                oss << "\"lastMutation\":null,\"mutationStatus\":\"UNKNOWN\"";
            }
        } else if (st.hasLastMutation) {
            oss << "\"lastMutation\":{\"requestId\":\""
                << st.lastMutation.requestId << "\",\"appliedRevision\":"
                << st.lastMutation.appliedRevision
                << ",\"previewStatus\":\"" << st.lastMutation.previewStatus
                << "\"}";
        } else {
            oss << "\"lastMutation\":null";
        }

        oss << "}}";
        return oss.str();
    }

    if (op == "set_param") {
        for (const cJSON *child = root->child; child != nullptr;
             child = child->next) {
            std::string key = child->string ? child->string : "";
            if (key != "protocolVersion" && key != "requestId" && key != "op" &&
                key != "sessionId" && key != "editorId" &&
                key != "baseRevision" && key != "params") {
                return makeErrorResponse(
                    protocolVersion, requestId, sessionId_, reqEditorId,
                    "INVALID_REQUEST", "Unknown key in set_param: " + key, "{}",
                    false);
            }
        }

        if (reqSessionId.empty() || reqSessionId != sessionId_) {
            return makeErrorResponse(protocolVersion, requestId, sessionId_,
                                     reqEditorId, "SESSION_MISMATCH",
                                     "Session ID does not match running GUI",
                                     "{}", false);
        }

        cJSON *baseRevItem =
            cJSON_GetObjectItemCaseSensitive(root.get(), "baseRevision");
        if (!baseRevItem || !cJSON_IsNumber(baseRevItem) ||
            baseRevItem->valueint < 0) {
            return makeErrorResponse(
                protocolVersion, requestId, sessionId_, reqEditorId,
                "INVALID_REQUEST", "Missing or invalid baseRevision", "{}",
                false);
        }
        int64_t baseRevision = baseRevItem->valueint;

        cJSON *paramsItem =
            cJSON_GetObjectItemCaseSensitive(root.get(), "params");
        if (!paramsItem || !cJSON_IsObject(paramsItem)) {
            return makeErrorResponse(protocolVersion, requestId, sessionId_,
                                     reqEditorId, "INVALID_REQUEST",
                                     "Missing or invalid params object", "{}",
                                     false);
        }

        for (const cJSON *child = paramsItem->child; child != nullptr;
             child = child->next) {
            std::string key = child->string ? child->string : "";
            if (key != "Exposure.Compensation") {
                return makeErrorResponse(
                    protocolVersion, requestId, sessionId_, reqEditorId,
                    "UNSUPPORTED_PARAM", "Unsupported param: " + key, "{}",
                    false);
            }
        }

        cJSON *expCompItem = cJSON_GetObjectItemCaseSensitive(
            paramsItem, "Exposure.Compensation");
        if (!expCompItem || !cJSON_IsNumber(expCompItem)) {
            return makeErrorResponse(protocolVersion, requestId, sessionId_,
                                     reqEditorId, "INVALID_VALUE",
                                     "Exposure.Compensation must be numeric",
                                     "{}", false);
        }
        double expComp = expCompItem->valuedouble;
        if (!std::isfinite(expComp) || expComp < -12.0 || expComp > 12.0) {
            return makeErrorResponse(
                protocolVersion, requestId, sessionId_, reqEditorId,
                "INVALID_VALUE",
                "Exposure.Compensation out of range [-12.0, 12.0]", "{}",
                false);
        }

        if (reqEditorId.empty()) {
            return makeErrorResponse(protocolVersion, requestId, sessionId_,
                                     reqEditorId, "EDITOR_NOT_FOUND",
                                     "editorId is required", "{}", false);
        }

        auto it = editors_.find(reqEditorId);
        if (it == editors_.end()) {
            return makeErrorResponse(protocolVersion, requestId, sessionId_,
                                     reqEditorId, "EDITOR_NOT_FOUND",
                                     "Editor not found or closed", "{}", false);
        }
        EditorState &st = it->second;

        auto cit = st.mutationCache.find(requestId);
        if (cit != st.mutationCache.end()) {
            if (cit->second.baseRevision == baseRevision &&
                std::fabs(cit->second.effectiveExpComp - expComp) < 1e-6) {
                std::ostringstream oss;
                oss << "{\"protocolVersion\":1,\"requestId\":\"" << requestId
                    << "\",\"sessionId\":\"" << sessionId_
                    << "\",\"editorId\":\"" << reqEditorId
                    << "\",\"status\":\"APPLIED\",\"result\":{";
                oss << "\"appliedRevision\":" << cit->second.appliedRevision
                    << ",";
                oss << "\"viewRevision\":" << cit->second.viewRevision << ",";
                oss << "\"effectiveParams\":{\"Exposure.Compensation\":"
                    << expComp << "},";
                oss << "\"previewStatus\":\"" << cit->second.previewStatus
                    << "\",";
                oss << "\"renderedRevision\":";
                if (st.renderedRevision >= 0) {
                    oss << st.renderedRevision;
                } else {
                    oss << "null";
                }
                oss << ",\"renderedViewRevision\":";
                if (st.renderedViewRevision >= 0) {
                    oss << st.renderedViewRevision;
                } else {
                    oss << "null";
                }
                oss << ",\"ppVersion\":" << PPVERSION;
                oss << "}}";
                return oss.str();
            } else {
                return makeErrorResponse(
                    protocolVersion, requestId, sessionId_, reqEditorId,
                    "REQUEST_ID_CONFLICT",
                    "requestId reused with different content", "{}", false);
            }
        }

        pruneExpiredCache(st);
        if (st.mutationCache.size() >= 1024) {
            return makeErrorResponse(
                protocolVersion, requestId, sessionId_, reqEditorId, "BUSY",
                "Mutation cache full", "{}", true);
        }

        if (st.panel->getIsProcessing()) {
            return makeErrorResponse(
                protocolVersion, requestId, sessionId_, reqEditorId, "BUSY",
                "Editor is currently initializing or closing", "{}", true);
        }

        auto ipc = st.panel->getImageProcessor();
        if (!ipc || ipc->hasTweakOperator()) {
            return makeErrorResponse(
                protocolVersion, requestId, sessionId_, reqEditorId, "BUSY",
                "Editor has active TweakOperator or processor busy", "{}", true);
        }

        if (st.hasInFlightMutation) {
            return makeErrorResponse(
                protocolVersion, requestId, sessionId_, reqEditorId, "BUSY",
                "Prior external mutation is pending preview", "{}", true);
        }

        auto tpc = st.panel->getToolPanelCoordinator();
        if (!tpc || !tpc->isExposureEnabled()) {
            return makeErrorResponse(
                protocolVersion, requestId, sessionId_, reqEditorId,
                "TOOL_DISABLED", "Exposure tool is disabled", "{}", false);
        }

        if (baseRevision != st.currentRevision) {
            std::ostringstream detailsOss;
            detailsOss << "{\"currentRevision\":" << st.currentRevision << "}";
            return makeErrorResponse(protocolVersion, requestId, sessionId_,
                                     reqEditorId, "REVISION_CONFLICT",
                                     "baseRevision does not match currentRevision",
                                     detailsOss.str(), false);
        }

        st.currentRevision++;
        int64_t appliedRev = st.currentRevision;
        int64_t viewRev = st.currentViewRevision;

        ipc->setNextRevisions(appliedRev, viewRev);

        if (!tpc->applyExternalExposure(expComp)) {
            return makeErrorResponse(
                protocolVersion, requestId, sessionId_, reqEditorId,
                "INTERNAL_ERROR", "Failed to apply exposure parameter", "{}",
                false);
        }

        MutationRecord rec;
        rec.requestId = requestId;
        rec.appliedRevision = appliedRev;
        rec.viewRevision = viewRev;
        rec.previewStatus = "PENDING";
        rec.effectiveExpComp = expComp;
        rec.baseRevision = baseRevision;
        rec.completedTime = std::chrono::steady_clock::now();
        rec.isCompleted = false;

        st.hasLastMutation = true;
        st.lastMutation = rec;
        st.hasInFlightMutation = true;
        st.inFlightRequestId = requestId;
        st.inFlightAppliedRev = appliedRev;
        st.inFlightAppliedViewRev = viewRev;
        st.mutationCache[requestId] = rec;

        std::ostringstream oss;
        oss << "{\"protocolVersion\":1,\"requestId\":\"" << requestId
            << "\",\"sessionId\":\"" << sessionId_ << "\",\"editorId\":\""
            << reqEditorId << "\",\"status\":\"APPLIED\",\"result\":{";
        oss << "\"appliedRevision\":" << appliedRev << ",";
        oss << "\"viewRevision\":" << viewRev << ",";
        oss << "\"effectiveParams\":{\"Exposure.Compensation\":" << expComp
            << "},";
        oss << "\"previewStatus\":\"PENDING\",";
        oss << "\"renderedRevision\":";
        if (st.renderedRevision >= 0) {
            oss << st.renderedRevision;
        } else {
            oss << "null";
        }
        oss << ",\"renderedViewRevision\":";
        if (st.renderedViewRevision >= 0) {
            oss << st.renderedViewRevision;
        } else {
            oss << "null";
        }
        oss << ",\"ppVersion\":" << PPVERSION;
        oss << "}}";
        return oss.str();
    }

    return makeErrorResponse(protocolVersion, requestId, sessionId_,
                             reqEditorId, "INVALID_REQUEST", "Unsupported op: " + op,
                             "{}", false);
}

} // namespace liveparam
} // namespace art
