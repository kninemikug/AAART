#include "test_liveparam_socket.h"
#include "liveparamcontroller.h"
#include "liveparamserver.h"
#include "cachemanager.h"
#include "editorpanel.h"
#include "history.h"
#include "rtwindow.h"
#include "toolpanelcoord.h"
#include "../rtengine/cJSON.h"

#include <chrono>
#include <cerrno>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <vector>
#include <thread>
#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <glib.h>

namespace art {
namespace liveparam {
struct LiveParamServerTestAccess {
    static bool authenticate(int fd) { return LiveParamServer::authenticatePeer(fd); }
};
} // namespace liveparam
} // namespace art

namespace {

void pump()
{
    while (g_main_context_pending(nullptr)) {
        g_main_context_iteration(nullptr, false);
    }
    gdk_threads_leave();
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
    gdk_threads_enter();
}

class Client {
public:
    explicit Client(const std::string &path)
    {
        fd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (fd < 0) {
            return;
        }
        fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK);
        sockaddr_un addr{};
        addr.sun_family = AF_UNIX;
        if (path.size() >= sizeof(addr.sun_path)) {
            close(fd);
            fd = -1;
            return;
        }
        std::memcpy(addr.sun_path, path.c_str(), path.size() + 1);
        int result = connect(fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr));
        if (result < 0 && errno == EINPROGRESS) {
            pollfd ready{fd, POLLOUT, 0};
            int error = 0;
            socklen_t size = sizeof(error);
            result = poll(&ready, 1, 2000) > 0 &&
                getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &size) == 0 && !error ? 0 : -1;
        }
        if (result) {
            close(fd);
            fd = -1;
        }
        if (fd >= 0) {
            int yes = 1;
            setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, sizeof(yes));
        }
    }
    ~Client()
    {
        if (fd >= 0) {
            close(fd);
        }
    }
    Client(const Client &) = delete;
    Client &operator=(const Client &) = delete;
    bool sendText(const std::string &text)
    {
        size_t sent = 0;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (sent < text.size()) {
            const auto n = send(fd, text.data() + sent, text.size() - sent, 0);
            if (n <= 0) {
                if (n < 0 && (errno == EAGAIN || errno == EINTR) &&
                    std::chrono::steady_clock::now() < deadline) {
                    pollfd ready{fd, POLLOUT, 0};
                    poll(&ready, 1, 20);
                    continue;
                }
                return false;
            }
            sent += n;
        }
        return true;
    }
    bool tryLine(std::string &line)
    {
        char bytes[4096];
        const auto count = recv(fd, bytes, sizeof(bytes), MSG_DONTWAIT);
        if (count > 0) {
            input_.append(bytes, count);
        } else if (count == 0) {
            eof = true;
        }
        const auto end = input_.find('\n');
        if (end == std::string::npos) {
            return false;
        }
        line = input_.substr(0, end);
        input_.erase(0, end + 1);
        return true;
    }
    std::string line(bool dispatchGui = true, int timeoutMs = 3000)
    {
        const auto deadline = std::chrono::steady_clock::now() +
            std::chrono::milliseconds(timeoutMs);
        do {
            std::string result;
            if (tryLine(result)) {
                return result;
            }
            if (eof) {
                return "";
            }
            if (dispatchGui) {
                pump();
            } else {
                std::this_thread::sleep_for(std::chrono::milliseconds(2));
            }
        } while (std::chrono::steady_clock::now() < deadline);
        return "";
    }
    int fd = -1;
    bool eof = false;
private:
    std::string input_;
};

// A broken stop must fail the test process, rather than leaving the GUI and
// the test runner waiting for a client that the test intentionally keeps open.
class ShutdownWatchdog {
public:
    ShutdownWatchdog(): worker_([this] {
        std::unique_lock<std::mutex> lock(mutex_);
        if (!condition_.wait_for(lock, std::chrono::seconds(5),
                                 [this] { return done_; })) {
            std::cerr << "T08 FAILED: server stop exceeded 5 seconds" << std::endl;
            std::_Exit(81);
        }
    }) {}
    ~ShutdownWatchdog()
    {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            done_ = true;
        }
        condition_.notify_all();
        worker_.join();
    }
private:
    std::mutex mutex_;
    std::condition_variable condition_;
    bool done_ = false;
    std::thread worker_;
};

using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;

Json parse(const std::string &text)
{
    return Json(cJSON_ParseWithOpts(text.c_str(), nullptr, true), cJSON_Delete);
}

