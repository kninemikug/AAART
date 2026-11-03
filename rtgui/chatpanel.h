#pragma once

#include "chatconnection.h"
#include <gtkmm.h>

class ChatPanel: public Gtk::Box {
public:
    ChatPanel();
    bool containsFocus();
    bool handleKeyPress(GdkEventKey *event);
    void stop();
    void setLiveTargetProvider(std::function<ChatLiveTarget()> provider)
    {
        connection_.setLiveTargetProvider(std::move(provider));
    }

private:
    ChatConnection connection_;
    Gtk::Box messages_;
    Gtk::ScrolledWindow scroll_;
    Gtk::Entry input_, python_, source_, store_;
    Gtk::Button send_, cancel_, clear_;
    Gtk::Label status_;
    Gtk::Spinner spinner_;
    Gtk::Expander settings_;
    Gtk::Grid settings_grid_;
    void send();
    void received(const ChatReply &reply);
    void busy(bool running);
    void welcome();
    Gtk::Box *append(const Glib::ustring &who, const Glib::ustring &text,
                     const std::vector<ChatCitation> &citations = {});
    void settingRow(int row, const Glib::ustring &label, Gtk::Entry &entry,
                    bool file);
};
