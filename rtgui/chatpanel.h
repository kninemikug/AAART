#pragma once

#include "chatconnection.h"
#include <gtkmm.h>

class ChatPanel: public Gtk::Box {
public:
    ChatPanel();
    bool containsFocus();
    bool handleKeyPress(GdkEventKey *event);
    void stop();
    static bool liveExposureEnabledAtStartup();
    void setLiveExposureControl(std::function<bool(bool)> control, bool active);
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
    Gtk::CheckButton live_exposure_;
    Gtk::Label live_help_;
    std::function<bool(bool)> liveExposureControl_;
    sigc::connection liveExposureChanged_;
    bool saveSettings(bool includePermission);
    void liveExposureToggled();
    void send();
    void received(const ChatReply &reply);
    void busy(bool running);
    void welcome();
    Gtk::Box *append(const Glib::ustring &who, const Glib::ustring &text,
                     const std::vector<ChatCitation> &citations = {});
    void settingRow(int row, const Glib::ustring &label, Gtk::Entry &entry,
                    bool file);
};
