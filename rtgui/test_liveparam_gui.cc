#include "cachemanager.h"
#include "cropwindow.h"
#include "editorpanel.h"
#include "extprog.h"
#include "guiutils.h"
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
#include <thread>
#include <tiffio.h>
#include <unistd.h>

extern Options options;

// Globals expected by rtgui_core (defined in main.cc for ART executable)
Glib::ustring creditsPath;
Glib::ustring licensePath;
Glib::ustring argv1;
Glib::ustring argv2;
bool simpleEditor = true;
bool gimpPlugin = false;
bool remote = false;
bool is_session = false;

namespace {

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

} // namespace

int main(int argc, char **argv)
{
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

        allOk = test_t01_gui_state_and_off(rtWin.get(), workDir);

        rtWin->on_delete_event(nullptr);
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
