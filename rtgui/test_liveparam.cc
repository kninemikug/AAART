#include "liveparamcontroller.h"
#include "liveparamserver.h"
#include "editorpanel.h"
#include "toolpanelcoord.h"
#include "../rtengine/cJSON.h"

#include <cassert>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <thread>
#include <unistd.h>
#include <gtkmm.h>

using namespace art::liveparam;

bool ToolPanelCoordinator::applyExternalExposure(double) { return true; }
bool ToolPanelCoordinator::isExposureEnabled() const { return true; }
double ToolPanelCoordinator::getExposureCompensation() const { return 0.0; }
std::vector<art::liveparam::NumericControl> ToolPanelCoordinator::numericControls() const { return {}; }
std::string ToolPanelCoordinator::numericContext() const { return "protocol-fixture"; }
art::liveparam::NumericApplyResult ToolPanelCoordinator::applyExternalNumeric(
    const std::string &, double, bool)
{
    art::liveparam::NumericApplyResult result;
    result.error = "UNSUPPORTED_PARAM";
    return result;
}
bool EditorPanel::can_open_now() const { return true; }

#define TEST_ASSERT(cond, msg) \
    do { \
        if (!(cond)) { \
            std::cerr << "FAILED: " << msg << " (" << #cond << ") at line " << __LINE__ << std::endl; \
            return false; \
        } \
    } while (0)

bool test_v1_inputs()
{
    std::cout << "[Test V1: Protocol Inputs & Contract Validation]" << std::endl;
    LiveParamController &ctrl = LiveParamController::getInstance();
    ctrl.init();
    std::string sess = ctrl.getSessionId();

    // 1. Oversized frame (> 64 KiB)
    std::string big(70000, 'x');
    std::string res = ctrl.handleCommand(big);
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Oversized frame rejected");
    TEST_ASSERT(res.find("64 KiB") != std::string::npos, "Error mentions 64 KiB");

    // 2. Malformed JSON
    res = ctrl.handleCommand("{invalid json}");
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Malformed JSON rejected");

    // 3. Duplicate JSON keys
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"get_state\"}");
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Duplicate keys rejected");

    // 4. Missing protocolVersion
    res = ctrl.handleCommand("{\"requestId\": \"r1\", \"op\": \"get_state\"}");
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Missing protocolVersion rejected");

    // 5. Unsupported protocolVersion != 1
    res = ctrl.handleCommand("{\"protocolVersion\": 2, \"requestId\": \"r1\", \"op\": \"get_state\"}");
    TEST_ASSERT(res.find("UNSUPPORTED_VERSION") != std::string::npos, "Unsupported version rejected");

    // 6. Missing or invalid requestId
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"op\": \"get_state\"}");
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Missing requestId rejected");

    std::string longReqId(130, 'a');
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"" + longReqId + "\", \"op\": \"get_state\"}");
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Too long requestId rejected");

    // 7. Unknown fields in get_state
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"get_state\", \"foo\": \"bar\"}");
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Unknown fields in get_state rejected");

    // 8. Unsupported op
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"unknown_op\"}");
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Unsupported op rejected");

    // 9. set_param with unknown field
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"set_param\", \"sessionId\": \"" + sess + "\", \"editorId\": \"e1\", \"baseRevision\": 0, \"params\": {\"Exposure.Compensation\": 0.0}, \"extra\": 1}");
    TEST_ASSERT(res.find("INVALID_REQUEST") != std::string::npos, "Unknown field in set_param rejected");

    // 10. set_param with unsupported param key
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"set_param\", \"sessionId\": \"" + sess + "\", \"editorId\": \"e1\", \"baseRevision\": 0, \"params\": {\"Exposure.Compensation\": 0.0, \"Exposure.Black\": 0.1}}");
    TEST_ASSERT(res.find("UNSUPPORTED_PARAM") != std::string::npos, "Unsupported param key rejected");

    // 11. set_param with string value for Exposure.Compensation
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"set_param\", \"sessionId\": \"" + sess + "\", \"editorId\": \"e1\", \"baseRevision\": 0, \"params\": {\"Exposure.Compensation\": \"0.5\"}}");
    TEST_ASSERT(res.find("INVALID_VALUE") != std::string::npos, "String number rejected");

    // 12. set_param with out-of-range value
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"set_param\", \"sessionId\": \"" + sess + "\", \"editorId\": \"e1\", \"baseRevision\": 0, \"params\": {\"Exposure.Compensation\": 12.01}}");
    TEST_ASSERT(res.find("INVALID_VALUE") != std::string::npos, "Value > 12 rejected");

    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"set_param\", \"sessionId\": \"" + sess + "\", \"editorId\": \"e1\", \"baseRevision\": 0, \"params\": {\"Exposure.Compensation\": -12.01}}");
    TEST_ASSERT(res.find("INVALID_VALUE") != std::string::npos, "Value < -12 rejected");

    std::cout << "  -> V1 contract checks PASSED!" << std::endl;
    return true;
}

