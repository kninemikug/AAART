#include "cachemanager.h"
#include "cropwindow.h"
#include "editorpanel.h"
#include "extprog.h"
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
#include "../rtengine/refreshmap.h"

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

namespace art {
namespace liveparam {
struct LiveParamControllerTestAccess {
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
        {"T13", test_t13_resubmit_and_conflict},
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
    simpleEditor = true;
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
            if (selected.empty() || selected.count(test.id)) {
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
                rtWin->epanel->cleanup();
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

    std::cout << "========================================" << std::endl;
    if (allOk) {
        std::cout << "GUI VERIFICATION SUITE PASSED!" << std::endl;
        return 0;
    }
    std::cerr << "GUI VERIFICATION SUITE FAILED!" << std::endl;
    return 1;
}
