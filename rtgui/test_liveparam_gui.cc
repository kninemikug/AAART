#include "cachemanager.h"
#include "chatpanel.h"
#include "config.h"
#include "multilangmgr.h"
#include "cropwindow.h"
#include "editorpanel.h"
#include "extprog.h"
#include "filecatalog.h"
#include "filepanel.h"
#include "guiutils.h"
#include "history.h"
#include "imagearea.h"
#include "imageareapanel.h"
#include "liveparamcontroller.h"
#include "liveparamserver.h"
#include "options.h"
#include "pathutils.h"
#include "rtimage.h"
#include "rtwindow.h"
#include "soundman.h"
#include "toolpanelcoord.h"
#include "test_liveparam_socket.h"
#include "wbprovider.h"
#include "../rtengine/cJSON.h"
#include "../rtengine/improccoordinator.h"
#include "../rtengine/procparams.h"
#include "../rtengine/processingjob.h"
#include "../rtengine/refreshmap.h"
#include "../rtengine/threadpool.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <giomm.h>
#include <glib/gstdio.h>
#include <gtkmm.h>
#include <iostream>
#include <locale.h>
#include <memory>
#include <mutex>
#include <set>
#include <thread>
#include <tiffio.h>
#include <unistd.h>

extern Options options;
using rtengine::FullPartialProfile;

// Globals expected by rtgui_core (defined in main.cc for ART executable)
Glib::ustring creditsPath;
Glib::ustring licensePath;
Glib::ustring argv1;
Glib::ustring argv2;
bool simpleEditor = true;
bool gimpPlugin = false;
bool remote = false;
bool is_session = false;

struct EditorPanelTestAccess {
    static void setBeforeAfter(EditorPanel *panel, bool enabled)
    {
        panel->beforeAfter->set_active(enabled);
    }
    static BatchQueueEntry *createQueuedExport(EditorPanel *panel)
    {
        return panel->createBatchQueueEntry(false, false, nullptr);
    }
};

namespace art {
namespace liveparam {
struct LiveParamControllerTestAccess {
    static void dump(LiveParamController &controller, EditorPanel *panel)
    {
        const auto found = controller.panelToId_.find(panel);
        if (found == controller.panelToId_.end()) { return; }
        const auto &state = controller.editors_.at(found->second);
        std::cerr << "Frame diagnostics: current=" << state.currentRevision
            << "/" << state.currentViewRevision << " required=" << state.requiredGeneration
            << " delayed=" << state.pendingNavigatorUpdates
            << " nav=" << state.previewContext.editRevision << "/"
            << state.previewContext.viewRevision << "/" << state.previewContext.generation
            << " crop=" << state.cropContext.editRevision << "/"
            << state.cropContext.viewRevision << "/" << state.cropContext.generation << std::endl;
    }
    static void setClock(LiveParamController &controller,
                        std::function<std::chrono::steady_clock::time_point()> clock)
    {
        controller.clock_ = std::move(clock);
    }
};
} // namespace liveparam
} // namespace art

namespace {

class TestClock {
public:
    explicit TestClock(art::liveparam::LiveParamController &controller)
        : controller_(controller), now_(new std::chrono::steady_clock::time_point(
              std::chrono::steady_clock::now()))
    {
        auto now = now_;
        art::liveparam::LiveParamControllerTestAccess::setClock(
            controller_, [now] { return *now; });
    }
    ~TestClock()
    {
        art::liveparam::LiveParamControllerTestAccess::setClock(
            controller_, [] { return std::chrono::steady_clock::now(); });
    }
    void advance(int seconds) { *now_ += std::chrono::seconds(seconds); }
private:
    art::liveparam::LiveParamController &controller_;
    std::shared_ptr<std::chrono::steady_clock::time_point> now_;
};

Glib::Threads::RecMutex g_gdkRecMutex;
void testGdkLockEnter() { g_gdkRecMutex.lock(); }
void testGdkLockLeave() { g_gdkRecMutex.unlock(); }

struct ScopedGdkUnlock {
    ScopedGdkUnlock() { gdk_threads_leave(); }
    ~ScopedGdkUnlock() { gdk_threads_enter(); }
};

#define GUI_ASSERT(cond, msg)                                                  \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::cerr << "FAILED: " << (msg) << " (" << #cond                  \
                      << ") at line " << __LINE__ << std::endl;                \
            return false;                                                      \
        }                                                                      \
    } while (0)

#define GUI_CHECK(cond, msg, failCount)                                        \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::cerr << "  [FAIL] " << (msg) << " (" << #cond                 \
                      << ") at line " << __LINE__ << std::endl;                \
            ++(failCount);                                                     \
        } else {                                                               \
            std::cout << "  [PASS] " << (msg) << std::endl;                    \
        }                                                                      \
    } while (0)

void pumpGuiEvents(int durationMs)
{
    auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(durationMs);
    while (std::chrono::steady_clock::now() < deadline) {
        while (g_main_context_pending(nullptr)) {
            g_main_context_iteration(nullptr, FALSE);
        }
        {
            ScopedGdkUnlock unlock;
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
    }
    while (g_main_context_pending(nullptr)) {
        g_main_context_iteration(nullptr, FALSE);
    }
}

bool waitUntilIdle(EditorPanel *ep, int timeoutMs = 120000)
{
    auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs);
    // Give background threads a moment to start first
    pumpGuiEvents(50);
    while (std::chrono::steady_clock::now() < deadline) {
        while (g_main_context_pending(nullptr)) {
            g_main_context_iteration(nullptr, FALSE);
        }
        if (!ep->getIsProcessing()) {
            pumpGuiEvents(30);
            if (!ep->getIsProcessing()) {
                return true;
            }
        }
        {
            ScopedGdkUnlock unlock;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    }
    return false;
}

bool copyFile(const std::string &src, const std::string &dst)
{
    std::ifstream in(src, std::ios::binary);
    std::ofstream out(dst, std::ios::binary);
    if (!in || !out) {
        return false;
    }
    out << in.rdbuf();
    return out.good();
}

void linkFilesInDir(const std::string &srcDir, const std::string &dstDir)
{
    if (!Glib::file_test(srcDir, Glib::FILE_TEST_IS_DIR)) {
        return;
    }
    Glib::Dir dir(srcDir);
    for (const auto &entry : dir) {
        std::string sp = Glib::build_filename(srcDir, entry);
        if (Glib::file_test(sp, Glib::FILE_TEST_IS_REGULAR)) {
            std::string dp = Glib::build_filename(dstDir, entry);
            unlink(dp.c_str());
            symlink(sp.c_str(), dp.c_str());
        }
    }
}

bool stageRtData(const std::string &srcRtData, const std::string &dstRtData)
{
    g_mkdir_with_parents(dstRtData.c_str(), 0700);
    const char *subdirs[] = {"languages",   "sounds",     "iccprofiles",
                             "dcpprofiles", "profiles",   "themes",
                             "ctlscripts",  "luts"};
    for (const char *sd : subdirs) {
        std::string s = Glib::build_filename(srcRtData, sd);
        std::string d = Glib::build_filename(dstRtData, sd);
        unlink(d.c_str());
        if (symlink(s.c_str(), d.c_str()) != 0) {
            return false;
        }
    }
    const char *files[] = {"cammatrices.json", "dcraw.json", "rt.json",
                           "wbpresets.json", "dynamicprofile.cfg"};
    for (const char *fn : files) {
        std::string s = Glib::build_filename(srcRtData, fn);
        std::string d = Glib::build_filename(dstRtData, fn);
        unlink(d.c_str());
        if (symlink(s.c_str(), d.c_str()) != 0) {
            return false;
        }
    }
    if (!copyFile(Glib::build_filename(srcRtData, "options/options.osx"),
                  Glib::build_filename(dstRtData, "options"))) {
        return false;
    }
    std::string imagesDst = Glib::build_filename(dstRtData, "images");
    g_mkdir_with_parents(imagesDst.c_str(), 0700);
    linkFilesInDir(Glib::build_filename(srcRtData, "images"), imagesDst);
    linkFilesInDir(Glib::build_filename(srcRtData, "images/svg"), imagesDst);
    linkFilesInDir(Glib::build_filename(srcRtData, "images/png"), imagesDst);
    return true;
}

bool test_t01_gui_state_and_off(RTWindow *rtWin, const std::string &workDir)
{
    std::cout << "[T01] GUI State Ownership, OFF Gate & Engine Boundaries"
              << std::endl;

    auto &ctrl = art::liveparam::LiveParamController::getInstance();
    auto &srv = art::liveparam::LiveParamServer::getInstance();

    // Part 1: Default OFF mode — opening, editing, pan/zoom, closing must NOT
    // register external editors or create socket/threads, while preserving normal save.
    unsetenv("ART_LIVE_PARAM");
    srv.stop();
    ctrl.cleanup();

    std::string rawSrc = ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef";
    std::string rawOff = workDir + "/t01_off_sample.nef";
    GUI_ASSERT(copyFile(rawSrc, rawOff), "Copied sample RAW for T01 OFF check");

    EditorPanel *ep = rtWin->epanel;
    GUI_ASSERT(ep != nullptr, "RTWindow->epanel exists");

    Thumbnail *thmOff = CacheManager::getInstance()->getEntry(rawOff);
    GUI_ASSERT(thmOff != nullptr, "Loaded thumbnail fixture");
    GUI_ASSERT(thmOff != nullptr, "CacheManager loaded thumbnail for T01 OFF");
    int loadErr = 0;
    rtengine::InitialImage *iiOff = rtengine::InitialImage::load(
        rawOff, thmOff->getType() == FT_Raw, &loadErr, nullptr);
    GUI_ASSERT(iiOff != nullptr && loadErr == 0,
               "InitialImage::load succeeded for T01 OFF");

    ep->open(thmOff, iiOff);
    GUI_ASSERT(!srv.isRunning(), "Server remains OFF when ART_LIVE_PARAM unset");

    int fails = 0;

    // Check that OFF mode did NOT register any editor in LiveParamController
    std::string stateOff = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t01-off-q\",\"op\":\"get_state\"}");
    std::cout << "  OFF-mode get_state: " << stateOff << std::endl;
    GUI_CHECK(stateOff.find("\"editors\":[]") != std::string::npos,
              "OFF mode must not register editor in LiveParamController", fails);

    GUI_ASSERT(waitUntilIdle(ep),
               "Initial preview processing finished in OFF mode");

    rtengine::procparams::ProcParams offProcessed, offCommitted;
    ep->getImageProcessor()->getParams(&offProcessed);
    ep->getImageProcessor()->getCommittedParams(&offCommitted);
    GUI_CHECK(offCommitted == offProcessed,
              "OFF save snapshot preserves existing processed auto values", fails);

    // Manual edit + pan/zoom + close in OFF mode preserves normal profile saving
    ToolPanelCoordinator *tpc = ep->getToolPanelCoordinator();
    GUI_ASSERT(tpc != nullptr, "ToolPanelCoordinator exists");
    GUI_ASSERT(tpc->applyExternalExposure(0.55),
               "Applied manual exposure path in OFF mode");
    GUI_ASSERT(waitUntilIdle(ep),
               "Exposure update finished in OFF mode");

    ImageAreaPanel *iap = ep->getImageAreaPanel();
    GUI_ASSERT(iap != nullptr && iap->imageArea != nullptr &&
                   iap->imageArea->mainCropWindow != nullptr,
               "Main CropWindow realized in OFF mode");
    iap->imageArea->mainCropWindow->cropHandler.setZoom(20);
    pumpGuiEvents(options.adjusterMaxDelay + 60);
    iap->imageArea->mainCropWindow->cropHandler.moveAnchor(40, 30, true);
    GUI_ASSERT(waitUntilIdle(ep),
               "Pan/zoom Crop::fullUpdate finished in OFF mode");
    GUI_CHECK(!srv.isRunning(),
              "OFF mode pan/zoom/edit did not start LiveParamServer", fails);

    ep->close();
    pumpGuiEvents(30);

    rtengine::procparams::ProcParams savedPp;
    int arpLoadErr = savedPp.load(nullptr, rawOff + ".arp");
    GUI_ASSERT(arpLoadErr == 0, "Sidecar .arp saved on close in OFF mode");
    GUI_ASSERT(std::fabs(savedPp.exposure.expcomp - 0.55) < 1e-5,
               "Saved .arp preserved Exposure.Compensation=0.55 in OFF mode");

    // Part 2: Worker-thread sizeChanged / error notifications must NOT mutate
    // LiveParamController on the worker thread, and stale open-identity callbacks
    // must not mutate a newly reopened editor.
    setenv("ART_LIVE_PARAM", "1", 1);
    GUI_ASSERT(srv.start(), "LiveParamServer started with ART_LIVE_PARAM=1");

    std::string rawOn1 = workDir + "/t01_on1.nef";
    std::string rawOn2 = workDir + "/t01_on2.nef";
    GUI_ASSERT(copyFile(rawSrc, rawOn1) && copyFile(rawSrc, rawOn2),
               "Copied sample RAWs for T01 ON check");

    Thumbnail *thm1 = CacheManager::getInstance()->getEntry(rawOn1);
    GUI_ASSERT(thm1 != nullptr, "Loaded thumbnail fixture");
    rtengine::InitialImage *ii1 = rtengine::InitialImage::load(
        rawOn1, thm1->getType() == FT_Raw, &loadErr, nullptr);
    GUI_ASSERT(thm1 && ii1 && loadErr == 0, "Loaded first ON image");
    ep->open(thm1, ii1);
    GUI_ASSERT(waitUntilIdle(ep), "First ON image idle");

    std::string ed1 = ep->getEditorId();
    GUI_ASSERT(!ed1.empty(), "First ON image registered editorId");

    // Query baseline state of ed1 on GUI thread
    std::string qBefore = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t01-q1\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        ed1 + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> jBefore(
        cJSON_Parse(qBefore.c_str()), cJSON_Delete);
    GUI_ASSERT(jBefore != nullptr, "Parsed qBefore JSON");
    cJSON *resBefore = cJSON_GetObjectItemCaseSensitive(jBefore.get(), "result");
    int viewRevBefore =
        cJSON_GetObjectItemCaseSensitive(resBefore, "viewRevision")->valueint;

    // Trigger 3 synthetic sizeChanged calls and error on a worker thread WITHOUT
    // pumping GUI main loop yet
    {
        ScopedGdkUnlock unlock;
        std::thread worker([ep]() {
            ep->sizeChanged(800, 600, 4000, 3000);
            ep->sizeChanged(800, 600, 4000, 3000);
            ep->sizeChanged(800, 600, 4000, 3000);
            ep->error("synthetic worker error");
        });
        worker.join();
    }

    // Controller state MUST NOT have changed before GUI main loop runs!
    std::string qMid = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t01-q2\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        ed1 + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> jMid(
        cJSON_Parse(qMid.c_str()), cJSON_Delete);
    cJSON *resMid = cJSON_GetObjectItemCaseSensitive(jMid.get(), "result");
    int viewRevMid =
        cJSON_GetObjectItemCaseSensitive(resMid, "viewRevision")->valueint;
    GUI_CHECK(viewRevMid == viewRevBefore,
              "Worker-thread sizeChanged must not synchronously mutate controller",
              fails);

    // Close ed1 and open ed2 BEFORE pumping pending idle callbacks, verifying stale
    // callbacks from ed1 cannot touch ed2
    ep->close();
    Thumbnail *thm2 = CacheManager::getInstance()->getEntry(rawOn2);
    GUI_ASSERT(thm2 != nullptr, "Loaded thumbnail fixture");
    rtengine::InitialImage *ii2 = rtengine::InitialImage::load(
        rawOn2, thm2->getType() == FT_Raw, &loadErr, nullptr);
    GUI_ASSERT(thm2 && ii2 && loadErr == 0, "Loaded second ON image");
    ep->open(thm2, ii2);
    std::string ed2 = ep->getEditorId();
    GUI_ASSERT(!ed2.empty() && ed2 != ed1,
               "Reopen issued distinct editorId");

    pumpGuiEvents(50);
    GUI_ASSERT(waitUntilIdle(ep), "Second ON image idle");

    std::string qEd2 = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t01-q3\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        ed2 + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> jEd2(
        cJSON_Parse(qEd2.c_str()), cJSON_Delete);
    GUI_ASSERT(jEd2 != nullptr, "Parsed qEd2 JSON");
    cJSON *resEd2 = cJSON_GetObjectItemCaseSensitive(jEd2.get(), "result");
    int viewRevEd2 =
        cJSON_GetObjectItemCaseSensitive(resEd2, "viewRevision")->valueint;
    std::cout << "  viewRevBefore(ed1)=" << viewRevBefore
              << " viewRevMid(ed1)=" << viewRevMid
              << " viewRevEd2(after 3 stale ed1 callbacks)=" << viewRevEd2
              << std::endl;
    GUI_CHECK(viewRevEd2 == viewRevBefore,
              "Stale sizeChanged callbacks from closed ed1 must not mutate ed2",
              fails);
    GUI_CHECK(ctrl.getNonGuiAccessCount() == 0,
              "All LiveParamController accesses occurred on GUI main thread",
              fails);

    ep->close();
    srv.stop();
    unsetenv("ART_LIVE_PARAM");

    // Part 3: Engine lock ordering — GUI beginUpdateParams() must not block while
    // Crop::fullUpdate() holds mProcessing and ImProcCoordinator::process() is queued.
    rtengine::InitialImage *iiLock =
        rtengine::InitialImage::load(rawSrc, true, &loadErr, nullptr);
    GUI_ASSERT(iiLock && loadErr == 0, "Loaded RAW for lock-order test");
    std::unique_ptr<rtengine::StagedImageProcessor> ipcLock(
        rtengine::StagedImageProcessor::create(iiLock));
    ipcLock->setPreviewScale(10);

    struct SlowTweak : public rtengine::TweakOperator {
        std::mutex mtx;
        std::condition_variable cv;
        bool entered = false;
        void tweakParams(rtengine::procparams::ProcParams &) override
        {
            {
                std::lock_guard<std::mutex> lk(mtx);
                if (!entered) {
                    entered = true;
                    cv.notify_all();
                }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
        }
    } slowTweak;

    rtengine::DetailedCrop *dcrop = ipcLock->createCrop(nullptr, false);
    auto *crop = static_cast<rtengine::Crop *>(dcrop);
    ipcLock->setTweakOperator(&slowTweak);

    GUI_ASSERT(crop->tryUpdate(), "crop->tryUpdate() true");
    std::thread cropWorker([crop]() { crop->fullUpdate(); });
    {
        std::unique_lock<std::mutex> lk(slowTweak.mtx);
        slowTweak.cv.wait_for(lk, std::chrono::seconds(2),
                              [&]() { return slowTweak.entered; });
    }
    GUI_ASSERT(slowTweak.entered, "Crop::fullUpdate entered tweakParams");

    {
        auto *pp = ipcLock->beginUpdateParams();
        pp->exposure.expcomp = 0.25;
        ipcLock->endUpdateParams(rtengine::M_VOID);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(30));

    auto t0 = std::chrono::steady_clock::now();
    {
        auto *pp = ipcLock->beginUpdateParams();
        pp->exposure.expcomp = 0.50;
        ipcLock->endUpdateParams(rtengine::M_VOID);
    }
    auto latencyMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                         std::chrono::steady_clock::now() - t0)
                         .count();
    {
        ScopedGdkUnlock unlock;
        cropWorker.join();
    }
    ipcLock->unsetTweakOperator(&slowTweak);
    ipcLock->stopProcessing();
    ipcLock.reset();

    std::cout << "  beginUpdateParams latency under mProcessing contention: "
              << latencyMs << " ms" << std::endl;
    GUI_CHECK(latencyMs < 80,
              "beginUpdateParams must not block on mProcessing", fails);

    // Part 4: Empty crops getHighQualComputed() boundary check
    options.prevdemo = PD_Fast;
    rtengine::InitialImage *iiEmpty =
        rtengine::InitialImage::load(rawSrc, true, &loadErr, nullptr);
    GUI_ASSERT(iiEmpty && loadErr == 0, "Loaded RAW for empty crops check");
    std::unique_ptr<rtengine::StagedImageProcessor> ipcEmpty(
        rtengine::StagedImageProcessor::create(iiEmpty));
    bool hq = ipcEmpty->getHighQualComputed();
    GUI_CHECK(!hq, "getHighQualComputed() returns false safely when crops empty",
              fails);
    ipcEmpty.reset();

    if (fails > 0) {
        std::cerr << "  -> [T01] FAILED with " << fails << " failure(s)"
                  << std::endl;
        return false;
    }
    std::cout << "  -> [T01] PASSED!" << std::endl;
    return true;
}

