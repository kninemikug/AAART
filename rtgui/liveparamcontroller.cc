#include "liveparamcontroller.h"
#include "editorpanel.h"
#include "toolpanelcoord.h"
#include "ppversion.h"
#include "../rtengine/cJSON.h"
#include "../rtengine/rtengine.h"

#include <algorithm>
#include <cmath>
#include <cstring>
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

using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;

std::string serialize(cJSON *root)
{
    std::unique_ptr<char, decltype(&cJSON_free)> bytes(
        cJSON_PrintUnformatted(root), cJSON_free);
    if (!bytes) {
        throw std::bad_alloc();
    }
    return bytes.get();
}

Json response(const std::string &requestId, const std::string &sessionId,
              const std::string &editorId, const char *status)
{
    Json root(cJSON_CreateObject(), cJSON_Delete);
    cJSON_AddNumberToObject(root.get(), "protocolVersion", 1);
    if (requestId.empty()) {
        cJSON_AddNullToObject(root.get(), "requestId");
    } else {
        cJSON_AddStringToObject(root.get(), "requestId", requestId.c_str());
    }
    cJSON_AddStringToObject(root.get(), "sessionId", sessionId.c_str());
    if (editorId.empty()) {
        cJSON_AddNullToObject(root.get(), "editorId");
    } else {
        cJSON_AddStringToObject(root.get(), "editorId", editorId.c_str());
    }
    cJSON_AddStringToObject(root.get(), "status", status);
    return root;
}

std::string makeErrorResponse(int, const std::string &requestId,
                              const std::string &sessionId,
                              const std::string &editorId,
                              const std::string &code,
                              const std::string &message,
                              const std::string &detailsJson, bool retryable)
{
    auto root = response(requestId, sessionId, editorId, "ERROR");
    auto *error = cJSON_AddObjectToObject(root.get(), "error");
    cJSON_AddStringToObject(error, "code", code.c_str());
    cJSON_AddStringToObject(error, "message", message.c_str());
    auto *details = cJSON_ParseWithOpts(detailsJson.c_str(), nullptr, true);
    cJSON_AddItemToObject(error, "details", details ? details : cJSON_CreateObject());
    cJSON_AddBoolToObject(error, "retryable", retryable);
    return serialize(root.get());
}

bool exactInteger(const cJSON *value, const std::string &token)
{
    if (!cJSON_IsNumber(value) || !std::isfinite(value->valuedouble) || token.empty()) {
        return false;
    }
    const bool negative = token[0] == '-';
    const size_t begin = negative ? 1 : 0;
    const auto exponentAt = token.find_first_of("eE");
    const auto decimalAt = token.find('.');
    const size_t end = exponentAt == std::string::npos ? token.size() : exponentAt;
    std::string digits;
    for (size_t i = begin; i < end; ++i) {
        if (token[i] != '.') {
            digits += token[i];
        }
    }
    if (digits.find_first_not_of('0') == std::string::npos) {
        return value->valuedouble == 0;
    }
    if (negative) {
        return false;
    }
    int exponent = 0;
    if (exponentAt != std::string::npos) {
        size_t i = exponentAt + 1;
        const bool minus = token[i] == '-';
        if (token[i] == '+' || token[i] == '-') {
            ++i;
        }
        for (; i < token.size(); ++i) {
            // Beyond this bound every nonzero value is either fractional or
            // outside the exact integer range, regardless of its mantissa.
            exponent = std::min(1000, exponent * 10 + token[i] - '0');
        }
        if (minus) {
            exponent = -exponent;
        }
    }
    int scale = exponent - (decimalAt == std::string::npos ? 0 : int(end - decimalAt - 1));
    while (scale < 0 && !digits.empty() && digits.back() == '0') {
        digits.pop_back();
        ++scale;
    }
    if (scale < 0) {
        return false;
    }
    digits.erase(0, digits.find_first_not_of('0'));
    if (digits.size() + scale > 16) {
        return false;
    }
    uint64_t integer = 0;
    for (char digit : digits) {
        integer = integer * 10 + digit - '0';
    }
    while (scale-- > 0) {
        integer *= 10;
    }
    return integer <= 9007199254740991ULL && value->valuedouble == double(integer);
}