std::string print(cJSON *json)
{
    char *bytes = cJSON_PrintUnformatted(json);
    const std::string result = bytes ? bytes : "";
    cJSON_free(bytes);
    return result;
}

std::string stringField(cJSON *json, const char *key)
{
    auto *value = cJSON_GetObjectItemCaseSensitive(json, key);
    return cJSON_IsString(value) ? value->valuestring : "";
}

std::string request(const std::string &id, const char *op = "get_state",
                    const std::string &editor = "", const std::string &session = "",
                    int64_t revision = 0, double value = 0.0)
{
    Json root(cJSON_CreateObject(), cJSON_Delete);
    cJSON_AddNumberToObject(root.get(), "protocolVersion", 1);
    cJSON_AddStringToObject(root.get(), "requestId", id.c_str());
    cJSON_AddStringToObject(root.get(), "op", op);
    if (!editor.empty()) {
        cJSON_AddStringToObject(root.get(), "editorId", editor.c_str());
    }
    if (!session.empty()) {
        cJSON_AddStringToObject(root.get(), "sessionId", session.c_str());
    }
    if (std::strcmp(op, "set_param") == 0) {
        cJSON_AddNumberToObject(root.get(), "baseRevision", revision);
        auto *params = cJSON_AddObjectToObject(root.get(), "params");
        cJSON_AddNumberToObject(params, "Exposure.Compensation", value);
    }
    return print(root.get());
}

struct ServerScope {
    ServerScope()
    {
        setenv("ART_LIVE_PARAM", "1", 1);
        started = art::liveparam::LiveParamServer::getInstance().start();
    }
    ~ServerScope()
    {
        ShutdownWatchdog watchdog;
        art::liveparam::LiveParamServer::getInstance().stop();
        unsetenv("ART_LIVE_PARAM");
    }
    std::string path() const
    {
        return art::liveparam::LiveParamServer::getInstance().getSocketPath();
    }
    bool started = false;
};

struct EditorScope {
    EditorScope(RTWindow *window, const std::string &dir, const std::string &name)
        : panel(window->epanel)
    {
        path = dir + "/" + name + ".nef";
        {
            std::ifstream input(ART_TEST_SOURCE_DIR "/data/fivek_sample/sample1.nef",
                                std::ios::binary);
            std::ofstream output(path, std::ios::binary);
            if (!input || !output) {
                return;
            }
            output << input.rdbuf();
        }
        auto *thumbnail = CacheManager::getInstance()->getEntry(path);
        if (!thumbnail) {
            return;
        }
        int error = 0;
        auto *image = rtengine::InitialImage::load(path, true, &error, nullptr);
        if (!image || error) {
            return;
        }
        panel->open(thumbnail, image);
        opened = true;
        const auto deadline = std::chrono::steady_clock::now() +
            std::chrono::seconds(120);
        do {
            pump();
        } while (panel->getIsProcessing() && std::chrono::steady_clock::now() < deadline);
        ready = !panel->getIsProcessing();
    }
    ~EditorScope()
    {
        if (opened) {
            panel->close();
        }
    }
    EditorPanel *panel;
    std::string path;
    bool opened = false;
    bool ready = false;
};

std::string rpc(Client &client, const std::string &json)
{
    return client.sendText(json + "\n") ? client.line() : "";
}

bool check(bool condition, const char *message)
{
    std::cout << (condition ? "  [PASS] " : "  [FAIL] ") << message << std::endl;
    return condition;
}

} // namespace

bool testLiveParamShutdown(RTWindow *, const std::string &)
{
    using namespace art::liveparam;
    std::cout << "[T08] Shutdown with open idle/partial/GUI-pending clients" << std::endl;
    auto &server = LiveParamServer::getInstance();
    setenv("ART_LIVE_PARAM", "1", 1);
    for (int scenario = 0; scenario < 3; ++scenario) {
        if (!server.start()) {
            std::cerr << "T08 FAILED: could not start server" << std::endl;
            return false;
        }
        const std::string path = server.getSocketPath();
        Client client(path);
        if (client.fd < 0 ||
            (scenario == 1 && !client.sendText("{\"protocolVersion\":")) ||
            (scenario == 2 && !client.sendText(
                "{\"protocolVersion\":1,\"requestId\":\"stop-pending\","
                "\"op\":\"get_state\"}\n"))) {
            std::cerr << "T08 FAILED: client setup" << std::endl;
            return false;
        }
        // Deliberately do not dispatch GUI callbacks or close the client.
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        const auto start = std::chrono::steady_clock::now();
        {
            ShutdownWatchdog watchdog;
            server.stop();
        }
        const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start).count();
        if (ms >= 5000 || server.isRunning() || access(path.c_str(), F_OK) == 0) {
            std::cerr << "T08 FAILED: resources remained after stop" << std::endl;
            return false;
        }
        server.stop();
        while (g_main_context_pending(nullptr)) {
            g_main_context_iteration(nullptr, false);
        }
        std::cout << "  [PASS] scenario=" << scenario << " stop=" << ms
                  << "ms, client stayed open" << std::endl;
    }
    unsetenv("ART_LIVE_PARAM");
    return true;
}