bool waitWorkerFinishedWithoutMainLoop(EditorPanel *ep, int timeoutMs = 120000)
{
    auto *ipc = static_cast<const rtengine::ImProcCoordinator *>(
        ep->getImageProcessor());
    if (!ipc) {
        return true;
    }
    auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs);
    {
        ScopedGdkUnlock unlock;
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
    }
    while (std::chrono::steady_clock::now() < deadline) {
        if (!ipc->is_running()) {
            return true;
        }
        ScopedGdkUnlock unlock;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    return false;
}

struct ImProcListenerAccess : public rtengine::ImProcCoordinator {
    static void invokeStaleBatchOnWorker(rtengine::ImProcCoordinator *ipc)
    {
        if (auto *l = ipc->*(&ImProcListenerAccess::aeListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            std::vector<double> c1 = {
                1.0, 0.0, 0.0, 0.25, 0.5, 0.85, 0.9, 1.0, 1.0};
            std::vector<double> c2 = {0.0};
            l->autoMatchedToneCurveChanged(c1, c2);
        }
        if (auto *l = ipc->*(&ImProcListenerAccess::autoLogListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            rtengine::procparams::LogEncodingParams lp;
            lp.enabled = true;
            lp.autocompute = true;
            lp.gain = 7.77;
            lp.blackEv = -4.25;
            lp.whiteEv = 6.75;
            l->logEncodingChanged(lp);
        }
        if (auto *l = ipc->*(&ImProcListenerAccess::autoRadiusListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            l->autoDeconvRadiusChanged(2.44f);
        }
        if (auto *l = ipc->*(&ImProcListenerAccess::awbListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            l->WBChanged(rtengine::ColorTemp(4123.0, 1.234, 1.0, "Custom"));
        }
        if (auto *l = ipc->*(&ImProcListenerAccess::adnListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            l->chromaChanged(33.3, 22.2, 11.1);
        }
        if (auto *l = ipc->*(&ImProcListenerAccess::filmNegListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            rtengine::procparams::FilmNegativeParams::RGB ri{0.4f, 0.3f, 0.2f};
            rtengine::procparams::FilmNegativeParams::RGB ro{2000.f, 2100.f,
                                                             2200.f};
            l->filmRefValuesChanged(ri, ro);
        }
        if (auto *l =
                ipc->*(&ImProcListenerAccess::flatFieldAutoClipListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            l->flatFieldAutoClipValueChanged(77);
        }
        if (auto *l = ipc->*(&ImProcListenerAccess::bayerAutoContrastListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            l->autoContrastChanged(42.0);
        }
        if (auto *l =
                ipc->*(&ImProcListenerAccess::xtransAutoContrastListener)) {
            l->setProcessingContext(ipc->getProcessingContext());
            l->autoContrastChanged(43.0);
        }
    }
};

bool test_t02_single_external_mutation(RTWindow *rtWin,
                                       const std::string &workDir)
{
    std::cout << "[T02] Single External Mutation, Rounding, History & AutoCalc"
              << std::endl;

    auto &ctrl = art::liveparam::LiveParamController::getInstance();
    auto &srv = art::liveparam::LiveParamServer::getInstance();

    setenv("ART_LIVE_PARAM", "1", 1);
    GUI_ASSERT(srv.start(), "LiveParamServer started for T02");

    std::string rawSrc = ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef";
    std::string rawT02 = workDir + "/t02_sample.nef";
    std::string rawT02Same = workDir + "/t02_same.nef";
    GUI_ASSERT(copyFile(rawSrc, rawT02) && copyFile(rawSrc, rawT02Same),
               "Copied sample RAWs for T02");

    EditorPanel *ep = rtWin->epanel;
    int loadErr = 0;
    Thumbnail *thm = CacheManager::getInstance()->getEntry(rawT02);
    GUI_ASSERT(thm != nullptr, "Loaded thumbnail fixture");
    rtengine::InitialImage *ii = rtengine::InitialImage::load(
        rawT02, thm->getType() == FT_Raw, &loadErr, nullptr);
    GUI_ASSERT(thm && ii && loadErr == 0, "Loaded T02 RAW");

    ep->open(thm, ii);
    GUI_ASSERT(waitUntilIdle(ep), "Initial open idle in T02");
    pumpGuiEvents(50);

    std::string ed = ep->getEditorId();
    std::string sess = ctrl.getSessionId();
    GUI_ASSERT(!ed.empty(), "T02 editor registered");

    int fails = 0;

    // 1. Check initial revision matches engine snapshot (no extra EvPhotoLoaded bump)
    std::string q0Str = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t02-q0\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        ed + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> q0(
        cJSON_Parse(q0Str.c_str()), cJSON_Delete);
    GUI_ASSERT(q0 != nullptr, "Parsed T02 q0");
    cJSON *q0Res = cJSON_GetObjectItemCaseSensitive(q0.get(), "result");
    int64_t rev0 = cJSON_GetObjectItemCaseSensitive(q0Res, "revision")->valueint;
    int64_t engRev0 = ep->getImageProcessor()->getCurrentEditRevision();
    std::cout << "  initial controller rev=" << rev0
              << " engine rev=" << engRev0 << std::endl;
    GUI_CHECK(rev0 == 0 && rev0 == engRev0,
              "Initial EvPhotoLoaded revision is 0 and matches engine snapshot",
              fails);

    // 2. Configure non-expcomp exposure fields while keeping default RAW histmatching active
    ToolPanelCoordinator *tpc = ep->getToolPanelCoordinator();
    History *hist = ep->getHistory();
    GUI_ASSERT(tpc && hist, "TPC and History exist");
    {
        rtengine::procparams::ProcParams setupPp;
        ep->getImageProcessor()->getParams(&setupPp);
        setupPp.exposure.enabled = true;
        setupPp.exposure.black = 0.15;
        setupPp.exposure.hrmode =
            rtengine::procparams::ExposureParams::HR_BLEND;
        setupPp.toneCurve.histmatching = true;
        setupPp.toneCurve.fromHistMatching = false;
        FullPartialProfile fp(setupPp);
        tpc->profileChange(&fp, rtengine::EvProfileChanged, "T02 setup");
    }
    GUI_ASSERT(waitUntilIdle(ep), "T02 setup profileChange idle");
    pumpGuiEvents(50);

    std::string q1Str = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t02-q1\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        ed + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> q1(
        cJSON_Parse(q1Str.c_str()), cJSON_Delete);
    int64_t rev1 =
        cJSON_GetObjectItemCaseSensitive(
            cJSON_GetObjectItemCaseSensitive(q1.get(), "result"), "revision")
            ->valueint;

    // 3. Apply non-0.05-multiple 0.125 via set_param
    std::string setStr = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t02-set-0125\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed +
        "\",\"baseRevision\":" + std::to_string(rev1) +
        ",\"params\":{\"Exposure.Compensation\":0.125}}");
    std::cout << "  set_param(0.125) resp: " << setStr << std::endl;
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> setJ(
        cJSON_Parse(setStr.c_str()), cJSON_Delete);
    GUI_ASSERT(setJ != nullptr, "Parsed set_param(0.125) JSON");
    cJSON *stItem = cJSON_GetObjectItemCaseSensitive(setJ.get(), "status");
    GUI_CHECK(stItem && cJSON_IsString(stItem) &&
                  std::string(stItem->valuestring) == "APPLIED",
              "set_param(0.125) returned APPLIED", fails);

    if (stItem && cJSON_IsString(stItem) &&
        std::string(stItem->valuestring) == "APPLIED") {
        cJSON *res = cJSON_GetObjectItemCaseSensitive(setJ.get(), "result");
        int64_t appliedRev =
            cJSON_GetObjectItemCaseSensitive(res, "appliedRevision")->valueint;
        double effVal = cJSON_GetObjectItemCaseSensitive(
                            cJSON_GetObjectItemCaseSensitive(res,
                                                             "effectiveParams"),
                            "Exposure.Compensation")
                            ->valuedouble;
        GUI_CHECK(appliedRev == rev1 + 1,
                  "appliedRevision incremented by 1", fails);
        GUI_CHECK(std::fabs(effVal - 0.13) < 1e-9 &&
                      std::fabs(tpc->getExposureCompensation() - 0.13) < 1e-9,
                  "effectiveParams reports actual Adjuster-reflected value 0.13",
                  fails);

        // Query immediately after APPLIED: revision must equal appliedRevision (not +2!)
        std::string q2Str = ctrl.handleCommand(
            "{\"protocolVersion\":1,\"requestId\":\"t02-q2\",\"op\":\"get_state\","
            "\"editorId\":\"" +
            ed + "\"}");
        std::cout << "  get_state right after APPLIED: " << q2Str << std::endl;
        std::unique_ptr<cJSON, decltype(&cJSON_Delete)> q2(
            cJSON_Parse(q2Str.c_str()), cJSON_Delete);
        cJSON *q2Res = cJSON_GetObjectItemCaseSensitive(q2.get(), "result");
        int64_t rev2 =
            cJSON_GetObjectItemCaseSensitive(q2Res, "revision")->valueint;
        cJSON *lastMut =
            cJSON_GetObjectItemCaseSensitive(q2Res, "lastMutation");
        std::string prevSt =
            (lastMut && cJSON_IsObject(lastMut))
                ? cJSON_GetObjectItemCaseSensitive(lastMut, "previewStatus")
                      ->valuestring
                : "";
        GUI_CHECK(rev2 == appliedRev,
                  "External set_param bumped revision exactly once (appliedRevision == revision)",
                  fails);
        GUI_CHECK(prevSt != "SUPERSEDED",
                  "External set_param did not self-SUPERSEDE its own mutation",
                  fails);

        // Verify History row value formatting matches Exposure::adjusterChanged ("0.13")
        size_t hSize = hist->getHistorySize();
        Glib::ustring hText, hVal;
        rtengine::ProcEvent hEv;
        rtengine::procparams::ProcParams hPp;
        GUI_ASSERT(hSize > 0 &&
                       hist->getHistoryRow(hSize - 1, hText, hVal, hEv, hPp),
                   "Read latest History row");
        std::cout << "  History latest row: text='" << hText.raw()
                  << "' value='" << hVal.raw() << "'" << std::endl;
        GUI_CHECK(hEv == rtengine::EvExpComp && hVal.raw() == "0.13",
                  "History value column formatted as '0.13' matching manual UI",
                  fails);

        // Verify other exposure fields preserved in committed params
        rtengine::procparams::ProcParams curPp;
        ep->getImageProcessor()->getCommittedParams(&curPp);
        GUI_CHECK(curPp.exposure.enabled &&
                      std::fabs(curPp.exposure.expcomp - 0.13) < 1e-9 &&
                      std::fabs(curPp.exposure.black - 0.15) < 1e-9 &&
                      curPp.exposure.hrmode ==
                          rtengine::procparams::ExposureParams::HR_BLEND,
                  "Other Exposure fields and enabled state preserved", fails);

        // Wait for background M_AUTOEXP (histmatching) to finish and check no extra rev bump
        GUI_ASSERT(waitUntilIdle(ep), "T02 M_AUTOEXP render idle");
        pumpGuiEvents(60);
        std::string q3Str = ctrl.handleCommand(
            "{\"protocolVersion\":1,\"requestId\":\"t02-q3\",\"op\":\"get_state\","
            "\"editorId\":\"" +
            ed + "\"}");
        std::unique_ptr<cJSON, decltype(&cJSON_Delete)> q3(
            cJSON_Parse(q3Str.c_str()), cJSON_Delete);
        cJSON *q3Res = cJSON_GetObjectItemCaseSensitive(q3.get(), "result");
        int64_t rev3 =
            cJSON_GetObjectItemCaseSensitive(q3Res, "revision")->valueint;
        std::string prevSt3 =
            cJSON_GetObjectItemCaseSensitive(
                cJSON_GetObjectItemCaseSensitive(q3Res, "lastMutation"),
                "previewStatus")
                ->valuestring;
        GUI_CHECK(rev3 == appliedRev && prevSt3 != "SUPERSEDED",
                  "Matching-generation autoMatchedToneCurveChanged did not bump rev or SUPERSEDE",
                  fails);
    }

    ep->close();

    // 4. Test 0.03 and same-value external set_param bumping revision once
    Thumbnail *thmSame = CacheManager::getInstance()->getEntry(rawT02Same);
    GUI_ASSERT(thmSame != nullptr, "Loaded thumbnail fixture");
    rtengine::InitialImage *iiSame = rtengine::InitialImage::load(
        rawT02Same, thmSame->getType() == FT_Raw, &loadErr, nullptr);
    GUI_ASSERT(thmSame && iiSame && loadErr == 0, "Loaded T02 same-value RAW");
    ep->open(thmSame, iiSame);
    GUI_ASSERT(waitUntilIdle(ep), "T02 same-value initial open idle");
    pumpGuiEvents(50);

    std::string edSame = ep->getEditorId();
    // Set expcomp to 0.03 manually first via profileChange, then send external set_param with SAME 0.03
    {
        rtengine::procparams::ProcParams pp003;
        ep->getImageProcessor()->getParams(&pp003);
        pp003.exposure.expcomp = 0.03;
        FullPartialProfile fp003(pp003);
        tpc->profileChange(&fp003, rtengine::EvProfileChanged, "Set 0.03");
    }
    GUI_ASSERT(waitUntilIdle(ep), "Set 0.03 idle");
    pumpGuiEvents(40);

    std::string qSame0Str = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t02-qs0\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        edSame + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> qSame0(
        cJSON_Parse(qSame0Str.c_str()), cJSON_Delete);
    int64_t revBeforeSame =
        cJSON_GetObjectItemCaseSensitive(
            cJSON_GetObjectItemCaseSensitive(qSame0.get(), "result"),
            "revision")
            ->valueint;

    std::string setSameStr = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t02-set-same\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + edSame +
        "\",\"baseRevision\":" + std::to_string(revBeforeSame) +
        ",\"params\":{\"Exposure.Compensation\":0.03}}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> setSameJ(
        cJSON_Parse(setSameStr.c_str()), cJSON_Delete);
    cJSON *sameSt = cJSON_GetObjectItemCaseSensitive(setSameJ.get(), "status");
    bool sameOk = sameSt && cJSON_IsString(sameSt) &&
                  std::string(sameSt->valuestring) == "APPLIED";
    int64_t sameAppliedRev = -1;
    double sameEff = -999.0;
    if (sameOk) {
        cJSON *sRes = cJSON_GetObjectItemCaseSensitive(setSameJ.get(), "result");
        sameAppliedRev =
            cJSON_GetObjectItemCaseSensitive(sRes, "appliedRevision")->valueint;
        sameEff = cJSON_GetObjectItemCaseSensitive(
                      cJSON_GetObjectItemCaseSensitive(sRes, "effectiveParams"),
                      "Exposure.Compensation")
                      ->valuedouble;
    }
    std::string qSame1Str = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t02-qs1\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        edSame + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> qSame1(
        cJSON_Parse(qSame1Str.c_str()), cJSON_Delete);
    int64_t revAfterSame =
        cJSON_GetObjectItemCaseSensitive(
            cJSON_GetObjectItemCaseSensitive(qSame1.get(), "result"),
            "revision")
            ->valueint;
    GUI_CHECK(sameOk && sameAppliedRev == revBeforeSame + 1 &&
                  revAfterSame == sameAppliedRev &&
                  std::fabs(sameEff - 0.03) < 1e-9,
              "Same-value 0.03 set_param succeeded and incremented revision once",
              fails);

    GUI_ASSERT(waitUntilIdle(ep), "T02 same-value render idle");
    ep->close();
    srv.stop();
    unsetenv("ART_LIVE_PARAM");

    if (fails > 0) {
        std::cerr << "  -> [T02] FAILED with " << fails << " failure(s)"
                  << std::endl;
        return false;
    }
    std::cout << "  -> [T02] PASSED!" << std::endl;
    return true;
}

bool test_t03_gui_conflict_and_derived_gates(RTWindow *rtWin,
                                             const std::string &workDir)
{
    std::cout << "[T03] GUI Revisions, SUPERSEDED Acceptance During Render & "
                 "Derived Callback Gates"
              << std::endl;

    auto &ctrl = art::liveparam::LiveParamController::getInstance();
    auto &srv = art::liveparam::LiveParamServer::getInstance();

    setenv("ART_LIVE_PARAM", "1", 1);
    GUI_ASSERT(srv.start(), "LiveParamServer started for T03");

    std::string rawSrc = ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef";
    std::string raw1 = workDir + "/t03_1.nef";
    std::string raw2 = workDir + "/t03_2.nef";
    GUI_ASSERT(copyFile(rawSrc, raw1) && copyFile(rawSrc, raw2),
               "Copied sample RAWs for T03");

    EditorPanel *ep = rtWin->epanel;
    ToolPanelCoordinator *tpc = ep->getToolPanelCoordinator();
    History *hist = ep->getHistory();
    int loadErr = 0;

    Thumbnail *thm1 = CacheManager::getInstance()->getEntry(raw1);
    GUI_ASSERT(thm1 != nullptr, "Loaded thumbnail fixture");
    rtengine::InitialImage *ii1 = rtengine::InitialImage::load(
        raw1, thm1->getType() == FT_Raw, &loadErr, nullptr);
    GUI_ASSERT(thm1 && ii1 && loadErr == 0, "Loaded T03 RAW 1");

    ep->open(thm1, ii1);
    GUI_ASSERT(waitUntilIdle(ep), "T03 initial open idle");
    pumpGuiEvents(50);

    std::string ed1 = ep->getEditorId();
    std::string sess = ctrl.getSessionId();
    int fails = 0;

    auto getRev = [&](const std::string &reqId, const std::string &editorId) {
        std::string s = ctrl.handleCommand(
            "{\"protocolVersion\":1,\"requestId\":\"" + reqId +
            "\",\"op\":\"get_state\",\"editorId\":\"" + editorId + "\"}");
        std::unique_ptr<cJSON, decltype(&cJSON_Delete)> j(
            cJSON_Parse(s.c_str()), cJSON_Delete);
        return static_cast<int64_t>(
            cJSON_GetObjectItemCaseSensitive(
                cJSON_GetObjectItemCaseSensitive(j.get(), "result"), "revision")
                ->valueint);
    };

    // 1. Manual edit, History undo/redo, Profile change, AutoCrop must all keep
    // controller revision == engine currentEditRevision
    int64_t r0 = getRev("t03-r0", ed1);
    tpc->applyExternalExposure(0.40); // outside controller scope -> manual edit!
    GUI_ASSERT(waitUntilIdle(ep), "Manual edit idle");
    pumpGuiEvents(30);
    int64_t rManual = getRev("t03-r1", ed1);
    GUI_CHECK(rManual == r0 + 1 &&
                  ep->getImageProcessor()->getCurrentEditRevision() == rManual,
              "Manual edit revision matches engine snapshot revision", fails);

    hist->undo();
    GUI_ASSERT(waitUntilIdle(ep), "History undo idle");
    pumpGuiEvents(30);
    int64_t rUndo = getRev("t03-r2", ed1);
    GUI_CHECK(rUndo == rManual + 1 &&
                  ep->getImageProcessor()->getCurrentEditRevision() == rUndo,
              "History undo revision matches engine snapshot revision", fails);

    hist->redo();
    GUI_ASSERT(waitUntilIdle(ep), "History redo idle");
    pumpGuiEvents(30);
    int64_t rRedo = getRev("t03-r3", ed1);
    GUI_CHECK(rRedo == rUndo + 1 &&
                  ep->getImageProcessor()->getCurrentEditRevision() == rRedo,
              "History redo revision matches engine snapshot revision", fails);

    tpc->autoCropRequested();
    tpc->getToolBar()->setTool(TMHand);
    GUI_ASSERT(waitUntilIdle(ep), "AutoCrop idle");
    pumpGuiEvents(30);
    int64_t rAutoCrop = getRev("t03-r4", ed1);
    GUI_CHECK(rAutoCrop == rRedo + 1 &&
                  ep->getImageProcessor()->getCurrentEditRevision() == rAutoCrop,
              "AutoCrop snapshot action revision matches engine snapshot",
              fails);

    // 2. Stale baseRevision rejection + SUPERSEDED -> immediate external set_param
    // ACCEPTED while background recalculation is STILL running!
    std::string extA = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t03-ext-a\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed1 +
        "\",\"baseRevision\":" + std::to_string(rAutoCrop) +
        ",\"params\":{\"Exposure.Compensation\":0.20}}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> extAJ(
        cJSON_Parse(extA.c_str()), cJSON_Delete);
    GUI_CHECK(std::string(cJSON_GetObjectItemCaseSensitive(extAJ.get(), "status")
                              ->valuestring) == "APPLIED",
              "t03-ext-a APPLIED", fails);

    // Stale baseRevision must return REVISION_CONFLICT
    std::string staleResp = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t03-stale\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed1 +
        "\",\"baseRevision\":" + std::to_string(rAutoCrop) +
        ",\"params\":{\"Exposure.Compensation\":0.60}}");
    GUI_CHECK(staleResp.find("\"REVISION_CONFLICT\"") != std::string::npos ||
                  staleResp.find("\"BUSY\"") != std::string::npos,
              "Stale baseRevision rejected", fails);

    // Trigger a heavy manual GUI edit (causes SUPERSEDED + background RAW/denoise work)
    {
        rtengine::procparams::ProcParams heavyPp;
        ep->getImageProcessor()->getParams(&heavyPp);
        heavyPp.exposure.expcomp = -0.30;
        heavyPp.denoise.enabled = true;
        FullPartialProfile fpHeavy(heavyPp);
        tpc->profileChange(&fpHeavy, rtengine::EvProfileChanged, "Heavy manual");
    }
    int64_t rAfterSuper = getRev("t03-r5", ed1);

    // Confirm t03-ext-a is now SUPERSEDED
    std::string qSup = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t03-qsup\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        ed1 + "\",\"mutationRequestId\":\"t03-ext-a\"}");
    GUI_CHECK(qSup.find("\"mutationStatus\":\"SUPERSEDED\"") != std::string::npos,
              "Manual edit transitioned in-flight mutation to SUPERSEDED",
              fails);

    // Confirm stale baseRevision now specifically returns REVISION_CONFLICT
    std::string staleAfterSup = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t03-stale2\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed1 +
        "\",\"baseRevision\":" + std::to_string(rAutoCrop) +
        ",\"params\":{\"Exposure.Compensation\":0.60}}");
    GUI_CHECK(staleAfterSup.find("\"REVISION_CONFLICT\"") != std::string::npos,
              "Stale baseRevision after SUPERSEDED returns REVISION_CONFLICT",
              fails);

    // IMMEDIATELY (while background recalculation from Heavy manual is STILL running!)
    // send new external set_param with rAfterSuper -> MUST succeed (NOT BUSY from getIsProcessing()!)
    std::string extDuringBg = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t03-ext-bg\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed1 +
        "\",\"baseRevision\":" + std::to_string(rAfterSuper) +
        ",\"params\":{\"Exposure.Compensation\":0.75}}");
    std::cout << "  set_param during background recalculation: " << extDuringBg
              << std::endl;
    GUI_CHECK(extDuringBg.find("\"status\":\"APPLIED\"") != std::string::npos,
              "External set_param accepted during normal background recalculation after SUPERSEDED",
              fails);

    // 3. Delayed stale derived callbacks (all 9 §2 types!) must NOT overwrite newer
    // manual edit, external edit, profileChange, or reopened editor!
    GUI_ASSERT(waitUntilIdle(ep), "Idle before derived callback gate check");
    pumpGuiEvents(40);

    // Set known explicit baseline values across all 9 derived-callback panels
    auto setExplicitBaseline = [&]() {
        rtengine::procparams::ProcParams basePp;
        ep->getImageProcessor()->getParams(&basePp);
        basePp.exposure.expcomp = 0.25;
        basePp.toneCurve.histmatching = false;
        basePp.toneCurve.fromHistMatching = false;
        basePp.toneCurve.curve = {0.0};
        basePp.toneCurve.curve2 = {0.0};
        basePp.logenc.enabled = true;
        basePp.logenc.autocompute = false;
        basePp.logenc.gain = 1.25;
        basePp.logenc.blackEv = -5.0;
        basePp.logenc.whiteEv = 3.0;
        basePp.sharpening.enabled = true;
        basePp.sharpening.method = "rld";
        basePp.sharpening.deconvAutoRadius = false;
        basePp.sharpening.deconvradius = 1.50;
        basePp.wb.enabled = true;
        basePp.wb.method = rtengine::procparams::WBParams::CUSTOM_TEMP;
        basePp.wb.temperature = 5500;
        basePp.wb.green = 1.000;
        basePp.denoise.enabled = true;
        basePp.denoise.chrominanceMethod =
            rtengine::procparams::DenoiseParams::ChrominanceMethod::MANUAL;
        basePp.denoise.chrominance = 12.0;
        basePp.denoise.chrominanceRedGreen = 1.0;
        basePp.denoise.chrominanceBlueYellow = -1.0;
        basePp.filmNegative.enabled = false;
        basePp.filmNegative.refInput = {0.1f, 0.1f, 0.1f};
        basePp.raw.ff_AutoClipControl = false;
        basePp.raw.ff_clipControl = 10;
        basePp.raw.bayersensor.dualDemosaicAutoContrast = false;
        basePp.raw.bayersensor.dualDemosaicContrast = 18.0;
        basePp.raw.xtranssensor.dualDemosaicAutoContrast = false;
        basePp.raw.xtranssensor.dualDemosaicContrast = 19.0;
        FullPartialProfile fpBase(basePp);
        tpc->profileChange(&fpBase, rtengine::EvProfileChanged, "Explicit base");
    };

    setExplicitBaseline();
    GUI_ASSERT(waitUntilIdle(ep), "Explicit baseline idle");
    pumpGuiEvents(40);

    // Positive control: valid source context must reach both widgets and pending params.
    auto *validIpc = static_cast<rtengine::ImProcCoordinator *>(ep->getImageProcessor());
    const int64_t validRev = getRev("t03-valid-before", ed1);
    {
        ScopedGdkUnlock unlock;
        std::thread producer([validIpc]() {
            ImProcListenerAccess::invokeStaleBatchOnWorker(validIpc);
        });
        producer.join();
    }
    pumpGuiEvents(40);
    rtengine::procparams::ProcParams acceptedDerived;
    ep->getImageProcessor()->getCommittedParams(&acceptedDerived);
    std::cout << "  accepted derived: hist=" << acceptedDerived.toneCurve.fromHistMatching
              << " log=" << acceptedDerived.logenc.gain
              << " radius=" << acceptedDerived.sharpening.deconvradius
              << " chroma=" << acceptedDerived.denoise.chrominance
              << " ff=" << acceptedDerived.raw.ff_clipControl
              << " bayer=" << acceptedDerived.raw.bayersensor.dualDemosaicContrast
              << " xtrans=" << acceptedDerived.raw.xtranssensor.dualDemosaicContrast
              << " rev=" << getRev("t03-valid-actual", ed1) << "/" << validRev
              << std::endl;
    GUI_CHECK(acceptedDerived.toneCurve.fromHistMatching &&
                  std::fabs(acceptedDerived.logenc.gain - 7.77) < 1e-6 &&
                  std::fabs(acceptedDerived.sharpening.deconvradius - 2.44) < 0.01 &&
                  std::fabs(acceptedDerived.denoise.chrominance - 33.3) < 0.01 &&
                  acceptedDerived.raw.ff_clipControl == 77 &&
                  acceptedDerived.raw.bayersensor.dualDemosaicContrast == 42.0 &&
                  acceptedDerived.raw.xtranssensor.dualDemosaicContrast == 43.0 &&
                  getRev("t03-valid-after", ed1) == validRev,
              "Valid derived results update pending params without a new revision", fails);
    tpc->refreshPreview(rtengine::EvMonitorTransform);
    GUI_ASSERT(waitUntilIdle(ep), "Valid derived values survive non-panel update");
    rtengine::procparams::ProcParams afterNonPanel;
    ep->getImageProcessor()->getCommittedParams(&afterNonPanel);
    GUI_CHECK(std::fabs(afterNonPanel.logenc.gain - 7.77) < 1e-6 &&
                  std::fabs(afterNonPanel.denoise.chrominance - 33.3) < 0.01,
              "Non-panel update preserves accepted derived values", fails);
    setExplicitBaseline();
    GUI_ASSERT(waitUntilIdle(ep), "Reset explicit baseline after positive control");
    pumpGuiEvents(40);

    // Queue all 9 stale derived callbacks from a worker thread BEFORE new external edit
    auto *rawIpc1 =
        static_cast<rtengine::ImProcCoordinator *>(ep->getImageProcessor());
    {
        ScopedGdkUnlock unlock;
        std::thread staleWorker(
            [rawIpc1]() { ImProcListenerAccess::invokeStaleBatchOnWorker(rawIpc1); });
        staleWorker.join();
    }

    // Advance revision via external set_param BEFORE pumping GLib main loop!
    int64_t rBeforeStaleDrain = getRev("t03-r6", ed1);
    std::string extAfterStale = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t03-ext-stale\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed1 +
        "\",\"baseRevision\":" + std::to_string(rBeforeStaleDrain) +
        ",\"params\":{\"Exposure.Compensation\":0.45}}");
    GUI_CHECK(extAfterStale.find("\"status\":\"APPLIED\"") != std::string::npos,
              "t03-ext-stale APPLIED before draining stale derived callbacks",
              fails);