void numberNodes(const cJSON *node, std::vector<const cJSON *> &numbers)
{
    if (cJSON_IsNumber(node)) {
        numbers.push_back(node);
    }
    for (const auto *child = node->child; child; child = child->next) {
        numberNodes(child, numbers);
    }
}

bool validJsonText(const std::string &text, std::vector<std::string> &numbers)
{
    if (text.find('\0') != std::string::npos ||
        !g_utf8_validate(text.data(), text.size(), nullptr)) {
        return false;
    }
    bool string = false;
    auto digit = [](char c) { return c >= '0' && c <= '9'; };
    for (size_t i = 0; i < text.size(); ++i) {
        const unsigned char c = text[i];
        if (string) {
            if (c < 0x20) {
                return false;
            }
            if (c == '"') {
                string = false;
            } else if (c == '\\') {
                if (++i >= text.size()) {
                    return false;
                }
                if (text[i] == 'u') {
                    if (i + 4 >= text.size()) {
                        return false;
                    }
                    unsigned code = 0;
                    for (int n = 0; n < 4; ++n) {
                        const int hex = g_ascii_xdigit_value(text[++i]);
                        if (hex < 0) {
                            return false;
                        }
                        code = code * 16 + hex;
                    }
                    // cJSON strings are NUL-terminated, so embedded NUL would
                    // otherwise make identities and duplicate keys ambiguous.
                    if (!code) {
                        return false;
                    }
                } else if (!std::strchr("\"\\/bfnrt", text[i])) {
                    return false;
                }
            }
        } else if (c == '"') {
            string = true;
        } else if (c == '-' || digit(c)) {
            size_t end = i;
            if (text[end] == '-') {
                ++end;
            }
            if (end == text.size() || !digit(text[end])) {
                return false;
            }
            if (text[end] == '0') {
                ++end;
            } else {
                while (end < text.size() && digit(text[end])) {
                    ++end;
                }
            }
            if (end < text.size() && text[end] == '.') {
                const size_t begin = ++end;
                while (end < text.size() && digit(text[end])) {
                    ++end;
                }
                if (end == begin) {
                    return false;
                }
            }
            if (end < text.size() && (text[end] == 'e' || text[end] == 'E')) {
                ++end;
                if (end < text.size() && (text[end] == '+' || text[end] == '-')) {
                    ++end;
                }
                const size_t begin = end;
                while (end < text.size() && digit(text[end])) {
                    ++end;
                }
                if (begin == end) {
                    return false;
                }
            }
            if (end < text.size() && !std::strchr(",}] \t\r\n", text[end])) {
                return false;
            }
            numbers.push_back(text.substr(i, end - i));
            i = end - 1;
        } else if (c < 0x20 && c != '\t' && c != '\r' && c != '\n') {
            return false;
        }
    }
    return !string;
}

void revisionField(cJSON *result, const char *key, int64_t revision)
{
    if (revision < 0) {
        cJSON_AddNullToObject(result, key);
    } else {
        cJSON_AddNumberToObject(result, key, revision);
    }
}

void lastMutationField(cJSON *result, const MutationRecord *record)
{
    if (!record) {
        cJSON_AddNullToObject(result, "lastMutation");
        return;
    }
    auto *mutation = cJSON_AddObjectToObject(result, "lastMutation");
    cJSON_AddStringToObject(mutation, "requestId", record->requestId.c_str());
    cJSON_AddNumberToObject(mutation, "appliedRevision", record->appliedRevision);
    cJSON_AddStringToObject(mutation, "previewStatus", record->previewStatus.c_str());
    if (record->previewStatus == "FAILED") {
        auto *error = cJSON_AddObjectToObject(mutation, "error");
        cJSON_AddStringToObject(error, "code", "INTERNAL_ERROR");
        cJSON_AddStringToObject(error, "message", "Preview processing failed");
        cJSON_AddObjectToObject(error, "details");
        cJSON_AddBoolToObject(error, "retryable", false);
    }
}