bool testLiveParamJson(RTWindow *window, const std::string &dir)
{
    std::cout << "[T04] JSON round trip and get_state schema" << std::endl;
    ServerScope server;
    if (!server.started) {
        return false;
    }
    EditorScope editor(window, dir, "t04_따옴표\"_역슬래시\\_개행\n");
    if (!editor.ready) {
        return false;
    }
    Client client(server.path());
    const std::string id = "한글\"\\\n요청";
    auto list = parse(rpc(client, request(id)));
    if (!check(list && stringField(list.get(), "requestId") == id &&
                   cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(list.get(), "editorId")),
               "Editor list echoes escaped Unicode requestId and null editorId")) {
        return false;
    }
    auto *result = cJSON_GetObjectItemCaseSensitive(list.get(), "result");
    auto *editors = cJSON_GetObjectItemCaseSensitive(result, "editors");
    if (!check(cJSON_GetArraySize(editors) == 1 &&
                   stringField(cJSON_GetArrayItem(editors, 0), "name") ==
                       Glib::path_get_basename(editor.path),
               "Filename quotes, backslash and newline survive JSON serialization")) {
        return false;
    }
    auto &controller = art::liveparam::LiveParamController::getInstance();
    const auto editorId = editor.panel->getEditorId();
    auto state = parse(rpc(client, request(id, "get_state", editorId)));
    result = cJSON_GetObjectItemCaseSensitive(state.get(), "result");
    auto *supported = cJSON_GetObjectItemCaseSensitive(result, "supportedParams");
    auto *exposure = cJSON_GetObjectItemCaseSensitive(supported, "Exposure.Compensation");
    if (!check(state && stringField(state.get(), "editorId") == editorId &&
                   cJSON_IsObject(exposure) &&
                   cJSON_IsBool(cJSON_GetObjectItemCaseSensitive(exposure, "enabled")) &&
                   cJSON_IsNumber(cJSON_GetObjectItemCaseSensitive(exposure, "value")) &&
                   cJSON_GetObjectItemCaseSensitive(result, "ppVersion"),
               "Single-editor state includes supportedParams and ppVersion")) {
        return false;
    }
    const auto revision = cJSON_GetObjectItemCaseSensitive(result, "revision")->valuedouble;
    auto applied = parse(rpc(client, request(id, "set_param", editorId,
                                            controller.getSessionId(), revision, 0.125)));
    auto invalid = parse(rpc(client, request(id + "-error", "set_param", editorId,
                                            controller.getSessionId(), revision, 20.0)));
    return check(applied && stringField(applied.get(), "status") == "APPLIED" &&
                     stringField(applied.get(), "requestId") == id && invalid &&
                     stringField(invalid.get(), "requestId") == id + "-error" &&
                     stringField(cJSON_GetObjectItemCaseSensitive(invalid.get(), "error"),
                                 "code") == "INVALID_VALUE",
                 "Successful mutation and error responses round trip escaped requestId");
}