    // Now pump GLib main loop so queued stale callbacks attempt to apply, then trigger
    // a panel write via sharpMaskSelected / refreshPreview to expose any widget pollution
    pumpGuiEvents(80);
    GUI_ASSERT(waitUntilIdle(ep), "Idle after draining stale derived callbacks");
    pumpGuiEvents(40);
    tpc->refreshPreview(rtengine::EvMonitorTransform);
    GUI_ASSERT(waitUntilIdle(ep), "Idle after refreshPreview");

    rtengine::procparams::ProcParams afterStalePp;
    ep->getImageProcessor()->getParams(&afterStalePp);
    std::cout << "  after stale callbacks: logGain=" << afterStalePp.logenc.gain
              << " deconvRad=" << afterStalePp.sharpening.deconvradius
              << " chroma=" << afterStalePp.denoise.chrominance
              << " ffClip=" << afterStalePp.raw.ff_clipControl
              << " bayerContrast="
              << afterStalePp.raw.bayersensor.dualDemosaicContrast
              << " xtransContrast="
              << afterStalePp.raw.xtranssensor.dualDemosaicContrast
              << " fromHistMatch=" << afterStalePp.toneCurve.fromHistMatching
              << std::endl;
    GUI_CHECK(!afterStalePp.toneCurve.fromHistMatching &&
                  std::fabs(afterStalePp.logenc.gain - 1.25) < 1e-6 &&
                  std::fabs(afterStalePp.sharpening.deconvradius - 1.50) < 1e-5 &&
                  afterStalePp.wb.temperature == 5500 &&
                  std::fabs(afterStalePp.denoise.chrominance - 12.0) < 1e-6 &&
                  afterStalePp.raw.ff_clipControl == 10 &&
                  std::fabs(
                      afterStalePp.raw.bayersensor.dualDemosaicContrast - 18.0) <
                      1e-6 &&
                  std::fabs(
                      afterStalePp.raw.xtranssensor.dualDemosaicContrast - 19.0) <
                      1e-6,
              "Stale derived callbacks (all 9 §2 types) discarded without mutating panels or nextParams",
              fails);

