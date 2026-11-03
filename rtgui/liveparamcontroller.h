#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include <glibmm.h>

class EditorPanel;

namespace art {
namespace liveparam {

struct MutationRecord {
    std::string requestId;
    int64_t appliedRevision = 0;
    int64_t viewRevision = 0;
    std::string previewStatus; // PENDING, READY, SUPERSEDED, FAILED
    double effectiveExpComp = 0.0;
    int64_t baseRevision = 0;
    std::chrono::steady_clock::time_point completedTime;
    bool isCompleted = false;
};

struct EditorState {
    EditorPanel *panel = nullptr;
    std::string editorId;
    std::string filename;
    int64_t currentRevision = 0;
    int64_t currentViewRevision = 0;
    int64_t renderedRevision = -1;
    int64_t renderedViewRevision = -1;

    int64_t lastPreviewReadyEditRev = -1;
    int64_t lastPreviewReadyViewRev = -1;
    int64_t lastCropReadyEditRev = -1;
    int64_t lastCropReadyViewRev = -1;

    bool hasInFlightMutation = false;
    std::string inFlightRequestId;
    int64_t inFlightAppliedRev = 0;
    int64_t inFlightAppliedViewRev = 0;

    bool hasLastMutation = false;
    MutationRecord lastMutation;

    std::map<std::string, MutationRecord> mutationCache;
};

class LiveParamController {
public:
    static LiveParamController &getInstance();

    void init();
    void cleanup();

    bool isEnabled() const { return enabled_.load(std::memory_order_acquire); }
    uint64_t getNonGuiAccessCount() const
    {
        return nonGuiAccessCount_.load(std::memory_order_acquire);
    }

    const std::string &getSessionId() const { return sessionId_; }

    std::string registerEditor(EditorPanel *panel, const std::string &filename);
    void unregisterEditor(EditorPanel *panel);

    void onEditorParamChanged(EditorPanel *panel);
    void onEditorViewChanged(EditorPanel *panel);
    void onEditorSizeChanged(const std::string &sessionId,
                             const std::string &editorId, EditorPanel *panel);
    void onPreviewReady(EditorPanel *panel, int64_t editRev, int64_t viewRev);
    void onCropReady(EditorPanel *panel, int64_t editRev, int64_t viewRev);
    void onRenderFailed(EditorPanel *panel, const std::string &err);
    void onRenderFailed(const std::string &sessionId,
                        const std::string &editorId, EditorPanel *panel,
                        const std::string &err);

    std::string handleCommand(const std::string &jsonRequest);

private:
    LiveParamController();
    ~LiveParamController();

    void recordGuiAccess();
    void pruneExpiredCache(EditorState &st);

    std::atomic<bool> enabled_{false};
    std::thread::id guiThreadId_;
    bool hasGuiThreadId_ = false;
    std::atomic<uint64_t> nonGuiAccessCount_{0};
    std::string sessionId_;
    std::map<std::string, EditorState> editors_;
    std::map<EditorPanel *, std::string> panelToId_;
    uint64_t nextEditorIndex_ = 1;
};

} // namespace liveparam
} // namespace art