bool testLiveParamTypes(RTWindow *window, const std::string &dir)
{
    std::cout << "[T05] Complete JSON and strict input types" << std::endl;
    ServerScope server;
    if (!server.started) {
        return false;
    }
    EditorScope editor(window, dir, "t05");
    if (!editor.ready) {
        return false;
    }
    Client client(server.path());
    const auto editorId = editor.panel->getEditorId();
    const auto session = art::liveparam::LiveParamController::getInstance().getSessionId();
    const auto query = request("types-state", "get_state", editorId);
    auto initial = parse(rpc(client, query));
    auto *result = cJSON_GetObjectItemCaseSensitive(initial.get(), "result");
    if (!result) {
        return false;
    }
    const auto revision = cJSON_GetObjectItemCaseSensitive(result, "revision")->valuedouble;
    const auto history = editor.panel->getHistory()->getHistorySize();
    rtengine::procparams::ProcParams before;
    editor.panel->getImageProcessor()->getCommittedParams(&before);
    const std::string queryBase = request("bad", "get_state", editorId);
    const std::vector<std::pair<std::string, std::string>> invalid = {
        {"{\"protocolVersion\":1.5,\"requestId\":\"bad\",\"op\":\"get_state\"}", "INVALID_REQUEST"},
        {"{\"protocolVersion\":2,\"requestId\":\"bad\",\"op\":\"get_state\"}", "UNSUPPORTED_VERSION"},
        {"{\"protocolVersion\":1.00000000000000001,\"requestId\":\"bad\",\"op\":\"get_state\"}", "INVALID_REQUEST"},
        {queryBase + " trailing", "INVALID_REQUEST"},
        {queryBase + "{}", "INVALID_REQUEST"},
        {"{\"protocolVersion\":1,\"requestId\":\"bad\",\"op\":\"get_state\",\"editorId\":7}", "INVALID_REQUEST"},
        {"{\"protocolVersion\":1,\"requestId\":\"bad\",\"op\":\"get_state\",\"sessionId\":false}", "INVALID_REQUEST"},
        {"{\"protocolVersion\":1,\"requestId\":\"bad\",\"op\":\"get_state\",\"mutationRequestId\":[]}", "INVALID_REQUEST"},
        {"{\"protocolVersion\":1,\"requestId\":\"bad\",\"requestId\":\"again\",\"op\":\"get_state\"}", "INVALID_REQUEST"},
        {"{\"protocolVersion\":01,\"requestId\":\"bad\",\"op\":\"get_state\"}", "INVALID_REQUEST"},
        {"{\"protocolVersion\":1,\"requestId\":\"bad\\u0000suffix\",\"op\":\"get_state\"}", "INVALID_REQUEST"}
    };
    for (const auto &entry : invalid) {
        auto response = parse(rpc(client, entry.first));
        if (!check(response && stringField(cJSON_GetObjectItemCaseSensitive(response.get(), "error"),
                                           "code") == entry.second,
                   "Malformed, trailing or wrongly typed request is rejected")) {
            std::cerr << "  request=" << entry.first << std::endl;
            return false;
        }
    }
    for (const char *number : {"-1", "0.5", "9007199254740992", "1e100", "1.00000000000000001", "1e-999"}) {
        auto json = request("revision-bad", "set_param", editorId, session, 0, 0.3);
        const auto start = json.find("\"baseRevision\":") + std::strlen("\"baseRevision\":");
        const auto end = json.find(',', start);
        json.replace(start, end - start, number);
        auto response = parse(rpc(client, json));
        if (!check(response && stringField(cJSON_GetObjectItemCaseSensitive(response.get(), "error"),
                                           "code") == "INVALID_REQUEST",
                   "Fractional, negative or inexact baseRevision is rejected")) {
            return false;
        }
    }
    rtengine::procparams::ProcParams after;
    editor.panel->getImageProcessor()->getCommittedParams(&after);
    auto state = parse(rpc(client, query));
    result = cJSON_GetObjectItemCaseSensitive(state.get(), "result");
    if (!check(after == before && editor.panel->getHistory()->getHistorySize() == history &&
                   cJSON_GetObjectItemCaseSensitive(result, "revision")->valuedouble == revision,
               "Rejected inputs leave parameters, history and revision unchanged")) {
        return false;
    }
    std::string unicodeId;
    for (int i = 0; i < 128; ++i) {
        unicodeId += "가";
    }
    auto validId = parse(rpc(client, request(unicodeId)));
    auto longId = parse(rpc(client, request(unicodeId + "가")));
    if (!check(stringField(validId.get(), "requestId") == unicodeId &&
                   stringField(cJSON_GetObjectItemCaseSensitive(longId.get(), "error"), "code") == "INVALID_REQUEST",
               "requestId counts Unicode characters: 128 accepted, 129 rejected")) {
        return false;
    }
    for (const char *number : {"2147483648", "9007199254740991"}) {
        auto json = request("large-int", "set_param", editorId, session, 0, 0.3);
        const auto start = json.find("\"baseRevision\":") + std::strlen("\"baseRevision\":");
        json.replace(start, json.find(',', start) - start, number);
        auto response = parse(rpc(client, json));
        if (!check(stringField(cJSON_GetObjectItemCaseSensitive(response.get(), "error"), "code") ==
                       "REVISION_CONFLICT",
                   "Large exact integers pass type validation without int32 truncation")) {
            return false;
        }
    }
    for (int value : {-12, 12}) {
        auto state = parse(rpc(client, query));
        auto *result = cJSON_GetObjectItemCaseSensitive(state.get(), "result");
        const auto revision = cJSON_GetObjectItemCaseSensitive(result, "revision")->valuedouble;
        auto response = parse(rpc(client, request("boundary-" + std::to_string(value),
                                                "set_param", editorId, session, revision, value)));
        auto *applied = cJSON_GetObjectItemCaseSensitive(response.get(), "result");
        auto *effective = cJSON_GetObjectItemCaseSensitive(applied, "effectiveParams");
        auto *exposure = cJSON_GetObjectItemCaseSensitive(effective, "Exposure.Compensation");
        if (!check(stringField(response.get(), "status") == "APPLIED" && exposure &&
                       exposure->valuedouble == value,
                   "Inclusive exposure boundary applies through the real GUI")) {
            return false;
        }
        // Completion generations are tested in T10-T12. A normal GUI edit
        // supersedes this pending mutation so the other boundary can be tested.
        editor.panel->getToolPanelCoordinator()->applyExternalExposure(0.0);
    }
    return true;
}