    auto queueDerived = [&]() {
        auto *processor = static_cast<rtengine::ImProcCoordinator *>(ep->getImageProcessor());
        ScopedGdkUnlock unlock;
        std::thread producer([processor]() {
            ImProcListenerAccess::invokeStaleBatchOnWorker(processor);
        });
        producer.join();
    };
    auto baselineIntact = [&]() {
        rtengine::procparams::ProcParams pp;
        ep->getImageProcessor()->getCommittedParams(&pp);
        return !pp.toneCurve.fromHistMatching && pp.logenc.gain == 1.25 &&
            std::fabs(pp.sharpening.deconvradius - 1.50) < 1e-5 &&
            pp.wb.temperature == 5500 && pp.denoise.chrominance == 12.0 &&
            pp.raw.ff_clipControl == 10 &&
            pp.raw.bayersensor.dualDemosaicContrast == 18.0 &&
            pp.raw.xtranssensor.dualDemosaicContrast == 19.0 &&
            pp.filmNegative.refInput.r == 0.1f;
    };
    for (int scenario = 0; scenario < 3; ++scenario) {
        setExplicitBaseline();
        GUI_ASSERT(waitUntilIdle(ep), "Baseline before delayed callback scenario");
        pumpGuiEvents(30);
        queueDerived();
        if (scenario == 0) {
            tpc->applyExternalExposure(0.60);
        } else if (scenario == 1) {
            setExplicitBaseline();
        } else {
            // Same edit revision, but a newer Navigator calculation request.
            ep->getImageProcessor()->startProcessing(rtengine::M_HIGHQUAL);
        }
        pumpGuiEvents(40);
        GUI_ASSERT(waitUntilIdle(ep), "Delayed callback scenario idle");
        GUI_CHECK(baselineIntact(),
                  "Delayed results discarded after manual/profile/calculation replacement", fails);
    }

    // 4. Close immediately after APPLIED while previous render is in progress -> saveProfile must preserve new value!
    {
        // Trigger a manual change first to clear in-flight, then immediately external set_param(-1.15) + close()
        tpc->applyExternalExposure(-0.10);
        int64_t rPreClose = getRev("t03-r7", ed1);
        std::string extClose = ctrl.handleCommand(
            "{\"protocolVersion\":1,\"requestId\":\"t03-ext-close\",\"op\":\"set_param\","
            "\"sessionId\":\"" +
            sess + "\",\"editorId\":\"" + ed1 +
            "\",\"baseRevision\":" + std::to_string(rPreClose) +
            ",\"params\":{\"Exposure.Compensation\":-1.15}}");
        GUI_CHECK(extClose.find("\"status\":\"APPLIED\"") != std::string::npos,
                  "t03-ext-close APPLIED right before close()", fails);
        ep->close();
    }

    rtengine::procparams::ProcParams closedPp;
    GUI_ASSERT(closedPp.load(nullptr, raw1 + ".arp") == 0,
               "Loaded sidecar .arp saved during mid-render close()");
    std::cout << "  mid-render close saved expcomp=" << closedPp.exposure.expcomp
              << std::endl;
    GUI_CHECK(std::fabs(closedPp.exposure.expcomp - (-1.15)) < 1e-6,
              "Closing immediately after APPLIED while previous render ran preserved -1.15 in .arp",
              fails);

    Thumbnail *reopenThm = CacheManager::getInstance()->getEntry(raw1);
    GUI_ASSERT(reopenThm != nullptr, "Reopen thumbnail");
    auto *reopenImage = rtengine::InitialImage::load(raw1, true, &loadErr, nullptr);
    GUI_ASSERT(reopenImage && loadErr == 0, "Reopen source image");
    ep->open(reopenThm, reopenImage);
    GUI_ASSERT(waitUntilIdle(ep), "Reopened source idle");
    const auto closedId = ep->getEditorId();
    queueDerived();
    ep->close();
    Thumbnail *otherThm = CacheManager::getInstance()->getEntry(raw2);
    GUI_ASSERT(otherThm != nullptr, "Other image thumbnail");
    auto *otherImage = rtengine::InitialImage::load(raw2, true, &loadErr, nullptr);
    GUI_ASSERT(otherImage && loadErr == 0, "Other source image");
    ep->open(otherThm, otherImage);
    GUI_ASSERT(waitUntilIdle(ep), "New image after queued old callbacks idle");
    pumpGuiEvents(40);
    rtengine::procparams::ProcParams newImageParams;
    ep->getImageProcessor()->getCommittedParams(&newImageParams);
    GUI_CHECK(ep->getEditorId() != closedId &&
                  newImageParams.logenc.gain != 7.77 &&
                  newImageParams.raw.ff_clipControl != 77 &&
                  newImageParams.denoise.chrominance != 33.3,
              "Closing cancels old image callbacks before reopening a new editor", fails);
    ep->close();

    srv.stop();
    unsetenv("ART_LIVE_PARAM");

    if (fails > 0) {
        std::cerr << "  -> [T03] FAILED with " << fails << " failure(s)"
                  << std::endl;
        return false;
    }
    std::cout << "  -> [T03] PASSED!" << std::endl;
    return true;
}

bool test_t13_resubmit_and_conflict(RTWindow *rtWin,
                                    const std::string &workDir)
{
    std::cout << "[T13-Step2] Idempotent Resubmit & Exact Conflict Detection"
              << std::endl;

    auto &ctrl = art::liveparam::LiveParamController::getInstance();
    auto &srv = art::liveparam::LiveParamServer::getInstance();

    setenv("ART_LIVE_PARAM", "1", 1);
    GUI_ASSERT(srv.start(), "LiveParamServer started for T13-Step2");

    std::string rawSrc = ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef";
    std::string rawT13 = workDir + "/t13_sample.nef";
    GUI_ASSERT(copyFile(rawSrc, rawT13), "Copied sample RAW for T13-Step2");

    EditorPanel *ep = rtWin->epanel;
    int loadErr = 0;
    Thumbnail *thm = CacheManager::getInstance()->getEntry(rawT13);
    GUI_ASSERT(thm != nullptr, "Loaded thumbnail fixture");
    rtengine::InitialImage *ii = rtengine::InitialImage::load(
        rawT13, thm->getType() == FT_Raw, &loadErr, nullptr);
    GUI_ASSERT(thm && ii && loadErr == 0, "Loaded T13 RAW");

    ep->open(thm, ii);
    GUI_ASSERT(waitUntilIdle(ep), "T13 initial open idle");
    pumpGuiEvents(40);

    std::string ed = ep->getEditorId();
    std::string sess = ctrl.getSessionId();
    int fails = 0;
    TestClock clock(ctrl);

    std::string q0Str = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t13-q0\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        ed + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> q0(
        cJSON_Parse(q0Str.c_str()), cJSON_Delete);
    int64_t r0 =
        cJSON_GetObjectItemCaseSensitive(
            cJSON_GetObjectItemCaseSensitive(q0.get(), "result"), "revision")
            ->valueint;

    std::string reqJson =
        "{\"protocolVersion\":1,\"requestId\":\"t13-idem-1\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed +
        "\",\"baseRevision\":" + std::to_string(r0) +
        ",\"params\":{\"Exposure.Compensation\":0.125}}";

    std::string rFirst = ctrl.handleCommand(reqJson);
    std::string rReplay = ctrl.handleCommand(reqJson);

    std::string q1Str = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t13-q1\",\"op\":\"get_state\","
        "\"editorId\":\"" +
        ed + "\"}");
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> q1(
        cJSON_Parse(q1Str.c_str()), cJSON_Delete);
    int64_t rAfterReplay =
        cJSON_GetObjectItemCaseSensitive(
            cJSON_GetObjectItemCaseSensitive(q1.get(), "result"), "revision")
            ->valueint;

    GUI_CHECK(rFirst.find("\"status\":\"APPLIED\"") != std::string::npos &&
                  rReplay.find("\"status\":\"APPLIED\"") != std::string::npos &&
                  rAfterReplay == r0 + 1 &&
                  rReplay.find("0.13") != std::string::npos,
              "Same requestId + same content replayed without re-execution and reported 0.13",
              fails);

    // Tiny numeric difference (0.1250004 vs 0.125 — within old 1e-6 bug!) MUST be REQUEST_ID_CONFLICT
    std::string nearConflict = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t13-idem-1\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed +
        "\",\"baseRevision\":" + std::to_string(r0) +
        ",\"params\":{\"Exposure.Compensation\":0.1250004}}");
    std::cout << "  near-diff reuse (0.1250004 vs 0.125): " << nearConflict
              << std::endl;
    GUI_CHECK(nearConflict.find("\"REQUEST_ID_CONFLICT\"") != std::string::npos,
              "Different param value within 1e-6 must NOT be treated as equal (REQUEST_ID_CONFLICT)",
              fails);

    std::string baseRevConflict = ctrl.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t13-idem-1\",\"op\":\"set_param\","
        "\"sessionId\":\"" +
        sess + "\",\"editorId\":\"" + ed +
        "\",\"baseRevision\":" + std::to_string(r0 + 1) +
        ",\"params\":{\"Exposure.Compensation\":0.125}}");
    GUI_CHECK(baseRevConflict.find("\"REQUEST_ID_CONFLICT\"") != std::string::npos,
              "Different baseRevision with same requestId returns REQUEST_ID_CONFLICT",
              fails);

    clock.advance(86400);
    GUI_CHECK(ctrl.handleCommand(reqJson).find("\"status\":\"APPLIED\"") != std::string::npos,
              "Pending mutation does not expire after a day", fails);
    ep->getToolPanelCoordinator()->applyExternalExposure(-0.10);
    const auto mutationQuery =
        "{\"protocolVersion\":1,\"requestId\":\"ttl-query\",\"op\":\"get_state\","
        "\"editorId\":\"" + ed + "\",\"mutationRequestId\":\"t13-idem-1\"}";
    clock.advance(299);
    GUI_CHECK(ctrl.handleCommand(mutationQuery).find("SUPERSEDED") != std::string::npos,
              "Completed mutation retained at 299 seconds", fails);
    clock.advance(1);
    GUI_CHECK(ctrl.handleCommand(mutationQuery).find("UNKNOWN") != std::string::npos &&
                  ctrl.handleCommand(reqJson).find("REVISION_CONFLICT") != std::string::npos,
              "At 300 seconds cache expires before lookup and replay is not accepted", fails);

    // Use real commits without draining GUI results: each manual commit
    // supersedes the preceding external commit, allowing bounded cache pressure.
    int64_t revision = r0 + 2;
    auto request = [&](const std::string &id) {
        return "{\"protocolVersion\":1,\"requestId\":\"" + id +
            "\",\"op\":\"set_param\",\"sessionId\":\"" + sess +
            "\",\"editorId\":\"" + ed + "\",\"baseRevision\":" +
            std::to_string(revision) + ",\"params\":{\"Exposure.Compensation\":0.03}}";
    };
    for (int i = 0; i < 1024; ++i) {
        GUI_ASSERT(ctrl.handleCommand(request("t13-cap-" + std::to_string(i))).find(
                       "\"status\":\"APPLIED\"") != std::string::npos,
                   "Every reserved cache slot follows a real GUI mutation");
        ++revision;
        ep->getToolPanelCoordinator()->applyExternalExposure(-0.10);
        ++revision;
    }
    GUI_CHECK(ctrl.handleCommand(request("t13-overflow")).find("BUSY") != std::string::npos,
              "1024 retained entries reject overflow before applying", fails);
    clock.advance(299);
    GUI_CHECK(ctrl.handleCommand(request("t13-overflow")).find("BUSY") != std::string::npos,
              "Cache saturation does not evict an entry before its deadline", fails);
    clock.advance(1);
    GUI_CHECK(ctrl.handleCommand(request("t13-after-ttl")).find("APPLIED") != std::string::npos,
              "Capacity recovers exactly at the completion TTL", fails);

    GUI_ASSERT(waitUntilIdle(ep), "T13 render idle");
    ep->close();
    srv.stop();
    unsetenv("ART_LIVE_PARAM");

    if (fails > 0) {
        std::cerr << "  -> [T13-Step2] FAILED with " << fails << " failure(s)"
                  << std::endl;
        return false;
    }
    std::cout << "  -> [T13-Step2] PASSED!" << std::endl;
    return true;
}

