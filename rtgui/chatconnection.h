#pragma once

#include <glibmm.h>
#include <gio/gio.h>
#include <memory>
#include <functional>
#include <cstdint>
#include <sigc++/sigc++.h>
#include <string>
#include <vector>

struct ChatSettings {
    Glib::ustring python;
    Glib::ustring source;
    Glib::ustring store;
};

struct ChatLiveTarget {
    std::string socketPath;
    std::string sessionId;
    std::string editorId;
    int64_t revision = -1;
};

struct ChatCitation {
    std::string title;
    std::string url;
};

struct ChatStep {
    std::string text;
    std::string error;
    std::vector<ChatCitation> citations;
};

struct ChatReply {
    std::string status;
    std::string message;
    std::vector<ChatStep> steps;
};

// Owns async I/O independently of the widgets; callbacks never outlive owner.
class ChatConnection: public sigc::trackable {
public:
    ChatConnection() = default;
    ~ChatConnection();
    void send(const ChatSettings &settings, const Glib::ustring &question);
    void cancel();
    void setLiveTargetProvider(std::function<ChatLiveTarget()> provider)
    {
        liveTargetProvider_ = std::move(provider);
    }
    bool mayHaveAppliedEdit() const;
    sigc::signal<void, const ChatReply &> completed;

private:
    std::function<ChatLiveTarget()> liveTargetProvider_;
    struct Job;
    std::shared_ptr<Job> job_;
    sigc::connection timeout_;
    bool timedOut();
    static void receive(GObject *source, GAsyncResult *result, void *data);
};