bool testLiveParamFrames(RTWindow *, const std::string &)
{
    std::cout << "[T06] Bounded and fragmented socket frames" << std::endl;
    ServerScope server;
    if (!server.started) {
        return false;
    }
    const std::string query = request("frames");
    {
        Client client(server.path());
        if (!client.sendText(query.substr(0, 9)) ||
            !client.sendText(query.substr(9) + "\n") ||
            stringField(parse(client.line()).get(), "status") != "OK") {
            return check(false, "Fragmented frame reassembly");
        }
        std::string maximum = query + std::string(65536 - query.size(), ' ');
        if (!check(client.sendText(maximum + "\n") &&
                       stringField(parse(client.line()).get(), "status") == "OK",
                   "Exactly 64 KiB JSON payload is accepted")) {
            return false;
        }
    }
    for (bool withLf : {false, true}) {
        Client client(server.path());
        const std::string oversized = std::string(65537, 'x') + (withLf ? "\n" : "");
        client.sendText(oversized);
        auto response = parse(client.line(false));
        if (!check(response &&
                       stringField(cJSON_GetObjectItemCaseSensitive(response.get(), "error"),
                                   "code") == "INVALID_REQUEST",
                   "Over-limit input is rejected without dispatching GUI, with or without LF")) {
            return false;
        }
    }
    return true;
}