struct FrameFixture {
    EditorPanel *panel;
    art::liveparam::LiveParamController &controller;
    bool open(RTWindow *win, const std::string &dir, const std::string &name)
    {
        panel = win->epanel;
        setenv("ART_LIVE_PARAM", "1", 1);
        if (!art::liveparam::LiveParamServer::getInstance().start()) {
            return false;
        }
        const auto raw = dir + "/" + name + ".nef";
        if (!copyFile(ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef", raw)) {
            return false;
        }
        auto *thumbnail = CacheManager::getInstance()->getEntry(raw);
        int error = 0;
        auto *image = rtengine::InitialImage::load(raw, true, &error, nullptr);
        if (!thumbnail || !image || error) {
            return false;
        }
        panel->open(thumbnail, image);
        return waitUntilIdle(panel);
    }
    std::string query() const
    {
        return controller.handleCommand("{\"protocolVersion\":1,\"requestId\":\"frames-query\","
            "\"op\":\"get_state\",\"editorId\":\"" + panel->getEditorId() + "\"}");
    }
    int64_t field(const std::string &key) const
    {
        const auto state = query();
        std::unique_ptr<cJSON, decltype(&cJSON_Delete)> json(cJSON_Parse(state.c_str()), cJSON_Delete);
        auto *value = cJSON_GetObjectItemCaseSensitive(
            cJSON_GetObjectItemCaseSensitive(json.get(), "result"), key.c_str());
        return cJSON_IsNumber(value) ? int64_t(value->valuedouble) : -1;
    }
    std::string set(const std::string &id, double value) const
    {
        return controller.handleCommand("{\"protocolVersion\":1,\"requestId\":\"" + id +
            "\",\"op\":\"set_param\",\"sessionId\":\"" + controller.getSessionId() +
            "\",\"editorId\":\"" + panel->getEditorId() + "\",\"baseRevision\":" +
            std::to_string(field("revision")) +
            ",\"params\":{\"Exposure.Compensation\":" + std::to_string(value) + "}}");
    }
    bool waitReady(int timeoutMs = 120000) const
    {
        art::liveparam::LiveParamControllerTestAccess::dump(controller, panel);
        const auto deadline = std::chrono::steady_clock::now() +
            std::chrono::milliseconds(timeoutMs);
        while (std::chrono::steady_clock::now() < deadline) {
            pumpGuiEvents(10);
            if (query().find("\"previewStatus\":\"READY\"") != std::string::npos) {
                return true;
            }
        }
        art::liveparam::LiveParamControllerTestAccess::dump(controller, panel);
        const auto nav = area()->getPreviewHandler()->getDisplayedContext();
        const auto crop = area()->mainCropWindow->cropHandler.getDisplayedContext();
        const auto engine = panel->getImageProcessor()->getProcessingContext();
        std::cerr << "Displayed nav/crop generation: " << nav.generation << "/" << crop.generation
            << " engine=" << engine.generation << std::endl;
        std::cerr << "Readiness timeout: " << query() << std::endl;
        return false;
    }
    ImageArea *area() const { return panel->getImageAreaPanel()->imageArea; }
    ~FrameFixture()
    {
        if (panel) {
            panel->close();
        }
        art::liveparam::LiveParamServer::getInstance().stop();
    }
};

uint64_t frameHash(const Glib::RefPtr<Gdk::Pixbuf> &image)
{
    if (!image) {
        return 0;
    }
    uint64_t hash = 1469598103934665603ULL;
    for (int y = 0; y < image->get_height(); ++y) {
        const auto *row = image->get_pixels() + y * image->get_rowstride();
        for (int x = 0; x < image->get_width() * 3; ++x) {
            hash = (hash ^ row[x]) * 1099511628211ULL;
        }
    }
    return hash;
}

bool test_t11_delayed_frames(RTWindow *win, const std::string &dir)
{
    std::cout << "[T11] Delayed actual frames and calculation generations" << std::endl;
    FrameFixture f{nullptr, art::liveparam::LiveParamController::getInstance()};
    GUI_ASSERT(f.open(win, dir, "t11"), "fixture opened");
    auto *preview = f.area()->getPreviewHandler();
    auto &crop = f.area()->mainCropWindow->cropHandler;
    const auto oldPixels = preview->getDisplayedImage();
    const auto oldHash = frameHash(oldPixels);
    GUI_ASSERT(f.set("delayed-old", 1.25).find("APPLIED") != std::string::npos,
               "external change accepted");
    GUI_ASSERT(waitWorkerFinishedWithoutMainLoop(f.panel), "first producer drained without GUI");
    GUI_ASSERT(frameHash(oldPixels) == oldHash, "displayed Navigator owns immutable bytes");
    GUI_ASSERT(f.panel->getToolPanelCoordinator()->applyExternalExposure(-0.5),
               "manual GUI change supersedes queued result");
    GUI_ASSERT(waitWorkerFinishedWithoutMainLoop(f.panel), "second producer drained without GUI");
    const auto newest = f.panel->getImageProcessor()->getProcessingContext();
    pumpGuiEvents(150);
    GUI_ASSERT(waitUntilIdle(f.panel), "delayed queues drained");
    GUI_ASSERT(preview->getDisplayedContext().generation == newest.generation &&
               crop.getDisplayedContext().generation == newest.generation &&
               crop.getDisplayedContext().editRevision == f.field("revision"),
               "Navigator and coalesced Crop retain newest pixels with matching provenance");
    GUI_ASSERT(f.query().find("SUPERSEDED") != std::string::npos,
               "superseded request never becomes READY");

    // Withhold the main Crop, then calculate a second Navigator generation at
    // the same edit/view revisions. Actual Crop delivery precedes Navigator.
    crop.getCrop()->setListener(nullptr);
    GUI_ASSERT(f.set("same-edit", 0.75).find("APPLIED") != std::string::npos,
               "second external request accepted");
    GUI_ASSERT(waitWorkerFinishedWithoutMainLoop(f.panel), "Navigator-only pass finished");
    pumpGuiEvents(120);
    GUI_ASSERT(f.query().find("PENDING") != std::string::npos,
               "Navigator alone cannot complete request");
    crop.getCrop()->setListener(&crop);
    struct Observer : PreviewListener {
        std::function<void()> callback;
        void previewImageChanged() override { callback(); }
    } observer;
    bool observed = false, pendingBeforeNavigator = false;
    observer.callback = [&] {
        observed = true;
        pendingBeforeNavigator = f.query().find("PENDING") != std::string::npos;
    };
    preview->addPreviewImageListener(&observer);
    f.panel->getImageProcessor()->startProcessing(rtengine::M_MONITOR);
    GUI_ASSERT(waitWorkerFinishedWithoutMainLoop(f.panel), "same-edit second calculation finished");
    pumpGuiEvents(150);
    GUI_ASSERT(observed && pendingBeforeNavigator,
               "new Crop cannot combine with old Navigator from the same edit/view");
    GUI_ASSERT(f.query().find("READY") != std::string::npos,
               "both second-generation actual buffers complete request");
    // A refresh accepted while the previous Crop is publishing its final
    // progress notification must either be consumed or start a new worker.
    struct FinalProgressRefresh : rtengine::ProgressListener {
        EditorPanel *panel = nullptr;
        std::shared_ptr<rtengine::StagedImageProcessor> processor;
        rtengine::DetailedCrop *crop = nullptr;
        std::atomic<int> finishes{0};
        std::atomic<bool> newWorker{false};
        void setProgress(double value) override { panel->setProgress(value); }
        void setProgressStr(const Glib::ustring &text) override { panel->setProgressStr(text); }
        void error(const Glib::ustring &text) override { panel->error(text); }
        void setProgressState(bool running) override
        {
            if (!running && finishes.fetch_add(1) == 0) {
                newWorker = crop->tryUpdate();
                if (newWorker) {
                    const auto keepAlive = processor;
                    auto *next = crop;
                    rtengine::ThreadPool::add_task(rtengine::ThreadPool::Priority::HIGH,
                        [keepAlive, next] { next->fullUpdate(); });
                }
            }
            panel->setProgressState(running);
        }
    } refresh;
    refresh.panel = f.panel;
    refresh.processor = f.area()->getImProcCoordinator();
    refresh.crop = crop.getCrop();
    refresh.processor->setProgressListener(&refresh);
    crop.update();
    const bool drained = waitUntilIdle(f.panel);
    refresh.processor->setProgressListener(f.panel);
    GUI_ASSERT(drained && refresh.newWorker && refresh.finishes == 2,
               "refresh at the end of a Crop pass starts a second worker without losing work");
    // The listener belongs to this open; close before its stack storage expires.
    f.panel->close();
    std::cout << "  -> [T11] PASSED!" << std::endl;
    return true;
}

bool test_t12_views_and_lifetime(RTWindow *win, const std::string &dir)
{
    std::cout << "[T12] Real viewport, delayed HIGHQUAL, detail and reopen" << std::endl;
    FrameFixture f{nullptr, art::liveparam::LiveParamController::getInstance()};
    const auto oldMode = options.prevdemo;
    options.prevdemo = PD_Fast;
    GUI_ASSERT(f.open(win, dir, "t12"), "fixture opened");
    auto &crop = f.area()->mainCropWindow->cropHandler;
    auto *ipc = f.panel->getImageProcessor();
    crop.setZoom(20);
    pumpGuiEvents(options.adjusterMaxDelay + 100);
    GUI_ASSERT(waitUntilIdle(f.panel), "50 percent view delivered");
    const auto revision = f.field("revision");
    auto view = f.field("viewRevision");
    crop.moveAnchor(120, 80, true);
    GUI_ASSERT(f.field("viewRevision") > view && f.field("revision") == revision,
               "pan advances actual view only");
    GUI_ASSERT(f.field("renderedRevision") == -1,
               "old viewport does not satisfy current readiness");
    GUI_ASSERT(waitUntilIdle(f.panel), "pan Crop delivered");
    GUI_ASSERT(f.field("renderedViewRevision") == f.field("viewRevision"),
               "pan revalidates unchanged Navigator with current main Crop");
    GUI_ASSERT(f.set("zoom-pending", 0.5).find("APPLIED") != std::string::npos,
               "request accepted before zoom");
    crop.setZoom(1000);
    crop.setZoom(2000);
    GUI_ASSERT(crop.hasPendingNavigatorUpdate() && f.field("renderedRevision") == -1,
               "timer replacement retains pending HIGHQUAL reservation");
    pumpGuiEvents(options.adjusterMaxDelay + 100);
    GUI_ASSERT(waitUntilIdle(f.panel), "100 percent quality transition delivered");
    GUI_ASSERT(!crop.hasPendingNavigatorUpdate() && f.query().find("READY") != std::string::npos,
               "pending request completes for current view after HIGHQUAL");
    crop.setZoom(20);
    pumpGuiEvents(options.adjusterMaxDelay + 80);
    GUI_ASSERT(waitUntilIdle(f.panel), "reduced view delivered");
    crop.setZoom(1000);
    GUI_ASSERT(crop.hasPendingNavigatorUpdate(), "new quality timer reserved");
    crop.setZoom(20);
    GUI_ASSERT(!crop.hasPendingNavigatorUpdate(), "zoom-back cancels reservation");
    pumpGuiEvents(options.adjusterMaxDelay + 80);
    GUI_ASSERT(waitUntilIdle(f.panel), "cancelled quality transition settled");

    // This is the native 100% detail-window path. It may schedule a new
    // Navigator pass but must never substitute for the main Crop.
    crop.getCrop()->setListener(nullptr);
    GUI_ASSERT(f.set("detail-only", 0.6).find("APPLIED") != std::string::npos,
               "request accepted before detail window");
    GUI_ASSERT(waitWorkerFinishedWithoutMainLoop(f.panel), "Navigator-only finished");
    pumpGuiEvents(80);
    f.area()->addCropWindow();
    pumpGuiEvents(options.adjusterMaxDelay + 100);
    GUI_ASSERT(waitUntilIdle(f.panel), "100 percent detail window finished");
    std::cout << "  detail-only state: " << f.query() << " main generation=" << crop.getDisplayedContext().generation << " current=" << ipc->getProcessingContext().generation << std::endl;
    GUI_ASSERT(f.query().find("PENDING") != std::string::npos,
               "detail buffer never substitutes for main Crop readiness");
    crop.update();
    GUI_ASSERT(waitUntilIdle(f.panel), "main Crop updated");
    GUI_ASSERT(f.query().find("READY") != std::string::npos, "main Crop releases request");

    const auto unchangedRevision = f.field("revision");
    auto generation = ipc->getProcessingContext().generation;
    f.panel->getToolPanelCoordinator()->refreshPreview(rtengine::EvMonitorTransform);
    GUI_ASSERT(f.field("renderedRevision") == -1 && waitUntilIdle(f.panel),
               "monitor-transform pass invalidates readiness until delivered");
    GUI_ASSERT(ipc->getProcessingContext().generation > generation &&
               f.field("revision") == unchangedRevision,
               "monitor transform schedules Navigator without editing parameters");
    generation = ipc->getProcessingContext().generation;
    f.panel->getToolPanelCoordinator()->sharpMaskSelected(true);
    GUI_ASSERT(f.field("renderedRevision") == -1 && waitUntilIdle(f.panel),
               "sharp-mask pass waits for actual Navigator");
    GUI_ASSERT(ipc->getProcessingContext().generation > generation &&
               f.field("revision") == unchangedRevision,
               "sharp mask schedules a distinct calculation at the same edit revision");
    f.panel->getToolPanelCoordinator()->sharpMaskSelected(false);
    GUI_ASSERT(waitUntilIdle(f.panel), "sharp mask restored");

    crop.setEnabled(false, false);
    GUI_ASSERT(f.set("before-only", 0.65).find("APPLIED") != std::string::npos,
               "request accepted with main Crop withheld");
    EditorPanelTestAccess::setBeforeAfter(f.panel, true);
    pumpGuiEvents(200);
    GUI_ASSERT(waitUntilIdle(f.panel), "native Before/After view opened");
    GUI_ASSERT(f.query().find("PENDING") != std::string::npos,
               "Before view cannot replace main Crop delivery");
    EditorPanelTestAccess::setBeforeAfter(f.panel, false);
    crop.setEnabled(true, true);
    GUI_ASSERT(f.waitReady() && waitUntilIdle(f.panel),
               "main Crop releases request after Before/After closes");

    // Warnings have no render-failure meaning. Only a generation-stamped
    // fatal notification may fail the accepted mutation.
    crop.getCrop()->setListener(nullptr);
    GUI_ASSERT(f.set("fatal-notification", 0.7).find("APPLIED") != std::string::npos,
               "failure-notification fixture accepted");
    GUI_ASSERT(waitWorkerFinishedWithoutMainLoop(f.panel), "actual generation captured");
    pumpGuiEvents(80);
    f.panel->error("nonfatal preview warning");
    pumpGuiEvents(40);
    GUI_ASSERT(f.query().find("PENDING") != std::string::npos,
               "generic warning does not mark render failed");
    const auto failedContext = ipc->getProcessingContext();
    f.area()->getPreviewHandler()->imageFailed(failedContext);
    pumpGuiEvents(40);
    GUI_ASSERT(f.query().find("FAILED") != std::string::npos,
               "matching fatal callback marks accepted value FAILED");
    GUI_ASSERT(std::fabs(f.panel->getToolPanelCoordinator()->getExposureCompensation() - 0.7) < 1e-9,
               "render failure does not revert accepted parameter");
    crop.getCrop()->setListener(&crop);
    GUI_ASSERT(f.set("after-failure", 0.8).find("APPLIED") != std::string::npos,
               "next request accepted after failed preview");
    f.area()->getPreviewHandler()->imageFailed(failedContext);
    GUI_ASSERT(waitUntilIdle(f.panel), "new request finished");
    GUI_ASSERT(f.query().find("READY") != std::string::npos,
               "stale fatal callback cannot fail new calculation");

    const auto previousId = f.panel->getEditorId();
    GUI_ASSERT(f.set("closing-pending", 0.9).find("APPLIED") != std::string::npos,
               "request accepted before immediate close");
    crop.setZoom(1000);
    f.panel->close();
    GUI_ASSERT(f.open(win, dir, "t12-reopened"), "reopened with queued old callbacks cancelled");
    GUI_ASSERT(f.panel->getEditorId() != previousId, "reopen has a new identity");
    GUI_ASSERT(f.field("renderedRevision") == f.field("revision"),
               "new open displays only its own actual buffers");
    options.prevdemo = oldMode;
    std::cout << "  -> [T12] PASSED!" << std::endl;
    return true;
}

bool equalTiffPixels(const std::string &left, const std::string &right)
{
    std::unique_ptr<TIFF, decltype(&TIFFClose)> a(TIFFOpen(left.c_str(), "r"), TIFFClose);
    std::unique_ptr<TIFF, decltype(&TIFFClose)> b(TIFFOpen(right.c_str(), "r"), TIFFClose);
    if (!a || !b) {
        return false;
    }
    uint32_t aw, ah, bw, bh;
    TIFFGetField(a.get(), TIFFTAG_IMAGEWIDTH, &aw);
    TIFFGetField(a.get(), TIFFTAG_IMAGELENGTH, &ah);
    TIFFGetField(b.get(), TIFFTAG_IMAGEWIDTH, &bw);
    TIFFGetField(b.get(), TIFFTAG_IMAGELENGTH, &bh);
    const auto bytes = TIFFScanlineSize(a.get());
    if (aw != bw || ah != bh || bytes != TIFFScanlineSize(b.get())) {
        return false;
    }
    std::vector<unsigned char> av(bytes), bv(bytes);
    for (uint32_t y = 0; y < ah; ++y) {
        if (TIFFReadScanline(a.get(), av.data(), y) < 0 ||
            TIFFReadScanline(b.get(), bv.data(), y) < 0 || av != bv) {
            return false;
        }
    }
    return true;
}

class RunningExport : public rtengine::ProgressListener {
    std::mutex mutex_;
    std::condition_variable condition_;
    bool released_ = false;
    bool entered_ = false;
    std::thread worker_;
public:
    std::atomic<int> result{-1};
    RunningExport(rtengine::ProcessingJob *job, const std::string &filename)
    {
        worker_ = std::thread([this, job, filename] {
            int error = 0;
            auto *image = rtengine::processImage(job, error, this, false);
            if (image) {
                error = image->saveAsTIFF(filename, 16, false, true);
                image->free();
            } else if (!error) {
                error = 1;
            }
            result = error;
        });
    }
    void setProgress(double) override { blockOnce(); }
    void setProgressStr(const Glib::ustring &) override { blockOnce(); }
    void setProgressState(bool) override { blockOnce(); }
    void error(const Glib::ustring &) override { result = 1; }
    void blockOnce()
    {
        std::unique_lock<std::mutex> lock(mutex_);
        entered_ = true;
        condition_.notify_all();
        condition_.wait(lock, [this] { return released_; });
    }
    bool awaitStarted()
    {
        ScopedGdkUnlock unlock;
        std::unique_lock<std::mutex> lock(mutex_);
        return condition_.wait_for(lock, std::chrono::seconds(10),
                                    [this] { return entered_; });
    }
    void finish()
    {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            released_ = true;
            condition_.notify_all();
        }
        if (worker_.joinable()) {
            ScopedGdkUnlock unlock;
            worker_.join();
        }
    }
    ~RunningExport() override { finish(); }
};