std::string appliedResponse(const std::string &sessionId,
                            const EditorState &editor, const MutationRecord &record)
{
    auto root = response(record.requestId, sessionId, editor.editorId, "APPLIED");
    auto *result = cJSON_AddObjectToObject(root.get(), "result");
    cJSON_AddNumberToObject(result, "appliedRevision", record.appliedRevision);
    cJSON_AddNumberToObject(result, "viewRevision", record.viewRevision);
    auto *params = cJSON_AddObjectToObject(result, "effectiveParams");
    cJSON_AddNumberToObject(params, record.paramKey.c_str(), record.effectiveValue);
    if (!record.contextId.empty()) {
        auto *enabled = cJSON_AddArrayToObject(result, "enabledTools");
        for (const auto &tool : record.enabledTools) {
            cJSON_AddItemToArray(enabled, cJSON_CreateString(tool.c_str()));
        }
    }
    cJSON_AddStringToObject(result, "previewStatus", record.previewStatus.c_str());
    revisionField(result, "renderedRevision", editor.renderedRevision);
    revisionField(result, "renderedViewRevision", editor.renderedViewRevision);
    cJSON_AddNumberToObject(result, "ppVersion", PPVERSION);
    return serialize(root.get());
}

} // namespace

std::string makeTransportError(const std::string &sessionId,
                               const std::string &code,
                               const std::string &message, bool retryable)
{
    // No parsing here: cJSON's parser has process-global error bookkeeping.
    auto root = response("", sessionId, "", "ERROR");
    auto *error = cJSON_AddObjectToObject(root.get(), "error");
    cJSON_AddStringToObject(error, "code", code.c_str());
    cJSON_AddStringToObject(error, "message", message.c_str());
    cJSON_AddObjectToObject(error, "details");
    cJSON_AddBoolToObject(error, "retryable", retryable);
    return serialize(root.get());
}

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

void LiveParamController::onEditorParamChanged(EditorPanel *panel,
                                               int64_t &editRev,
                                               int64_t &viewRev)
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
    if (st.hasCommittedParams) {
        ++st.currentRevision;
    } else {
        st.hasCommittedParams = true;
    }
    editRev = st.currentRevision;
    viewRev = st.currentViewRevision;

    if (st.hasInFlightMutation) {
        st.lastMutation.previewStatus = "SUPERSEDED";
        auto cit = st.mutationCache.find(st.inFlightRequestId);
        if (cit != st.mutationCache.end()) {
            cit->second.previewStatus = "SUPERSEDED";
            cit->second.completedTime = clock_();
            cit->second.isCompleted = true;
        }
        st.hasInFlightMutation = false;
    }
}

int64_t LiveParamController::onEditorViewChanged(EditorPanel *panel)
{
    if (!isEnabled() || !panel) {
        return -1;
    }
    recordGuiAccess();
    auto id = panelToId_.find(panel);
    if (id == panelToId_.end()) {
        return -1;
    }
    auto &state = editors_[id->second];
    ++state.currentViewRevision;
    state.renderedRevision = state.renderedViewRevision = -1;
    return state.currentViewRevision;
}

void LiveParamController::onEditorSizeChanged(const std::string &,
                                              const std::string &,
                                              EditorPanel *)
{
    // A size notification is not a viewport change. The main Crop publishes
    // its actual geometry on the GUI thread after layout has been updated.
}

void LiveParamController::onPreviewScheduled(EditorPanel *panel,
                                             uint64_t generation)
{
    if (!isEnabled()) {
        return;
    }
    recordGuiAccess();
    auto id = panelToId_.find(panel);
    if (id != panelToId_.end()) {
        auto &state = editors_[id->second];
        state.requiredGeneration = generation;
        state.renderedRevision = state.renderedViewRevision = -1;
    }
}