bool testLiveParamQueue(RTWindow *, const std::string &)
{
    std::cout << "[T07] Atomic GUI queue limit and per-connection serialization" << std::endl;
    ServerScope server;
    if (!server.started) {
        return false;
    }
    std::vector<std::unique_ptr<Client>> clients;
    std::vector<bool> received(34, false);
    for (int i = 0; i < 34; ++i) {
        clients.emplace_back(new Client(server.path()));
        if (!clients.back()->sendText(request("queue-" + std::to_string(i)) + "\n")) {
            return false;
        }
    }
    int busy = 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (std::chrono::steady_clock::now() < deadline && busy < 2) {
        for (size_t i = 0; i < clients.size(); ++i) {
            std::string line;
            if (!received[i] && clients[i]->tryLine(line)) {
                auto response = parse(line);
                if (stringField(cJSON_GetObjectItemCaseSensitive(response.get(), "error"), "code") != "BUSY") {
                    return false;
                }
                received[i] = true;
                ++busy;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    if (!check(busy == 2, "GUI-paused 34 connections reserve exactly 32 commands and reject two")) {
        return false;
    }
    int completed = 0;
    for (size_t i = 0; i < clients.size(); ++i) {
        if (!received[i]) {
            auto response = parse(clients[i]->line());
            if (stringField(response.get(), "status") != "OK") {
                return false;
            }
            ++completed;
        }
    }
    Client serial(server.path());
    if (!serial.sendText(request("first") + "\n" + request("second") + "\n")) {
        return false;
    }
    auto first = parse(serial.line());
    auto second = parse(serial.line());
    return check(completed == 32 && stringField(first.get(), "requestId") == "first" &&
                     stringField(second.get(), "requestId") == "second" &&
                     stringField(parse(rpc(serial, request("recovered"))).get(), "status") == "OK",
                 "All reservations recover and one connection processes requests in order");
}


bool testLiveParamStartup(RTWindow *window, const std::string &dir)
{
    using namespace art::liveparam;
    std::cout << "[T09] OFF gate, kernel peer credentials, permissions and reconnect" << std::endl;
    auto &server = LiveParamServer::getInstance();
    server.stop();
    const char *values[] = {nullptr, "", "0", "01", "true", "2"};
    for (const char *value : values) {
        if (value) {
            setenv("ART_LIVE_PARAM", value, 1);
        } else {
            unsetenv("ART_LIVE_PARAM");
        }
        if (!check(!server.start() && !server.isRunning() && server.getSocketPath().empty() &&
                       !LiveParamController::getInstance().isEnabled(),
                   "Only ART_LIVE_PARAM exactly equal to 1 enables a listener")) {
            return false;
        }
    }
    ServerScope scope;
    if (!scope.started) {
        return false;
    }
    struct stat socketInfo{}, dirInfo{};
    const std::string path = server.getSocketPath();
    const auto parent = Glib::path_get_dirname(path);
    if (!check(lstat(path.c_str(), &socketInfo) == 0 && S_ISSOCK(socketInfo.st_mode) &&
                   (socketInfo.st_mode & 0777) == 0600 && socketInfo.st_uid == geteuid() &&
                   lstat(parent.c_str(), &dirInfo) == 0 && S_ISDIR(dirInfo.st_mode) &&
                   (dirInfo.st_mode & 0777) == 0700 && dirInfo.st_uid == geteuid(),
               "Socket 0600 and directory 0700 belong to the GUI user")) {
        return false;
    }
    {
        Client client(path);
        int pipeFds[2];
        if (pipe(pipeFds)) {
            return false;
        }
        const bool authorized = LiveParamServerTestAccess::authenticate(client.fd);
        const bool denied = !LiveParamServerTestAccess::authenticate(pipeFds[0]);
        close(pipeFds[0]);
        close(pipeFds[1]);
        if (!check(authorized && denied,
                   "Kernel credentials authorize a real Unix peer and fail closed when unavailable")) {
            return false;
        }
    }
    {
        EditorScope editor(window, dir, "t09");
        if (!editor.ready) {
            return false;
        }
        auto &controller = LiveParamController::getInstance();
        const std::string session = controller.getSessionId();
        const std::string editorId = editor.panel->getEditorId();
        editor.panel->getToolPanelCoordinator()->applyExternalExposure(0.20);
        if (!check(editor.panel->getIsProcessing(), "Render is active before deferred quit check")) {
            return false;
        }
        if (!check(window->on_delete_event(nullptr) && server.isRunning() &&
                       editor.panel->getEditorId() == editorId,
                   "A quit deferred for processing keeps the editor and listener available")) {
            return false;
        }
        Client original(path);
        auto state = parse(rpc(original, request("before-reconnect", "get_state", editorId)));
        auto *result = cJSON_GetObjectItemCaseSensitive(state.get(), "result");
        if (!result) {
            return false;
        }
        const auto revision = cJSON_GetObjectItemCaseSensitive(result, "revision")->valuedouble;
        const std::string mutation = request("reconnect-\"\\", "set_param", editorId, session, revision, 0.75);
        if (!original.sendText(mutation + "\n")) {
            return false;
        }
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        rtengine::procparams::ProcParams params;
        do {
            pump();
            editor.panel->getImageProcessor()->getCommittedParams(&params);
        } while (params.exposure.expcomp != 0.75 && std::chrono::steady_clock::now() < deadline);
        if (!check(params.exposure.expcomp == 0.75,
                   "Mutation applied before the original client consumes its response")) {
            return false;
        }
        close(original.fd);
        original.fd = -1;
        Client reconnected(path);
        auto replay = parse(rpc(reconnected, mutation));
        auto after = parse(rpc(reconnected, request("after-reconnect", "get_state", editorId)));
        auto *current = cJSON_GetObjectItemCaseSensitive(after.get(), "result");
        if (!check(stringField(replay.get(), "status") == "APPLIED" && current &&
                       cJSON_GetObjectItemCaseSensitive(current, "revision")->valuedouble == revision + 1,
                   "Reconnect replays the cached application without incrementing revision again")) {
            return false;
        }
    }
    const auto previousSession = LiveParamController::getInstance().getSessionId();
    server.stop();
    if (!server.start()) {
        return false;
    }
    return check(server.getSocketPath() != path && access(path.c_str(), F_OK) != 0 &&
                     LiveParamController::getInstance().getSessionId() != previousSession,
                 "A fresh listener owns a new path and session; the previous path stays removed");
}