bool test_t14_saved_output(RTWindow *win, const std::string &dir)
{
    std::cout << "[T14] GUI profiles, actual exports and fixed ProcessingJob" << std::endl;
    FrameFixture f{nullptr, art::liveparam::LiveParamController::getInstance()};
    GUI_ASSERT(f.open(win, dir, "t14"), "fixture opened");
    rtengine::procparams::ProcParams initial;
    GUI_ASSERT(initial.load(nullptr, ART_TEST_SOURCE_DIR "/data/test_profile.arp") == 0,
               "existing version-343 profile loaded");
    FullPartialProfile profile(initial);
    f.panel->getToolPanelCoordinator()->profileChange(&profile, rtengine::EvProfileChanged, "T14 fixture");
    GUI_ASSERT(waitUntilIdle(f.panel), "existing profile processed");
    initial.save(nullptr, dir + "/t14-initial.arp");
    f.panel->saveProfile();
    SaveFormat format("tif", 16, 16, false);
    const auto before = dir + "/t14-before.tif";
    GUI_ASSERT(f.panel->saveImmediately(before, format), "initial GUI export rendered");
    // Compare the exact pre-IPC GUI export path (getParams + shared initial
    // image) with the new committed-snapshot path. A fresh CLI decode is a
    // separate reference path and is checked independently below/in CLI runs.
    rtengine::procparams::ProcParams processed;
    auto *processor = f.panel->getImageProcessor();
    processor->getParams(&processed);
    auto *oldPath = rtengine::ProcessingJob::create(processor->getInitialImage(), processed);
    int oldError = 0;
    auto *oldImage = rtengine::processImage(oldPath, oldError, nullptr, false);
    GUI_ASSERT(oldImage && !oldError, "pre-IPC GUI snapshot export rendered");
    const auto previousPath = dir + "/t14-previous-gui-path.tif";
    const int saveError = oldImage->saveAsTIFF(previousPath, 16, false, true);
    oldImage->free();
    GUI_ASSERT(!saveError && equalTiffPixels(before, previousPath),
               "old and new GUI snapshot export paths match exactly (max_abs_diff=0)");
    std::unique_ptr<BatchQueueEntry> queue(EditorPanelTestAccess::createQueuedExport(f.panel));
    GUI_ASSERT(queue && queue->job, "actual BatchQueue entry created");
    GUI_ASSERT(queue->params.exposure.expcomp == 1.5 &&
               static_cast<rtengine::ProcessingJobImpl *>(queue->job)->pparams.exposure.expcomp == 1.5,
               "queued job owns initial parameter snapshot");
    auto *job = queue->job;
    queue->job = nullptr;
    const auto oldOutput = dir + "/t14-existing-job.tif";
    RunningExport running(job, oldOutput);
    GUI_ASSERT(running.awaitStarted(), "old job is executing before GUI mutation");
    GUI_ASSERT(f.set("output-075", 0.75).find("APPLIED") != std::string::npos,
               "external change accepted while old job executes");
    f.panel->saveProfile();
    rtengine::procparams::ProcParams saved;
    const auto sidecar = dir + "/t14.nef.arp";
    GUI_ASSERT(saved.load(nullptr, sidecar) == 0 && saved.exposure.expcomp == 0.75,
               "immediate profile save reads accepted pending parameters");
    std::unique_ptr<BatchQueueEntry> nextQueue(EditorPanelTestAccess::createQueuedExport(f.panel));
    GUI_ASSERT(nextQueue && nextQueue->job && nextQueue->params.exposure.expcomp == 0.75,
               "new BatchQueue entry captures accepted value");
    rtengine::ProcessingJob::destroy(nextQueue->job);
    nextQueue->job = nullptr;
    const auto external = dir + "/t14-external.tif";
    GUI_ASSERT(f.panel->saveImmediately(external, format), "new export uses accepted pending value");
    running.finish();
    GUI_ASSERT(running.result == 0 && equalTiffPixels(before, oldOutput),
               "already executing job preserves original pixels exactly");
    GUI_ASSERT(waitUntilIdle(f.panel), "external actual frames delivered");
    const auto externalNav = frameHash(f.area()->getPreviewHandler()->getDisplayedImage());
    const auto externalCrop = frameHash(f.area()->mainCropWindow->cropHandler.cropPixbuf);
    auto *tools = f.panel->getToolPanelCoordinator();
    GUI_ASSERT(tools->applyExternalExposure(1.5) && waitUntilIdle(f.panel), "manual control reset");
    const auto historyBefore = f.panel->getHistory()->getHistorySize();
    const auto manualRevision = f.field("revision");
    GUI_ASSERT(tools->applyExternalExposure(0.75) && waitUntilIdle(f.panel), "same native GUI edit applied");
    Glib::ustring historyText, historyValue;
    rtengine::ProcEvent historyEvent;
    rtengine::procparams::ProcParams historyParams;
    GUI_ASSERT(f.panel->getHistory()->getHistorySize() == historyBefore &&
               f.panel->getHistory()->getHistoryRow(historyBefore - 1,
                   historyText, historyValue, historyEvent, historyParams) &&
               historyEvent == rtengine::EvExpComp && historyValue == "0.75" &&
               historyParams.exposure.expcomp == 0.75 &&
               f.field("revision") == manualRevision + 1,
               "consecutive native exposure edits coalesce once and advance revision once");
    rtengine::procparams::ProcParams manual;
    f.panel->getImageProcessor()->getCommittedParams(&manual);
    GUI_ASSERT(manual == saved, "manual and external saved processing parameters match");
    GUI_ASSERT(frameHash(f.area()->getPreviewHandler()->getDisplayedImage()) == externalNav &&
               frameHash(f.area()->mainCropWindow->cropHandler.cropPixbuf) == externalCrop,
               "manual and external Navigator/main Crop bytes match");
    const auto manualOutput = dir + "/t14-manual.tif";
    GUI_ASSERT(f.panel->saveImmediately(manualOutput, format) && equalTiffPixels(external, manualOutput),
               "manual and external final output pixels match exactly");
    const auto oldId = f.panel->getEditorId();
    f.panel->close();
    auto *thumbnail = CacheManager::getInstance()->getEntry(dir + "/t14.nef");
    int error = 0;
    auto *image = rtengine::InitialImage::load(dir + "/t14.nef", true, &error, nullptr);
    GUI_ASSERT(thumbnail && image && !error, "saved GUI image reloaded");
    f.panel->open(thumbnail, image);
    GUI_ASSERT(waitUntilIdle(f.panel) && f.panel->getEditorId() != oldId,
               "saved profile reopens under new identity");
    GUI_ASSERT(f.panel->getToolPanelCoordinator()->getExposureCompensation() == 0.75,
               "GUI reread preserves accepted exposure");
    std::cout << "  T14 artifacts: " << dir << std::endl;
    std::cout << "  -> [T14] PASSED!" << std::endl;
    return true;
}