void LiveParamController::onNavigatorDelay(EditorPanel *panel, bool pending)
{
    if (!isEnabled()) {
        return;
    }
    recordGuiAccess();
    auto id = panelToId_.find(panel);
    if (id == panelToId_.end()) {
        return;
    }
    auto &state = editors_[id->second];
    if (pending) {
        ++state.pendingNavigatorUpdates;
        state.renderedRevision = state.renderedViewRevision = -1;
    } else if (state.pendingNavigatorUpdates) {
        --state.pendingNavigatorUpdates;
        updateReady(state);
    }
}

bool LiveParamController::acceptsFrame(
    EditorPanel *panel, const rtengine::ProcessingContext &ctx) const
{
    if (!isEnabled()) {
        return true;
    }
    auto id = panelToId_.find(panel);
    if (id == panelToId_.end()) {
        return false;
    }
    const auto &state = editors_.at(id->second);
    return ctx.generation && ctx.generation == state.requiredGeneration &&
           ctx.editRevision == state.currentRevision;
}

void LiveParamController::updateReady(EditorState &state)
{
    const auto &nav = state.previewContext;
    const auto &crop = state.cropContext;
    // A pan can reuse a Navigator buffer from an earlier view, provided no
    // Navigator calculation or delayed HIGHQUAL refresh is outstanding.
    if (state.pendingNavigatorUpdates || !state.requiredGeneration ||
        nav.generation != state.requiredGeneration ||
        crop.generation != state.requiredGeneration ||
        nav.editRevision != state.currentRevision ||
        crop.editRevision != state.currentRevision ||
        crop.viewRevision != state.currentViewRevision) {
        return;
    }
    state.initialized = true;
    state.renderedRevision = state.currentRevision;
    state.renderedViewRevision = state.currentViewRevision;
    if (state.hasInFlightMutation &&
        state.inFlightAppliedRev == state.currentRevision) {
        auto &record = state.mutationCache.at(state.inFlightRequestId);
        record.previewStatus = "READY";
        record.completedTime = clock_();
        record.isCompleted = true;
        state.lastMutation = record;
        state.hasInFlightMutation = false;
    }
}

void LiveParamController::onPreviewReady(
    EditorPanel *panel, const rtengine::ProcessingContext &ctx)
{
    if (!isEnabled() || !acceptsFrame(panel, ctx)) {
        return;
    }
    recordGuiAccess();
    auto &state = editors_.at(panelToId_.at(panel));
    state.previewContext = ctx;
    updateReady(state);
}

void LiveParamController::onCropReady(
    EditorPanel *panel, const rtengine::ProcessingContext &ctx)
{
    if (!isEnabled() || !acceptsFrame(panel, ctx)) {
        return;
    }
    recordGuiAccess();
    auto &state = editors_.at(panelToId_.at(panel));
    if (ctx.viewRevision != state.currentViewRevision) {
        return;
    }
    state.cropContext = ctx;
    updateReady(state);
}

void LiveParamController::onPreviewReady(EditorPanel *, int64_t, int64_t)
{
    // Legacy producers do not identify their calculation generation.
}

void LiveParamController::onCropReady(EditorPanel *, int64_t, int64_t) {}

void LiveParamController::onRenderFailed(
    EditorPanel *panel, const rtengine::ProcessingContext &ctx)
{
    if (!isEnabled() || !acceptsFrame(panel, ctx)) {
        return;
    }
    onRenderFailed(panel, "Preview processing failed");
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
            cit->second.completedTime = clock_();
            cit->second.isCompleted = true;
        }
        st.hasInFlightMutation = false;
    }
}