bool test_v5_lifecycle_cache()
{
    std::cout << "[Test V5: Session, Editor, Revision & Flow Control]" << std::endl;
    LiveParamController &ctrl = LiveParamController::getInstance();
    ctrl.init();
    std::string sess = ctrl.getSessionId();

    // 1. Session mismatch
    std::string res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"set_param\", \"sessionId\": \"run-wrong\", \"editorId\": \"e1\", \"baseRevision\": 0, \"params\": {\"Exposure.Compensation\": 0.0}}");
    TEST_ASSERT(res.find("SESSION_MISMATCH") != std::string::npos, "Session mismatch rejected");

    // 2. Editor not found
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"set_param\", \"sessionId\": \"" + sess + "\", \"editorId\": \"editor-nonexistent\", \"baseRevision\": 0, \"params\": {\"Exposure.Compensation\": 0.0}}");
    TEST_ASSERT(res.find("EDITOR_NOT_FOUND") != std::string::npos, "Editor not found rejected");

    // 3. get_state editor list (empty)
    res = ctrl.handleCommand("{\"protocolVersion\": 1, \"requestId\": \"r1\", \"op\": \"get_state\"}");
    TEST_ASSERT(res.find("\"status\":\"OK\"") != std::string::npos, "get_state editor list returns OK");
    TEST_ASSERT(res.find("\"editors\":[]") != std::string::npos, "editors list is empty");

    std::cout << "  -> V5 checks PASSED!" << std::endl;
    return true;
}

bool test_v7_mac_server()
{
    std::cout << "[Test V7: macOS & Default OFF Behavior]" << std::endl;

    // 1. Without ART_LIVE_PARAM env var
    unsetenv("ART_LIVE_PARAM");
    LiveParamServer &srv = LiveParamServer::getInstance();
    bool started = srv.start();
    TEST_ASSERT(!started, "Server does NOT start when ART_LIVE_PARAM is unset");
    TEST_ASSERT(!srv.isRunning(), "Server is not running");

    // 2. With ART_LIVE_PARAM=0
    setenv("ART_LIVE_PARAM", "0", 1);
    started = srv.start();
    TEST_ASSERT(!started, "Server does NOT start when ART_LIVE_PARAM is 0");
    TEST_ASSERT(!srv.isRunning(), "Server is not running");

    // 3. With ART_LIVE_PARAM=1
    setenv("ART_LIVE_PARAM", "1", 1);
    started = srv.start();
    TEST_ASSERT(started, "Server starts successfully when ART_LIVE_PARAM=1");
    TEST_ASSERT(srv.isRunning(), "Server is running");

    std::string sockPath = srv.getSocketPath();
    TEST_ASSERT(!sockPath.empty(), "Socket path is non-empty");

    // Verify socket file permissions (0600)
    struct stat st;
    int statRet = stat(sockPath.c_str(), &st);
    TEST_ASSERT(statRet == 0, "Socket file exists on disk");
    TEST_ASSERT(S_ISSOCK(st.st_mode), "File is a Unix socket");
    TEST_ASSERT((st.st_mode & 0777) == 0600, "Socket mode is 0600");

    // Verify directory permissions (0700)
    std::string dir = sockPath.substr(0, sockPath.find_last_of('/'));
    statRet = stat(dir.c_str(), &st);
    TEST_ASSERT(statRet == 0, "Socket dir exists on disk");
    TEST_ASSERT(S_ISDIR(st.st_mode), "Path is a directory");
    TEST_ASSERT((st.st_mode & 0777) == 0700, "Directory mode is 0700");

    // 4. Connect via Unix domain socket in a client thread, while main thread runs glib events
    std::atomic<bool> clientDone{false};
    bool clientSuccess = false;
    std::string clientResp;

    std::thread clientThread([&]() {
        int clientFd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (clientFd < 0) return;

        struct sockaddr_un addr;
        std::memset(&addr, 0, sizeof(addr));
        addr.sun_family = AF_UNIX;
        std::strncpy(addr.sun_path, sockPath.c_str(), sizeof(addr.sun_path) - 1);

        if (connect(clientFd, reinterpret_cast<struct sockaddr *>(&addr), sizeof(addr)) != 0) {
            close(clientFd);
            return;
        }

        std::string req = "{\"protocolVersion\": 1, \"requestId\": \"sock-req-1\", \"op\": \"get_state\"}\n";
        send(clientFd, req.c_str(), req.size(), 0);

        char buf[4096];
        std::memset(buf, 0, sizeof(buf));
        ssize_t n = recv(clientFd, buf, sizeof(buf) - 1, 0);
        if (n > 0) {
            clientResp = std::string(buf, n);
            clientSuccess = true;
        }
        close(clientFd);
        clientDone = true;
    });

    // Pump main context so gdk_threads_add_idle_full dispatches handleCommand
    while (!clientDone.load()) {
        g_main_context_iteration(nullptr, FALSE);
        usleep(1000);
    }
    clientThread.join();

    TEST_ASSERT(clientSuccess, "Client communication succeeded");
    TEST_ASSERT(clientResp.find("\"status\":\"OK\"") != std::string::npos, "Socket response contains status OK");
    TEST_ASSERT(clientResp.find("sock-req-1") != std::string::npos, "Socket response contains requestId");

    // 5. Stop server
    srv.stop();
    TEST_ASSERT(!srv.isRunning(), "Server stopped");

    // Verify socket file unlinked
    statRet = stat(sockPath.c_str(), &st);
    TEST_ASSERT(statRet != 0, "Socket file unlinked after stop");

    unsetenv("ART_LIVE_PARAM");
    std::cout << "  -> V7 checks PASSED!" << std::endl;
    return true;
}

int main(int argc, char **argv)
{
    Gtk::Main m(&argc, &argv);

    std::cout << "========================================" << std::endl;
    std::cout << "Running ART Live Param Verification Suite" << std::endl;
    std::cout << "========================================" << std::endl;

    bool ok = true;
    ok = ok && test_v1_inputs();
    ok = ok && test_v5_lifecycle_cache();
    ok = ok && test_v7_mac_server();

    if (ok) {
        std::cout << "========================================" << std::endl;
        std::cout << "ALL VERIFICATION TESTS PASSED SUCCESSFULLY!" << std::endl;
        std::cout << "========================================" << std::endl;
        return 0;
    } else {
        std::cerr << "SOME TESTS FAILED!" << std::endl;
        return 1;
    }
}