bool test_t10_actual_frames(RTWindow *win, const std::string &workDir)
{
    std::cout << "[T10] Actual Navigator and main Crop completion" << std::endl;
    auto &srv = art::liveparam::LiveParamServer::getInstance();
    auto &ctrl = art::liveparam::LiveParamController::getInstance();
    setenv("ART_LIVE_PARAM", "1", 1);
    GUI_ASSERT(srv.start(), "receiver started");
    const std::string raw = workDir + "/t10.nef";
    GUI_ASSERT(copyFile(ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef", raw),
               "RAW copied");
    auto *ep = win->epanel;
    auto *thumb = CacheManager::getInstance()->getEntry(raw);
    int err = 0;
    auto *image = rtengine::InitialImage::load(raw, true, &err, nullptr);
    GUI_ASSERT(thumb && image && !err, "RAW loaded");
    ep->open(thumb, image);
    GUI_ASSERT(waitUntilIdle(ep), "initial actual frames delivered");
    auto query = [&] {
        return ctrl.handleCommand("{\"protocolVersion\":1,\"requestId\":\"frame-query\","
            "\"op\":\"get_state\",\"editorId\":\"" + ep->getEditorId() + "\"}");
    };
    for (int step = 0; step < 2; ++step) {
        auto state = query();
        std::unique_ptr<cJSON, decltype(&cJSON_Delete)> json(cJSON_Parse(state.c_str()), cJSON_Delete);
        auto *result = cJSON_GetObjectItemCaseSensitive(json.get(), "result");
        const int rev = cJSON_GetObjectItemCaseSensitive(result, "revision")->valueint;
        const auto reply = ctrl.handleCommand("{\"protocolVersion\":1,\"requestId\":\"frame-set-" +
            std::to_string(step) + "\",\"op\":\"set_param\",\"sessionId\":\"" +
            ctrl.getSessionId() + "\",\"editorId\":\"" + ep->getEditorId() +
            "\",\"baseRevision\":" + std::to_string(rev) +
            ",\"params\":{\"Exposure.Compensation\":" + std::to_string(0.25 + step) + "}}");
        GUI_ASSERT(reply.find("\"status\":\"APPLIED\"") != std::string::npos, reply);
        GUI_ASSERT(reply.find("\"previewStatus\":\"PENDING\"") != std::string::npos,
                   "acceptance precedes delivery");
        GUI_ASSERT(waitUntilIdle(ep), "actual processing drained");
        state = query();
        std::cout << state << std::endl;
        GUI_ASSERT(state.find("\"previewStatus\":\"READY\"") != std::string::npos,
                   "actual Navigator and main Crop release pending request");
    }
    ep->close();
    srv.stop();
    std::cout << "  -> [T10] PASSED!" << std::endl;
    return true;
}

template<class Widget>
Widget *findWidget(Gtk::Widget *root)
{
    if (auto *match = dynamic_cast<Widget *>(root)) {
        return match;
    }
    auto *container = dynamic_cast<Gtk::Container *>(root);
    if (container) {
        for (auto *child : container->get_children()) {
            if (auto *match = findWidget<Widget>(child)) {
                return match;
            }
        }
    }
    return nullptr;
}

Gtk::Entry *chatInput(Gtk::Widget *root)
{
    if (auto *entry = dynamic_cast<Gtk::Entry *>(root)) {
        if (entry->get_max_length() == 8192) {
            return entry;
        }
    }
    if (auto *container = dynamic_cast<Gtk::Container *>(root)) {
        for (auto *child : container->get_children()) {
            if (auto *entry = chatInput(child)) {
                return entry;
            }
        }
    }
    return nullptr;
}

void configureChatSettings(Gtk::Grid *settings, const std::string &directory)
{
    for (auto *child : settings->get_children()) {
        if (auto *entry = dynamic_cast<Gtk::Entry *>(child)) {
            int row = -1;
            gtk_container_child_get(GTK_CONTAINER(settings->gobj()), child->gobj(),
                                    "top-attach", &row, nullptr);
            if (row == 1) { entry->set_text(ART_AGENT_PYTHON); }
            if (row == 3) { entry->set_text(ART_TEST_SOURCE_DIR); }
            if (row == 5) { entry->set_text(directory + "/absent-search-store"); }
        }
    }
}

bool test_t16_python_chat(RTWindow *win, const std::string &directory)
{
    std::cout << "[T16] Native chat -> real Python client -> GUI exposure" << std::endl;
    FrameFixture fixture{nullptr, art::liveparam::LiveParamController::getInstance()};
    GUI_ASSERT(fixture.open(win, directory, "t16"), "real editor fixture opened");
    auto *panel = findWidget<ChatPanel>(win);
    auto *input = panel ? chatInput(panel) : nullptr;
    auto *settings = panel ? findWidget<Gtk::Grid>(panel) : nullptr;
    GUI_ASSERT(input && settings, "native chat controls located");
    configureChatSettings(settings, directory);
    auto begin = [&](const Glib::ustring &text) {
        input->set_text(text);
        g_signal_emit_by_name(input->gobj(), "activate");
        return !input->get_sensitive();
    };
    auto finish = [&]() {
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(60);
        while (!input->get_sensitive() && std::chrono::steady_clock::now() < deadline) {
            pumpGuiEvents(10);
        }
        return input->get_sensitive();
    };
    const auto originalRevision = fixture.field("revision");
    const auto historySize = fixture.panel->getHistory()->getHistorySize();
    GUI_ASSERT(begin("노출을 0.125 EV로 설정해줘") && finish(),
               "native chat starts and completes the real Python request");
    std::cout << "  chat state: " << fixture.query() << std::endl;
    GUI_ASSERT(fixture.field("revision") == originalRevision + 1 &&
               std::fabs(fixture.panel->getToolPanelCoordinator()->getExposureCompensation() - 0.13) < 1e-9,
               "actual chat command changes exposure once to effective 0.13");
    GUI_ASSERT(fixture.panel->getHistory()->getHistorySize() == historySize + 1 &&
               fixture.query().find("READY") != std::string::npos,
               "native history and both preview buffers are ready");

    GUI_ASSERT(begin("/exposure 0.75"), "stale-revision request started");
    GUI_ASSERT(fixture.panel->getToolPanelCoordinator()->applyExternalExposure(1.0),
               "manual change commits before the GUI handles the socket request");
    const auto manualRevision = fixture.field("revision");
    GUI_ASSERT(finish() && waitUntilIdle(fixture.panel), "stale response delivered");
    GUI_ASSERT(fixture.field("revision") == manualRevision &&
               fixture.panel->getToolPanelCoordinator()->getExposureCompensation() == 1.0,
               "captured revision cannot silently follow later manual edits");

    const auto oldId = fixture.panel->getEditorId();
    GUI_ASSERT(begin("/exposure -0.25"), "old-target request started");
    fixture.panel->close();
    GUI_ASSERT(fixture.open(win, directory, "t16-reopened") && finish(),
               "different image reopened while the original request was in flight");
    GUI_ASSERT(fixture.panel->getEditorId() != oldId && fixture.field("revision") == 0 &&
               fixture.panel->getToolPanelCoordinator()->getExposureCompensation() == 0.0,
               "old target never applies to the reopened image");

    auto &crop = fixture.area()->mainCropWindow->cropHandler;
    crop.setZoom(1000); // Hold readiness through the native deferred quality refresh.
    const auto beforeCancel = fixture.field("revision");
    GUI_ASSERT(begin("/exposure 0.75"), "cancel scenario started");
    const auto cancelDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    while (fixture.field("revision") == beforeCancel &&
           std::chrono::steady_clock::now() < cancelDeadline) {
        pumpGuiEvents(2);
    }
    GUI_ASSERT(fixture.field("revision") == beforeCancel + 1 && !input->get_sensitive(),
               "mutation is accepted while the Python client still waits for readiness");
    Gtk::Button *cancelButton = nullptr;
    for (auto *child : panel->get_children()) {
        if (auto *box = dynamic_cast<Gtk::Box *>(child)) {
            for (auto *buttonChild : box->get_children()) {
                auto *button = dynamic_cast<Gtk::Button *>(buttonChild);
                if (button && button->get_label() == M("GENERAL_CANCEL")) {
                    cancelButton = button;
                }
            }
        }
    }
    GUI_ASSERT(cancelButton && cancelButton->get_sensitive(), "native cancel control enabled");
    cancelButton->clicked();
    pumpGuiEvents(options.adjusterMaxDelay + 100);
    GUI_ASSERT(input->get_sensitive() && waitUntilIdle(fixture.panel), "cancel returns control to the GUI");
    GUI_ASSERT(fixture.field("revision") == beforeCancel + 1 &&
               fixture.panel->getToolPanelCoordinator()->getExposureCompensation() == 0.75,
               "cancellation does not roll back or resend an already applied edit");

    fixture.panel->close();
    GUI_ASSERT(begin("/exposure 0.5") && finish(), "empty editor receives an explicit refusal");
    GUI_ASSERT(fixture.panel->getEditorId().empty() &&
               art::liveparam::LiveParamServer::getInstance().isRunning(),
               "an enabled receiver does not create a target for an empty editor");
    art::liveparam::LiveParamServer::getInstance().stop();
    unsetenv("ART_LIVE_PARAM");
    const auto rawOff = directory + "/t16-off.nef";
    GUI_ASSERT(copyFile(ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef", rawOff), "OFF RAW copied");
    auto *thumbnail = CacheManager::getInstance()->getEntry(rawOff);
    int loadError = 0;
    auto *image = rtengine::InitialImage::load(rawOff, true, &loadError, nullptr);
    GUI_ASSERT(thumbnail && image && !loadError, "OFF RAW loaded");
    fixture.panel->open(thumbnail, image);
    GUI_ASSERT(waitUntilIdle(fixture.panel), "OFF editor ready");
    const auto offValue = fixture.panel->getToolPanelCoordinator()->getExposureCompensation();
    GUI_ASSERT(begin("/exposure 0.5") && finish(), "OFF command receives an explicit refusal");
    GUI_ASSERT(!art::liveparam::LiveParamServer::getInstance().isRunning() &&
               fixture.panel->getEditorId().empty() &&
               fixture.panel->getToolPanelCoordinator()->getExposureCompensation() == offValue,
               "chat does not enable the receiver or change exposure while OFF");
    std::cout << "  -> [T16] PASSED!" << std::endl;
    return true;
}

bool test_t17_selected_tab(RTWindow *win, const std::string &directory)
{
    std::cout << "[T17] Normal GUI: selected tab and captured target" << std::endl;
    setenv("ART_LIVE_PARAM", "1", 1);
    auto &server = art::liveparam::LiveParamServer::getInstance();
    GUI_ASSERT(server.start() && win->fpanel, "normal GUI receiver started");
    auto *notebook = findWidget<Gtk::Notebook>(win);
    GUI_ASSERT(notebook && notebook->get_name() == "MainNotebook", "main notebook found");
    const auto firstPath = directory + "/t17-first.nef";
    const auto secondPath = directory + "/t17-second.nef";
    GUI_ASSERT(copyFile(ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef", firstPath) &&
               copyFile(ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef", secondPath),
               "two real RAW files copied");
    win->fpanel->fileCatalog->dirSelected(directory, firstPath);
    auto openEditor = [&](const std::string &name) -> EditorPanel * {
        const auto path = directory + "/" + name + ".nef";
        if (path != firstPath) {
            win->fpanel->fileCatalog->openFile(path);
        }
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(120);
        while (std::chrono::steady_clock::now() < deadline) {
            pumpGuiEvents(10);
            if (win->selectEditorPanel(path)) {
                auto *editor = dynamic_cast<EditorPanel *>(
                    notebook->get_nth_page(notebook->get_current_page()));
                if (editor && waitUntilIdle(editor)) {
                    return editor;
                }
                return nullptr;
            }
        }
        return nullptr;
    };
    auto *first = openEditor("t17-first");
    auto *second = openEditor("t17-second");
    auto *panel = findWidget<ChatPanel>(win);
    auto *input = panel ? chatInput(panel) : nullptr;
    auto *settings = panel ? findWidget<Gtk::Grid>(panel) : nullptr;
    GUI_ASSERT(first && second && input && settings && notebook, "two real editor tabs opened");
    configureChatSettings(settings, directory);
    auto finish = [&]() {
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(60);
        while (!input->get_sensitive() && std::chrono::steady_clock::now() < deadline) {
            pumpGuiEvents(10);
        }
        return input->get_sensitive();
    };
    GUI_ASSERT(win->selectEditorPanel(first->getFileName()), "first editor selected");
    pumpGuiEvents(options.adjusterMaxDelay + 100);
    GUI_ASSERT(waitUntilIdle(first), "selected editor initial layout settled");
    input->set_text("/exposure 0.5");
    g_signal_emit_by_name(input->gobj(), "activate");
    GUI_ASSERT(!input->get_sensitive(), "selected-tab request started");
    GUI_ASSERT(win->selectEditorPanel(second->getFileName()), "second tab selected before request dispatch");
    GUI_ASSERT(finish() && waitUntilIdle(first), "original target request finished");
    GUI_ASSERT(first->getToolPanelCoordinator()->getExposureCompensation() == 0.5 &&
               second->getToolPanelCoordinator()->getExposureCompensation() == 0.0,
               "captured target stays on first photo after tab switch");

    notebook->set_current_page(0); // Browser; there is no implicit editor fallback.
    pumpGuiEvents(30);
    input->set_text("/exposure 0.75");
    g_signal_emit_by_name(input->gobj(), "activate");
    GUI_ASSERT(finish(), "browser request receives a refusal");
    GUI_ASSERT(first->getToolPanelCoordinator()->getExposureCompensation() == 0.5 &&
               second->getToolPanelCoordinator()->getExposureCompensation() == 0.0,
               "browser request cannot choose an arbitrary open photo");
    auto *permission = findWidget<Gtk::CheckButton>(panel);
    GUI_ASSERT(permission, "normal GUI permission control found");
    // The fixture started the receiver after constructing the window; first
    // synchronize the widget, then exercise a real OFF -> ON transition.
    permission->set_active(true);
    GUI_ASSERT(waitUntilIdle(first) && waitUntilIdle(second), "both tabs tracked after enabling");
    permission->set_active(false);
    GUI_ASSERT(!server.isRunning() && first->getEditorId().empty() && second->getEditorId().empty(),
               "permission removal unregisters every open tab");
    permission->set_active(true);
    GUI_ASSERT(server.isRunning() && waitUntilIdle(first) && waitUntilIdle(second) &&
               !first->getEditorId().empty() && !second->getEditorId().empty(),
               "reenabling registers both existing editor tabs");
    GUI_ASSERT(win->selectEditorPanel(second->getFileName()), "second tracked tab selected");
    FrameFixture secondState{second, art::liveparam::LiveParamController::getInstance()};
    std::cout << "  T17 state before chat: " << secondState.query() << std::endl;
    input->set_text("/exposure 0.75");
    g_signal_emit_by_name(input->gobj(), "activate");
    const bool completed = finish() && waitUntilIdle(second);
    std::cout << "  T17 state after chat: " << secondState.query() << std::endl;
    std::function<void(Gtk::Widget *)> printLabels = [&](Gtk::Widget *widget) {
        if (auto *label = dynamic_cast<Gtk::Label *>(widget)) {
            std::cout << "  T17 label: " << label->get_text() << std::endl;
        }
        if (auto *container = dynamic_cast<Gtk::Container *>(widget)) {
            for (auto *child : container->get_children()) { printLabels(child); }
        }
    };
    if (second->getToolPanelCoordinator()->getExposureCompensation() != 0.75) {
        printLabels(panel);
    }
    GUI_ASSERT(completed &&
               first->getToolPanelCoordinator()->getExposureCompensation() == 0.5 &&
               second->getToolPanelCoordinator()->getExposureCompensation() == 0.75,
               "chat after permission cycling still edits only the selected photo");
    permission->set_active(false);
    first->close();
    second->close();
    std::cout << "  -> [T17] PASSED!" << std::endl;
    return true;
}

bool test_t18_live_exposure_setting(RTWindow *win, const std::string &directory)
{
    std::cout << "[T18] GUI live exposure permission without environment variables" << std::endl;
    auto *panel = findWidget<ChatPanel>(win);
    auto *permission = panel ? findWidget<Gtk::CheckButton>(panel) : nullptr;
    GUI_ASSERT(permission, "chat settings provide a live exposure permission checkbox");
    auto &server = art::liveparam::LiveParamServer::getInstance();
    auto &controller = art::liveparam::LiveParamController::getInstance();
    server.stop();
    unsetenv("ART_LIVE_PARAM");
    win->epanel->close();
    const auto settingsFile = Glib::build_filename(Options::user_config_dir, "artagent.ini");
    g_unlink(settingsFile.c_str());
    GUI_ASSERT(!ChatPanel::liveExposureEnabledAtStartup() && !permission->get_active(),
               "fresh settings and absent environment default to OFF");
    setenv("ART_LIVE_PARAM", "1", 1);
    GUI_ASSERT(ChatPanel::liveExposureEnabledAtStartup(), "legacy opt-in is retained before a GUI choice");
    Glib::KeyFile settings;
    settings.set_string("Chat", "python", ART_AGENT_PYTHON);
    settings.set_string("Chat", "source", ART_TEST_SOURCE_DIR);
    settings.set_string("Chat", "store", directory + "/absent-search-store");
    settings.set_string("Other", "preserved", "unchanged");
    settings.set_boolean("Chat", "live_exposure", false);
    settings.save_to_file(settingsFile);
    GUI_ASSERT(!ChatPanel::liveExposureEnabledAtStartup(), "saved OFF wins over legacy environment ON");
    settings.set_string("Chat", "live_exposure", "invalid");
    settings.save_to_file(settingsFile);
    GUI_ASSERT(!ChatPanel::liveExposureEnabledAtStartup(), "malformed permission fails closed");
    settings.remove_key("Chat", "live_exposure");
    settings.save_to_file(settingsFile);
    unsetenv("ART_LIVE_PARAM");

    const auto raw = directory + "/t18.nef";
    GUI_ASSERT(copyFile(ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef", raw), "OFF RAW copied");
    auto *thumbnail = CacheManager::getInstance()->getEntry(raw);
    int error = 0;
    auto *image = rtengine::InitialImage::load(raw, true, &error, nullptr);
    GUI_ASSERT(thumbnail && image && !error, "OFF image loaded");
    win->epanel->open(thumbnail, image);
    GUI_ASSERT(waitUntilIdle(win->epanel) && win->epanel->getEditorId().empty(), "photo starts without external registration");
    FrameFixture fixture{win->epanel, controller};
    const auto historySize = fixture.panel->getHistory()->getHistorySize();
    rtengine::procparams::ProcParams before;
    fixture.panel->getImageProcessor()->getCommittedParams(&before);
    auto *input = chatInput(panel);
    auto *grid = findWidget<Gtk::Grid>(panel);
    GUI_ASSERT(input && grid, "native chat controls located");
    configureChatSettings(grid, directory);
    permission->set_active(true);
    GUI_ASSERT(server.isRunning() && !fixture.panel->getEditorId().empty() &&
               waitUntilIdle(fixture.panel), "checkbox enables the existing photo without an environment variable");
    rtengine::procparams::ProcParams enabled;
    fixture.panel->getImageProcessor()->getCommittedParams(&enabled);
    GUI_ASSERT(before == enabled && fixture.panel->getHistory()->getHistorySize() == historySize,
               "enabling preserves all parameters and history");
    GUI_ASSERT(ChatPanel::liveExposureEnabledAtStartup(), "enabled choice survives a fresh settings read");
    const auto firstSession = controller.getSessionId();
    const auto firstEditor = fixture.panel->getEditorId();
    const auto socketPath = server.getSocketPath();
    input->set_text("노출을 0.5 EV로 설정해줘");
    g_signal_emit_by_name(input->gobj(), "activate");
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(60);
    while (!input->get_sensitive() && std::chrono::steady_clock::now() < deadline) {
        pumpGuiEvents(10);
    }
    GUI_ASSERT(input->get_sensitive() && waitUntilIdle(fixture.panel) &&
               fixture.panel->getToolPanelCoordinator()->getExposureCompensation() == 0.5 &&
               fixture.query().find("READY") != std::string::npos,
               "checkbox-enabled chat reaches the real Python client and current-view readiness");
    settings.load_from_file(settingsFile);
    GUI_ASSERT(settings.get_boolean("Chat", "live_exposure") &&
               settings.get_string("Other", "preserved") == "unchanged" &&
               settings.get_string("Chat", "python") == ART_AGENT_PYTHON,
               "sending a chat preserves permission and unrelated settings");
    permission->set_active(false);
    GUI_ASSERT(!server.isRunning() && fixture.panel->getEditorId().empty() &&
               !Glib::file_test(socketPath, Glib::FILE_TEST_EXISTS) &&
               fixture.panel->getToolPanelCoordinator()->getExposureCompensation() == 0.5 &&
               !ChatPanel::liveExposureEnabledAtStartup(),
               "disabling removes the socket and target, keeps accepted edits and saves OFF");
    GUI_ASSERT(fixture.panel->getToolPanelCoordinator()->applyExternalExposure(0.75) &&
               waitUntilIdle(fixture.panel), "normal GUI editing works after permission removal");
    GUI_ASSERT(fixture.panel->getToolPanelCoordinator()->applyExternalExposure(0.5) &&
               waitUntilIdle(fixture.panel), "normal GUI editing keeps preview processing available");
    permission->set_active(true);
    GUI_ASSERT(server.isRunning() && waitUntilIdle(fixture.panel) &&
               controller.getSessionId() != firstSession && fixture.panel->getEditorId() != firstEditor,
               "reenabling creates a fresh session and editor identity");
    const auto stale = controller.handleCommand(
        "{\"protocolVersion\":1,\"requestId\":\"t18-old\",\"op\":\"set_param\",\"sessionId\":\"" +
        firstSession + "\",\"editorId\":\"" + firstEditor +
        "\",\"baseRevision\":0,\"params\":{\"Exposure.Compensation\":1}}");
    GUI_ASSERT(stale.find("SESSION_MISMATCH") != std::string::npos &&
               fixture.panel->getToolPanelCoordinator()->getExposureCompensation() == 0.5,
               "requests from the previous permission session cannot apply");

    auto &crop = fixture.area()->mainCropWindow->cropHandler;
    crop.setZoom(1000);
    permission->set_active(false);
    permission->set_active(true);
    GUI_ASSERT(waitUntilIdle(fixture.panel), "permission cycle during a deferred zoom refresh settles");
    GUI_ASSERT(fixture.set("t18-after-zoom", 0.75).find("APPLIED") != std::string::npos &&
               fixture.waitReady(), "new session waits for the current high-quality view");

    const auto backup = settingsFile + ".backup";
    GUI_ASSERT(g_rename(settingsFile.c_str(), backup.c_str()) == 0 &&
               g_mkdir(settingsFile.c_str(), 0700) == 0, "save failure fixture created");
    permission->set_active(false);
    GUI_ASSERT(!permission->get_active() && !server.isRunning(), "save failure does not prevent disabling this run");
    permission->set_active(true);
    GUI_ASSERT(!permission->get_active() && !server.isRunning(), "save failure cannot enable the receiver");
    GUI_ASSERT(g_rmdir(settingsFile.c_str()) == 0 &&
               g_rename(backup.c_str(), settingsFile.c_str()) == 0, "settings file restored");
    // Save the final OFF choice through the actual widget, then close normally.
    permission->set_active(true);
    GUI_ASSERT(waitUntilIdle(fixture.panel), "final permission cycle settles");
    permission->set_active(false);
    fixture.panel->close();
    std::cout << "  -> [T18] PASSED!" << std::endl;
    return true;
}

bool test_t19_numeric_catalog(RTWindow *win, const std::string &directory)
{
    std::cout << "[T19] All photo-tool numeric controls and stable context" << std::endl;
    FrameFixture fixture{nullptr, art::liveparam::LiveParamController::getInstance()};
    GUI_ASSERT(fixture.open(win, directory, "t19"), "numeric catalogue photo opened");
    auto *tools = fixture.panel->getToolPanelCoordinator();
    const auto controls = tools->numericControls();
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> catalogue(cJSON_CreateArray(), cJSON_Delete);
    std::set<std::string> ids;
    std::set<std::string> families;
    for (const auto &control : controls) {
        GUI_ASSERT(ids.insert(control.id).second && !control.tool.empty() && !control.label.empty(),
                   "numeric controls have unique identities and readable names");
        GUI_ASSERT(std::isfinite(control.minimum) && std::isfinite(control.maximum) &&
                   std::isfinite(control.value) && control.minimum <= control.maximum && control.step > 0,
                   "numeric metadata comes from finite GUI ranges");
        families.insert(control.tool);
        auto *entry = cJSON_CreateObject();
        cJSON_AddStringToObject(entry, "id", control.id.c_str());
        cJSON_AddStringToObject(entry, "tool", control.tool.c_str());
        cJSON_AddStringToObject(entry, "label", control.label.c_str());
        cJSON_AddNumberToObject(entry, "kind", int(control.kind));
        cJSON_AddNumberToObject(entry, "min", control.minimum);
        cJSON_AddNumberToObject(entry, "max", control.maximum);
        cJSON_AddBoolToObject(entry, "available", control.available);
        cJSON_AddItemToArray(catalogue.get(), entry);
    }
    GUI_ASSERT(controls.size() > 150 && families.count("saturation") && families.count("whitebalance") &&
               families.count("sharpening") && families.count("crop") && families.count("resize"),
               "catalogue spans photo tools instead of an exposure whitelist");
    GUI_ASSERT(ids.size() == tools->numericControls().size(), "repeated traversal does not duplicate nested fields");
    const auto before = tools->numericContext();
    GUI_ASSERT(before.size() == 64 && before == tools->numericContext(), "unchanged GUI has a stable context digest");
    GUI_ASSERT(tools->applyExternalExposure(0.5) && waitUntilIdle(fixture.panel) &&
               before != tools->numericContext(), "GUI changes invalidate the previous numeric context");
    std::cout << "  Catalogue controls=" << controls.size() << " tools=" << families.size() << std::endl;
    std::unique_ptr<char, decltype(&cJSON_free)> catalogueBytes(
        cJSON_PrintUnformatted(catalogue.get()), cJSON_free);
    std::ofstream(directory + "/t19-controls.json") << catalogueBytes.get();
    std::cout << "  Catalogue: " << directory << "/t19-controls.json" << std::endl;
    fixture.panel->close();
    std::cout << "  -> [T19] PASSED!" << std::endl;
    return true;
}

bool test_t20_numeric_apply(RTWindow *win, const std::string &directory)
{
    std::cout << "[T20] Numeric GUI transaction, activation and linked values" << std::endl;
    FrameFixture fixture{nullptr, art::liveparam::LiveParamController::getInstance()};
    GUI_ASSERT(fixture.open(win, directory, "t20"), "numeric application photo opened");
    auto *tools = fixture.panel->getToolPanelCoordinator();
    const auto find = [&](const std::string &family, const std::string &label) {
        for (const auto &control : tools->numericControls()) {
            if (control.tool == family && control.label.find(label) != std::string::npos) {
                return control;
            }
        }
        return art::liveparam::NumericControl();
    };
    const auto saturation = find("saturation", M("TP_SATURATION_SATURATION"));
    GUI_ASSERT(saturation.owner, "saturation binding exists");
    auto *saturationTool = dynamic_cast<FoldableToolPanel *>(saturation.owner);
    saturationTool->setEnabled(false);
    saturationTool->enabledChanged();
    GUI_ASSERT(waitUntilIdle(fixture.panel), "disabled tool fixture settled");
    const auto history = fixture.panel->getHistory()->getHistorySize();
    const auto revision = fixture.field("revision");
    rtengine::procparams::ProcParams before;
    fixture.panel->getImageProcessor()->getCommittedParams(&before);
    GUI_ASSERT(tools->applyExternalNumeric(saturation.id, 101, true).error == "INVALID_VALUE" &&
               !saturationTool->getEnabled(), "invalid value cannot enable a disabled tool");
    GUI_ASSERT(tools->applyExternalNumeric(saturation.id, 20, false).error == "TOOL_DISABLED" &&
               fixture.panel->getHistory()->getHistorySize() == history &&
               fixture.field("revision") == revision, "activation needs explicit permission");
    const auto applied = tools->applyExternalNumeric(saturation.id, 20, true);
    GUI_ASSERT(applied.error.empty() && applied.value == 20 && applied.enabledTools.size() == 1 &&
               waitUntilIdle(fixture.panel), "one request enables saturation and applies its value");
    rtengine::procparams::ProcParams after;
    fixture.panel->getImageProcessor()->getCommittedParams(&after);
    auto expected = before;
    expected.saturation.enabled = true;
    expected.saturation.saturation = 20;
    GUI_ASSERT(after == expected && fixture.panel->getHistory()->getHistorySize() == history + 1 &&
               fixture.field("revision") == revision + 1,
               "activation and value create exactly one history row and committed revision");
    const auto temperature = find("whitebalance", M("TP_WBALANCE_TEMPERATURE"));
    GUI_ASSERT(!temperature.id.empty() &&
               tools->applyExternalNumeric(temperature.id, 6500, true).error.empty() &&
               waitUntilIdle(fixture.panel), "white balance follows its native numeric callback");
    fixture.panel->getImageProcessor()->getCommittedParams(&after);
    GUI_ASSERT(after.wb.temperature == 6500 && after.wb.method == rtengine::procparams::WBParams::CUSTOM_TEMP,
               "temperature update selects the native custom-temperature method");
    const auto width = find("resize", M("TP_RESIZE_W"));
    GUI_ASSERT(!width.id.empty() && tools->applyExternalNumeric(width.id, 1000, true).error.empty() &&
               waitUntilIdle(fixture.panel), "standalone numeric spin follows native resize handling");
    fixture.panel->getImageProcessor()->getCommittedParams(&after);
    GUI_ASSERT(after.resize.enabled && after.resize.width == 1000, "resize state contains the requested width");
    bool mandatoryToolChecked = false;
    for (const auto &control : tools->numericControls()) {
        auto *tool = dynamic_cast<FoldableToolPanel *>(control.owner);
        if (tool && !tool->getUseEnabled() && control.available) {
            const auto unchanged = tools->applyExternalNumeric(control.id, control.value, false);
            GUI_ASSERT(unchanged.error.empty() && unchanged.enabledTools.empty() &&
                       waitUntilIdle(fixture.panel), "always-active tools need no artificial activation");
            mandatoryToolChecked = true;
            break;
        }
    }
    GUI_ASSERT(mandatoryToolChecked, "a tool without an enable checkbox is covered");
    GUI_ASSERT(tools->applyExternalNumeric("missing-control", 1, true).error == "UNSUPPORTED_PARAM",
               "unknown controls are never treated as arbitrary profile keys");
    fixture.panel->close();
    std::cout << "  -> [T20] PASSED!" << std::endl;
    return true;
}

} // namespace

int main(int argc, char **argv)
{
    struct TestCase {
        const char *id;
        bool (*run)(RTWindow *, const std::string &);
    };
    const TestCase cases[] = {
        {"T01", test_t01_gui_state_and_off},
        {"T02", test_t02_single_external_mutation},
        {"T03", test_t03_gui_conflict_and_derived_gates},
        {"T04", testLiveParamJson},
        {"T05", testLiveParamTypes},
        {"T06", testLiveParamFrames},
        {"T07", testLiveParamQueue},
        {"T08", testLiveParamShutdown},
        {"T09", testLiveParamStartup},
        {"T10", test_t10_actual_frames},
        {"T11", test_t11_delayed_frames},
        {"T12", test_t12_views_and_lifetime},
        {"T13", test_t13_resubmit_and_conflict},
        {"T14", test_t14_saved_output},
        {"T16", test_t16_python_chat},
        {"T17", test_t17_selected_tab},
        {"T18", test_t18_live_exposure_setting},
        {"T19", test_t19_numeric_catalog},
        {"T20", test_t20_numeric_apply},
    };
    std::set<std::string> selected;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--case") != 0 || i + 1 == argc) {
            std::cerr << "Usage: " << argv[0] << " [--case Tnn ...]"
                      << std::endl;
            return 2;
        }
        const std::string id = argv[++i];
        bool found = false;
        for (const auto &test : cases) {
            found = found || id == test.id;
        }
        if (!found) {
            std::cerr << "Unknown or unimplemented test: " << id << std::endl;
            return 2;
        }
        selected.insert(id);
    }
    if (selected.count("T17") && selected.size() != 1) {
        std::cerr << "T17 runs separately in the normal tabbed GUI" << std::endl;
        return 2;
    }
    argc = 1;
    argv[1] = nullptr;

    setlocale(LC_ALL, "");
    setlocale(LC_NUMERIC, "C");

    unsetenv("ART_LIVE_PARAM");

    char tmpRootTpl[] = "/tmp/art-liveparam-guitest-XXXXXX";
    if (!mkdtemp(tmpRootTpl)) {
        std::cerr << "Failed to create temp directory" << std::endl;
        return 1;
    }
    std::string tmpRoot(tmpRootTpl);
    std::string cfgDir = tmpRoot + "/config";
    std::string cacheDir = tmpRoot + "/cache";
    std::string workDir = tmpRoot + "/work";
    std::string rtDataDir = tmpRoot + "/rtdata";
    g_mkdir_with_parents(cfgDir.c_str(), 0700);
    g_mkdir_with_parents(cacheDir.c_str(), 0700);
    g_mkdir_with_parents(workDir.c_str(), 0700);

    setenv("ART_SETTINGS", cfgDir.c_str(), 1);
    setenv("ART_CACHE", cacheDir.c_str(), 1);

    Glib::init();
    Gio::init();

    if (!stageRtData(ART_TEST_SOURCE_DIR "/rtdata", rtDataDir)) {
        std::cerr << "Failed to stage rtdata directory" << std::endl;
        return 1;
    }

    options.ART_base_dir = rtDataDir;
    creditsPath = ART_TEST_SOURCE_DIR;
    licensePath = ART_TEST_SOURCE_DIR;
    simpleEditor = selected.count("T17") == 0;
    gimpPlugin = false;
    remote = false;
    argv1 = "";
    argv2 = "";

    try {
        Options::load();
    } catch (Options::Error &e) {
        std::cerr << "Options::load failed: " << e.get_msg() << std::endl;
        return 1;
    }

    if (selected.count("T17")) {
        options.tabbedUI = true;
        options.multiDisplayMode = 0;
    }
    TIFFSetWarningHandler(nullptr);
    gdk_threads_set_lock_functions(G_CALLBACK(testGdkLockEnter),
                                   G_CALLBACK(testGdkLockLeave));
    gdk_threads_init();
    Gtk::Main kit(&argc, &argv);
    initGUIColorManagement();

    UserCommandStore::getInstance()->init(
        Glib::build_filename(options.user_config_dir, "usercommands"));
    SoundManager::init();
    wb_presets::init(options.ART_base_dir, options.user_config_dir);

    Glib::ustring iconPath = Glib::build_filename(options.ART_base_dir, "images");
    Gtk::IconTheme::get_default()->append_search_path(iconPath);

    bool allOk = false;
    {
        gdk_threads_enter();
        std::unique_ptr<RTWindow> rtWin(new RTWindow());
        rtWin->set_default_size(900, 650);
        rtWin->show_all();
        pumpGuiEvents(80);

        allOk = true;
        for (const auto &test : cases) {
            const bool normalCase = std::strcmp(test.id, "T17") == 0;
            if (normalCase == !simpleEditor && (selected.empty() || selected.count(test.id))) {
                std::cout << "Running " << test.id << std::endl;
                if (!test.run(rtWin.get(), workDir)) {
                    allOk = false;
                    break;
                }
            }
        }

        // Follow the real close protocol. A deferred quit must keep the window
        // alive until queued progress callbacks have made it closable again.
        const auto closeDeadline = std::chrono::steady_clock::now() +
            std::chrono::seconds(5);
        while (rtWin->on_delete_event(nullptr)) {
            if (std::chrono::steady_clock::now() >= closeDeadline) {
                std::cerr << "FAILED: GUI quit stayed deferred after test cleanup"
                          << std::endl;
                allOk = false;
                if (rtWin->epanel) {
                    rtWin->epanel->cleanup();
                }
                break;
            }
            pumpGuiEvents(20);
        }
        pumpGuiEvents(30);
        rtWin.reset();
        gdk_threads_leave();
    }

    art::liveparam::LiveParamServer::getInstance().stop();
    rtengine::cleanup();

    // The normal tabbed fixture runs in a fresh process so changing the
    // process-wide GUI mode cannot affect an existing standalone window.
    if (allOk && selected.empty()) {
        gchar *arguments[] = {argv[0], const_cast<gchar *>("--case"),
                              const_cast<gchar *>("T17"), nullptr};
        gchar *output = nullptr;
        gchar *errors = nullptr;
        gint status = 0;
        GError *error = nullptr;
        const bool started = g_spawn_sync(nullptr, arguments, nullptr,
            G_SPAWN_SEARCH_PATH, nullptr, nullptr, &output, &errors, &status, &error);
        if (output) { std::cout << output; }
        if (errors) { std::cerr << errors; }
        allOk = started && g_spawn_check_wait_status(status, nullptr);
        g_free(output);
        g_free(errors);
        g_clear_error(&error);
    }
    std::cout << "========================================" << std::endl;
    if (allOk) {
        std::cout << "GUI VERIFICATION SUITE PASSED!" << std::endl;
        return 0;
    }
    std::cerr << "GUI VERIFICATION SUITE FAILED!" << std::endl;
    return 1;
}