void LiveParamController::pruneExpiredCache(EditorState &st)
{
    auto now = clock_();
    for (auto it = st.mutationCache.begin(); it != st.mutationCache.end();) {
        if (it->second.isCompleted) {
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                               now - it->second.completedTime)
                               .count();
            if (elapsed >= 300) { // 5 minutes
                if (st.hasLastMutation && st.lastMutation.requestId == it->first) {
                    st.hasLastMutation = false;
                }
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
    size_t cacheSize = 0;
    for (auto &entry : editors_) {
        pruneExpiredCache(entry.second);
        cacheSize += entry.second.mutationCache.size();
    }
    std::string requestId;
    std::string editorId;
    auto error = [&](const char *code, const char *message, bool retryable = false,
                     const std::string &details = "{}") {
        return makeErrorResponse(1, requestId, sessionId_, editorId,
                                 code, message, details, retryable);
    };
    if (jsonRequest.size() > 65536) {
        return error("INVALID_REQUEST", "Frame exceeds 64 KiB");
    }
    std::vector<std::string> numberTokens;
    if (!validJsonText(jsonRequest, numberTokens)) {
        return error("INVALID_REQUEST", "Invalid JSON encoding or token");
    }
    Json root(cJSON_ParseWithLengthOpts(jsonRequest.c_str(), jsonRequest.size() + 1,
                                        nullptr, true), cJSON_Delete);
    if (!root || !cJSON_IsObject(root.get())) {
        return error("INVALID_REQUEST", "Expected one complete JSON object");
    }
    std::vector<const cJSON *> nodes;
    numberNodes(root.get(), nodes);
    if (nodes.size() != numberTokens.size()) {
        return error("INVALID_REQUEST", "Invalid JSON number");
    }
    auto integer = [&](const cJSON *value) {
        auto found = std::find(nodes.begin(), nodes.end(), value);
        return found != nodes.end() && exactInteger(value, numberTokens[found - nodes.begin()]);
    };
    auto field = [&](const char *name) {
        return cJSON_GetObjectItemCaseSensitive(root.get(), name);
    };
    size_t requestIds = 0;
    for (const auto *item = root->child; item; item = item->next) {
        if (item->string && std::strcmp(item->string, "requestId") == 0) {
            ++requestIds;
        }
    }
    if (requestIds != 1) {
        return error("INVALID_REQUEST", "Expected one unambiguous requestId");
    }
    auto *id = field("requestId");
    if (!cJSON_IsString(id) || !id->valuestring || !*id->valuestring ||
        g_utf8_strlen(id->valuestring, -1) > 128) {
        return error("INVALID_REQUEST", "requestId must be a 1..128 character string");
    }
    requestId = id->valuestring;
    if (hasDuplicateKeys(root.get())) {
        return error("INVALID_REQUEST", "Duplicate JSON keys rejected");
    }
    auto *editor = field("editorId");
    if (editor && (!cJSON_IsString(editor) || !editor->valuestring || !*editor->valuestring)) {
        return error("INVALID_REQUEST", "editorId must be a nonempty string");
    }
    if (editor) {
        editorId = editor->valuestring;
    }
    auto *protocol = field("protocolVersion");
    if (!integer(protocol)) {
        return error("INVALID_REQUEST", "protocolVersion must be an integer");
    }
    if (protocol->valuedouble != 1) {
        return error("UNSUPPORTED_VERSION", "Protocol version must be 1");
    }
    auto *operation = field("op");
    if (!cJSON_IsString(operation) || !operation->valuestring) {
        return error("INVALID_REQUEST", "op must be a string");
    }
    const std::string op = operation->valuestring;
    if (op != "get_state" && op != "set_param" && op != "list_params") {
        return error("INVALID_REQUEST", "Unsupported operation");
    }
    const std::set<std::string> allowed = op == "get_state"
        ? std::set<std::string>{"protocolVersion", "requestId", "op", "sessionId", "editorId", "mutationRequestId"}
        : op == "list_params"
        ? std::set<std::string>{"protocolVersion", "requestId", "op", "sessionId", "editorId", "baseRevision", "contextId", "offset", "limit"}
        : std::set<std::string>{"protocolVersion", "requestId", "op", "sessionId", "editorId", "baseRevision", "params", "contextId", "enableTool"};
    for (auto *item = root->child; item; item = item->next) {
        if (!item->string || !allowed.count(item->string)) {
            return error("INVALID_REQUEST", "Unknown request field");
        }
    }
    auto *session = field("sessionId");
    if (session && (!cJSON_IsString(session) || !session->valuestring || !*session->valuestring)) {
        return error("INVALID_REQUEST", "sessionId must be a nonempty string");
    }
    if (session && session->valuestring != sessionId_) {
        return error("SESSION_MISMATCH", "Session ID does not match running GUI");
    }
    auto *contextField = field("contextId");
    if (contextField && (!cJSON_IsString(contextField) || !contextField->valuestring ||
        !*contextField->valuestring || g_utf8_strlen(contextField->valuestring, -1) > 128)) {
        return error("INVALID_REQUEST", "contextId must be a 1..128 character string");
    }
    const std::string contextId = contextField ? contextField->valuestring : "";
    if (op == "list_params") {
        auto *base = field("baseRevision");
        auto *offsetField = field("offset");
        auto *limitField = field("limit");
        if (!session || editorId.empty() || !integer(base) ||
            (offsetField && !integer(offsetField)) ||
            (limitField && (!integer(limitField) || limitField->valuedouble < 1 ||
                            limitField->valuedouble > 32))) {
            return error("INVALID_REQUEST", "Invalid numeric catalogue target or page");
        }
        const double offsetNumber = offsetField ? offsetField->valuedouble : 0;
        if (offsetNumber > 0 && contextId.empty()) {
            return error("INVALID_REQUEST", "Continuation requires contextId");
        }
        auto found = editors_.find(editorId);
        if (found == editors_.end()) {
            return error("EDITOR_NOT_FOUND", "Editor not found or closed");
        }
        if (base->valuedouble != found->second.currentRevision) {
            return error("REVISION_CONFLICT", "Numeric catalogue revision changed");
        }
        auto *tools = found->second.panel->getToolPanelCoordinator();
        if (!tools) {
            return error("BUSY", "Editor is not ready", true);
        }
        const auto currentContext = tools->numericContext();
        if (!contextId.empty() && contextId != currentContext) {
            return error("REVISION_CONFLICT", "Numeric editing context changed");
        }
        const auto controls = tools->numericControls();
        if (offsetNumber > controls.size()) {
            return error("INVALID_REQUEST", "Catalogue offset is out of range");
        }
        const size_t offset = offsetNumber;
        const size_t limit = limitField ? limitField->valuedouble : 32;
        const size_t end = std::min(controls.size(), offset + limit);
        auto reply = response(requestId, sessionId_, editorId, "OK");
        auto *result = cJSON_AddObjectToObject(reply.get(), "result");
        cJSON_AddNumberToObject(result, "revision", found->second.currentRevision);
        cJSON_AddStringToObject(result, "contextId", currentContext.c_str());
        cJSON_AddNumberToObject(result, "total", controls.size());
        if (end < controls.size()) {
            cJSON_AddNumberToObject(result, "nextOffset", end);
        } else {
            cJSON_AddNullToObject(result, "nextOffset");
        }
        auto *items = cJSON_AddArrayToObject(result, "items");
        const auto text = [](cJSON *item, const char *key, const std::string &value) {
            const auto bounded = Glib::ustring(value).substr(0, 80);
            cJSON_AddStringToObject(item, key, bounded.c_str());
        };
        for (size_t i = offset; i < end; ++i) {
            const auto &control = controls[i];
            auto *item = cJSON_CreateObject();
            text(item, "key", control.id);
            text(item, "tool", control.tool);
            text(item, "toolLabel", control.toolLabel);
            text(item, "label", control.label);
            cJSON_AddNumberToObject(item, "min", control.minimum);
            cJSON_AddNumberToObject(item, "max", control.maximum);
            cJSON_AddNumberToObject(item, "step", control.step);
            cJSON_AddNumberToObject(item, "value", control.value);
            cJSON_AddBoolToObject(item, "enabled", control.enabled);
            cJSON_AddBoolToObject(item, "available", control.available);
            cJSON_AddBoolToObject(item, "pending", control.pending);
            cJSON_AddItemToArray(items, item);
        }
        return serialize(reply.get());
    }
    if (op == "get_state") {
        auto *mutation = field("mutationRequestId");
        if (mutation && (!cJSON_IsString(mutation) || !mutation->valuestring ||
                         !*mutation->valuestring || g_utf8_strlen(mutation->valuestring, -1) > 128 ||
                         editorId.empty())) {
            return error("INVALID_REQUEST", "mutationRequestId requires a string ID and editorId");
        }
        auto reply = response(requestId, sessionId_, editorId, "OK");
        auto *result = cJSON_AddObjectToObject(reply.get(), "result");
        if (editorId.empty()) {
            auto *list = cJSON_AddArrayToObject(result, "editors");
            for (const auto &entry : editors_) {
                auto *item = cJSON_CreateObject();
                cJSON_AddStringToObject(item, "editorId", entry.first.c_str());
                const auto name = Glib::path_get_basename(entry.second.filename);
                cJSON_AddStringToObject(item, "name", name.c_str());
                cJSON_AddItemToArray(list, item);
            }
            return serialize(reply.get());
        }
        auto found = editors_.find(editorId);
        if (found == editors_.end()) {
            return error("EDITOR_NOT_FOUND", "Editor not found or closed");
        }
        auto &state = found->second;
        cJSON_AddNumberToObject(result, "revision", state.currentRevision);
        cJSON_AddNumberToObject(result, "viewRevision", state.currentViewRevision);
        revisionField(result, "renderedRevision", state.renderedRevision);
        revisionField(result, "renderedViewRevision", state.renderedViewRevision);
        cJSON_AddNumberToObject(result, "ppVersion", PPVERSION);
        auto *supported = cJSON_AddObjectToObject(result, "supportedParams");
        auto *exposure = cJSON_AddObjectToObject(supported, "Exposure.Compensation");
        auto *tools = state.panel->getToolPanelCoordinator();
        cJSON_AddNumberToObject(exposure, "min", -12.0);
        cJSON_AddNumberToObject(exposure, "max", 12.0);
        cJSON_AddBoolToObject(exposure, "enabled", tools && tools->isExposureEnabled());
        cJSON_AddNumberToObject(exposure, "value", tools ? tools->getExposureCompensation() : 0.0);
        if (mutation) {
            auto cached = state.mutationCache.find(mutation->valuestring);
            const auto *record = cached == state.mutationCache.end() ? nullptr : &cached->second;
            lastMutationField(result, record);
            cJSON_AddStringToObject(result, "mutationStatus",
                record ? record->previewStatus.c_str() : "UNKNOWN");
        } else {
            lastMutationField(result, state.hasLastMutation ? &state.lastMutation : nullptr);
        }
        return serialize(reply.get());
    }

    if (!session || editorId.empty()) {
        return error("INVALID_REQUEST", "set_param requires sessionId and editorId");
    }
    auto *base = field("baseRevision");
    auto *params = field("params");
    auto *value = cJSON_IsObject(params) ? params->child : nullptr;
    const std::string paramKey = value && value->string ? value->string : "";
    auto *enableField = field("enableTool");
    if ((!contextId.empty() && !cJSON_IsBool(enableField)) ||
        (contextId.empty() && enableField)) {
        return error("INVALID_REQUEST", "Numeric requests require contextId and enableTool");
    }
    const bool enableTool = cJSON_IsTrue(enableField);
    auto target = editors_.find(editorId);
    if (target != editors_.end()) {
        auto cached = target->second.mutationCache.find(requestId);
        if (cached != target->second.mutationCache.end()) {
            const auto &record = cached->second;
            if (!integer(base) || !cJSON_IsObject(params) ||
                cJSON_GetArraySize(params) != 1 || !cJSON_IsNumber(value) ||
                record.baseRevision != base->valuedouble ||
                record.paramKey != paramKey ||
                record.contextId != contextId || record.enableTool != enableTool ||
                record.requestedValue != value->valuedouble) {
                return error("REQUEST_ID_CONFLICT", "requestId reused with different content");
            }
            return appliedResponse(sessionId_, target->second, record);
        }
    }
    if (!integer(base)) {
        return error("INVALID_REQUEST", "baseRevision must be a nonnegative exact integer");
    }
    const int64_t baseRevision = base->valuedouble;
    if (!cJSON_IsObject(params) || !params->child) {
        return error("INVALID_REQUEST", "params must be a nonempty object");
    }
    if (cJSON_GetArraySize(params) != 1 || paramKey.empty() ||
        (contextId.empty() && paramKey != "Exposure.Compensation")) {
        return error("UNSUPPORTED_PARAM", "Expected one supported parameter");
    }
    if (!cJSON_IsNumber(value) || !std::isfinite(value->valuedouble) ||
        (contextId.empty() && (value->valuedouble < -12.0 || value->valuedouble > 12.0))) {
        return error("INVALID_VALUE", "Parameter must be a finite number in its GUI range");
    }
    if (target == editors_.end()) {
        return error("EDITOR_NOT_FOUND", "Editor not found or closed");
    }
    auto &state = target->second;
    auto processor = state.panel->getImageProcessor();
    if (cacheSize >= 1024 || !state.initialized || !processor ||
        processor->hasTweakOperator() || state.hasInFlightMutation) {
        return error("BUSY", "Editor or command capacity is currently unavailable", true);
    }
    auto *tools = state.panel->getToolPanelCoordinator();
    if (!tools || (contextId.empty() && !tools->isExposureEnabled())) {
        return error("TOOL_DISABLED", "Exposure tool is disabled");
    }
    if (baseRevision != state.currentRevision) {
        const std::string details = "{\"currentRevision\":" + std::to_string(state.currentRevision) + "}";
        return error("REVISION_CONFLICT", "baseRevision does not match current revision", false, details);
    }
    if (!contextId.empty() && contextId != tools->numericContext()) {
        return error("REVISION_CONFLICT", "Numeric editing context changed");
    }
    MutationRecord record;
    record.requestId = requestId;
    record.previewStatus = "PENDING";
    record.paramKey = paramKey;
    record.contextId = contextId;
    record.enableTool = enableTool;
    record.requestedValue = value->valuedouble;
    record.baseRevision = baseRevision;
    auto reserved = state.mutationCache.emplace(requestId, record);
    if (!contextId.empty()) {
        const auto applied = tools->applyExternalNumeric(paramKey, record.requestedValue, enableTool);
        if (!applied.error.empty()) {
            state.mutationCache.erase(reserved.first);
            return error(applied.error.c_str(), "Numeric parameter could not be applied", applied.error == "BUSY");
        }
        record.effectiveValue = applied.value;
        record.enabledTools = applied.enabledTools;
    } else {
        if (!tools->applyExternalExposure(record.requestedValue)) {
            state.mutationCache.erase(reserved.first);
            return error("INTERNAL_ERROR", "Exposure parameter could not be applied");
        }
        record.effectiveValue = tools->getExposureCompensation();
    }
    record.appliedRevision = state.currentRevision;
    record.viewRevision = state.currentViewRevision;
    record.completedTime = clock_();
    reserved.first->second = record;
    state.lastMutation = record;
    state.hasLastMutation = true;
    state.hasInFlightMutation = true;
    state.inFlightRequestId = requestId;
    state.inFlightAppliedRev = record.appliedRevision;
    state.inFlightAppliedViewRev = record.viewRevision;
    return appliedResponse(sessionId_, state, record);
}

} // namespace liveparam
} // namespace art
