#include "chatconnection.h"
#include "config.h"
#include "../rtengine/cJSON.h"
#include "multilangmgr.h"
#include <gio/gio.h>
#include <cstdlib>
#include <cstring>
#include <set>
#include <stdexcept>
#ifndef WIN32
#include <csignal>
#include <unistd.h>
#endif

namespace {

using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;

std::string field(const cJSON *json, const char *name)
{
    const auto value = cJSON_GetObjectItemCaseSensitive(json, name);
    if (!cJSON_IsString(value) || !value->valuestring) {
        throw std::runtime_error("Invalid response field");
    }
    return value->valuestring;
}

ChatReply parseReply(const char *text, const std::string &request_id)
{
    if (!text || std::strlen(text) > 2 * 1024 * 1024) {
        throw std::runtime_error("Invalid response size");
    }
    Json json(cJSON_ParseWithOpts(text, nullptr, true), cJSON_Delete);
    const auto version = cJSON_GetObjectItemCaseSensitive(
        json.get(), "version");
    const auto steps = cJSON_GetObjectItemCaseSensitive(json.get(), "steps");
    if (!cJSON_IsObject(json.get()) || !cJSON_IsNumber(version)
        || version->valuedouble != 1 || !cJSON_IsArray(steps)
        || field(json.get(), "request_id") != request_id) {
        throw std::runtime_error("Invalid response envelope");
    }
    ChatReply reply;
    reply.status = field(json.get(), "status");
    reply.message = field(json.get(), "message");
    const std::set<std::string> statuses = {
        "COMPLETED", "PARTIAL", "WAITING_CLARIFICATION", "UNSUPPORTED",
        "INSUFFICIENT_EVIDENCE", "FAILED", "OUT_OF_SCOPE", "CANCELLED"};
    if (!statuses.count(reply.status)) {
        throw std::runtime_error("Invalid response status");
    }
    for (auto item = steps->child; item; item = item->next) {
        ChatStep step;
        step.text = field(item, "text");
        const auto error = cJSON_GetObjectItemCaseSensitive(item, "error");
        if (!cJSON_IsNull(error)) {
            step.error = field(error, "message");
        }
        const auto citations = cJSON_GetObjectItemCaseSensitive(
            item, "citations");
        if (!cJSON_IsArray(citations)) {
            throw std::runtime_error("Invalid citations");
        }
        for (auto cite = citations->child; cite; cite = cite->next) {
            step.citations.push_back(
                {field(cite, "title"), field(cite, "url")});
        }
        reply.steps.push_back(std::move(step));
    }
    return reply;
}

} // namespace

struct ChatConnection::Job {
    ChatConnection *owner;
    GSubprocess *process = nullptr;
    GCancellable *cancellable = g_cancellable_new();
    std::string id;
    std::string input;

    ~Job()
    {
        g_clear_object(&process);
        g_object_unref(cancellable);
    }
};

ChatConnection::~ChatConnection() { cancel(); }

void ChatConnection::cancel()
{
    timeout_.disconnect();
    if (job_) {
        job_->owner = nullptr;
#ifndef WIN32
        // The launcher creates a group so cancellation also stops descendants.
        const char *id = g_subprocess_get_identifier(job_->process);
        if (id) {
            const auto pid = std::strtol(id, nullptr, 10);
            if (pid > 0) {
                ::kill(-pid, SIGKILL);
            }
        }
#endif
        g_subprocess_force_exit(job_->process);
        g_cancellable_cancel(job_->cancellable);
        job_.reset();
    }
}

void ChatConnection::send(const ChatSettings &settings,
                          const Glib::ustring &question)
{
    cancel();
    auto job = std::make_shared<Job>();
    job->owner = this;
    job->id = std::to_string(g_get_real_time());
    Json request(cJSON_CreateObject(), cJSON_Delete);
    cJSON_AddNumberToObject(request.get(), "version", 1);
    cJSON_AddStringToObject(request.get(), "request_id", job->id.c_str());
    cJSON_AddStringToObject(request.get(), "text", question.c_str());
    char *serialized = cJSON_PrintUnformatted(request.get());
    job->input = serialized;
    cJSON_free(serialized);

    auto flags = GSubprocessFlags(G_SUBPROCESS_FLAGS_STDIN_PIPE
                                 | G_SUBPROCESS_FLAGS_STDOUT_PIPE
                                 | G_SUBPROCESS_FLAGS_STDERR_PIPE);
    auto launcher = g_subprocess_launcher_new(flags);
    const auto pythonpath = Glib::build_filename(settings.source, "src");
    g_subprocess_launcher_set_cwd(launcher, settings.source.c_str());
    g_subprocess_launcher_setenv(
        launcher, "PYTHONPATH", pythonpath.c_str(), true);
    g_subprocess_launcher_setenv(
        launcher, "PYTHONDONTWRITEBYTECODE", "1", true);
    auto path = Glib::path_get_dirname(settings.python);
    if (std::strlen(ART_AGENT_ANSWER_RUNTIME)) {
        path += G_SEARCHPATH_SEPARATOR_S;
        path += Glib::path_get_dirname(ART_AGENT_ANSWER_RUNTIME);
    }
    if (const char *inherited = g_getenv("PATH")) {
        path += G_SEARCHPATH_SEPARATOR_S;
        path += inherited;
    }
    g_subprocess_launcher_setenv(launcher, "PATH", path.c_str(), true);
#ifndef WIN32
    g_subprocess_launcher_set_child_setup(
        launcher, [](gpointer) { ::setsid(); }, nullptr, nullptr);
#endif
    const char *argv[] = {settings.python.c_str(), "-u", "-m",
                          "artagent.gui_bridge", "--source-root",
                          settings.source.c_str(), "--persist-dir",
                          settings.store.c_str(), nullptr};
    GError *error = nullptr;
    job->process = g_subprocess_launcher_spawnv(launcher, argv, &error);
    g_object_unref(launcher);
    if (!job->process) {
        g_clear_error(&error);
        throw std::runtime_error("Unable to start chat process");
    }
    job_ = job;
    timeout_ = Glib::signal_timeout().connect_seconds(
        sigc::mem_fun(*this, &ChatConnection::timedOut), 300);
    g_subprocess_communicate_utf8_async(
        job->process, job->input.c_str(), job->cancellable, receive,
        new std::shared_ptr<Job>(job));
}

bool ChatConnection::timedOut()
{
    cancel();
    completed.emit({"FAILED", M("CHAT_TIMEOUT"), {}});
    return false;
}

void ChatConnection::receive(GObject *source, GAsyncResult *result, void *data)
{
    std::unique_ptr<std::shared_ptr<Job>> held(
        static_cast<std::shared_ptr<Job> *>(data));
    auto job = *held;
    char *out = nullptr;
    char *err = nullptr;
    GError *error = nullptr;
    const bool ok = g_subprocess_communicate_utf8_finish(
        G_SUBPROCESS(source), result, &out, &err, &error);
    ChatReply reply{"FAILED", M("CHAT_CONNECTION_ERROR"), {}};
    if (ok) {
        try {
            reply = parseReply(out, job->id);
        } catch (const std::exception &) {
            // Never display raw stderr, which may contain authentication data.
        }
    }
    g_free(out);
    g_free(err);
    g_clear_error(&error);
    if (job->owner) {
        auto owner = job->owner;
        owner->timeout_.disconnect();
        owner->job_.reset();
        owner->completed.emit(reply);
    }
}
