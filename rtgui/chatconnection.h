#pragma once

#include <glibmm.h>
#include <gio/gio.h>
#include <memory>
#include <sigc++/sigc++.h>
#include <string>
#include <vector>

struct ChatSettings {
    Glib::ustring python;
    Glib::ustring source;
    Glib::ustring store;
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
    sigc::signal<void, const ChatReply &> completed;

private:
    struct Job;
    std::shared_ptr<Job> job_;
    sigc::connection timeout_;
    bool timedOut();
    static void receive(GObject *source, GAsyncResult *result, void *data);
};
