#include "chatpanel.h"
#include "chatinput.h"
#include "config.h"
#include "guiutils.h"
#include "multilangmgr.h"
#include "options.h"
#include <glib/gstdio.h>

namespace {
Glib::ustring settingFile()
{
    return Glib::build_filename(Options::user_config_dir, "artagent.ini");
}
} // namespace

ChatPanel::ChatPanel()
    : Gtk::Box(Gtk::ORIENTATION_VERTICAL, 8),
      messages_(Gtk::ORIENTATION_VERTICAL, 12), send_(M("CHAT_SEND")),
      cancel_(M("GENERAL_CANCEL")), clear_(M("CHAT_CLEAR")),
      settings_(M("CHAT_SETTINGS"))
{
    set_border_width(12);
    set_size_request(300, -1);
    auto title = Gtk::manage(new Gtk::Label(M("CHAT_TITLE")));
    title->get_style_context()->add_class("title");
    title->set_xalign(0);
    auto header = Gtk::manage(new Gtk::Box(Gtk::ORIENTATION_HORIZONTAL, 8));
    header->pack_start(*title);
    header->pack_end(clear_, Gtk::PACK_SHRINK);
    pack_start(*header, Gtk::PACK_SHRINK);
    scroll_.set_policy(Gtk::POLICY_NEVER, Gtk::POLICY_AUTOMATIC);
    messages_.set_border_width(8);
    scroll_.add(messages_);
    pack_start(scroll_);
    input_.set_placeholder_text(M("CHAT_PLACEHOLDER"));
    input_.set_max_length(8192);
    input_.set_tooltip_text(M("CHAT_PLACEHOLDER"));
    input_.get_accessible()->set_name(M("CHAT_QUESTION"));
    art::chat::configureInput(input_);
    pack_start(input_, Gtk::PACK_SHRINK);
    auto actions = Gtk::manage(new Gtk::Box(Gtk::ORIENTATION_HORIZONTAL, 8));
    actions->pack_start(send_, Gtk::PACK_SHRINK);
    actions->pack_start(cancel_, Gtk::PACK_SHRINK);
    actions->pack_end(spinner_, Gtk::PACK_SHRINK);
    pack_start(*actions, Gtk::PACK_SHRINK);
    status_.set_xalign(0);
    status_.set_line_wrap(true);
    pack_start(status_, Gtk::PACK_SHRINK);
    settings_grid_.set_row_spacing(6);
    settings_grid_.set_column_spacing(6);
    settingRow(0, M("CHAT_PYTHON"), python_, true);
    settingRow(1, M("CHAT_SOURCE"), source_, false);
    settingRow(2, M("CHAT_STORE"), store_, false);
    settings_.add(settings_grid_);
    pack_start(settings_, Gtk::PACK_SHRINK);

    python_.set_text(ART_AGENT_PYTHON);
    source_.set_text(ART_AGENT_SOURCE_DIR);
    store_.set_text(ART_AGENT_STORE_DIR);
    if (const char *path = g_getenv("T09_PERSIST_DIR")) {
        store_.set_text(path);
    }
    try {
        Glib::KeyFile saved;
        if (saved.load_from_file(settingFile())) {
            python_.set_text(saved.get_string("Chat", "python"));
            source_.set_text(saved.get_string("Chat", "source"));
            store_.set_text(saved.get_string("Chat", "store"));
        }
    } catch (const Glib::Error &) {
        // First launch uses the configured build paths; no credentials stored.
    }
    connection_.completed.connect(sigc::mem_fun(*this, &ChatPanel::received));
    send_.signal_clicked().connect(sigc::mem_fun(*this, &ChatPanel::send));
    input_.signal_activate().connect(sigc::mem_fun(*this, &ChatPanel::send));
    cancel_.signal_clicked().connect([this]() {
        const bool possibleEdit = connection_.mayHaveAppliedEdit();
        stop();
        append(M("CHAT_TITLE"), M(possibleEdit ? "CHAT_LIVE_CANCELLED" : "CHAT_CANCELLED"));
    });
    clear_.signal_clicked().connect([this]() {
        for (auto child : messages_.get_children()) {
            delete child;
        }
        welcome();
    });
    scroll_.get_vadjustment()->signal_changed().connect([this]() {
        auto adjustment = scroll_.get_vadjustment();
        adjustment->set_value(
            adjustment->get_upper() - adjustment->get_page_size());
    });
    welcome();
    busy(false);
}

void ChatPanel::settingRow(int row, const Glib::ustring &text,
                           Gtk::Entry &entry, bool file)
{
    auto label = Gtk::manage(new Gtk::Label(text));
    label->set_xalign(0);
    label->set_mnemonic_widget(entry);
    auto browse = Gtk::manage(new Gtk::Button("…"));
    browse->set_tooltip_text(text);
    browse->get_accessible()->set_name(text);
    entry.set_hexpand(true);
    entry.get_accessible()->set_name(text);
    art::chat::configureInput(entry);
    settings_grid_.attach(*label, 0, row * 2, 2, 1);
    settings_grid_.attach(entry, 0, row * 2 + 1, 1, 1);
    settings_grid_.attach(*browse, 1, row * 2 + 1, 1, 1);
    browse->signal_clicked().connect([this, &entry, text, file]() {
        Gtk::FileChooserDialog dialog(text, file ? Gtk::FILE_CHOOSER_ACTION_OPEN
            : Gtk::FILE_CHOOSER_ACTION_SELECT_FOLDER);
        if (auto window = dynamic_cast<Gtk::Window *>(get_toplevel())) {
            dialog.set_transient_for(*window);
        }
        dialog.add_button(M("GENERAL_CANCEL"), Gtk::RESPONSE_CANCEL);
        dialog.add_button(M("GENERAL_OK"), Gtk::RESPONSE_OK);
        if (!entry.get_text().empty()) {
            dialog.set_filename(entry.get_text());
        }
        if (dialog.run() == Gtk::RESPONSE_OK) {
            entry.set_text(dialog.get_filename());
        }
    });
}

bool ChatPanel::containsFocus()
{
    auto window = dynamic_cast<Gtk::Window *>(get_toplevel());
    const auto focus = window ? window->get_focus() : nullptr;
    return focus && (focus == this || focus->is_ancestor(*this));
}

bool ChatPanel::handleKeyPress(GdkEventKey *event)
{
    auto window = dynamic_cast<Gtk::Window *>(get_toplevel());
    return art::chat::handleEditKey(window ? window->get_focus() : nullptr,
                                   event);
}

void ChatPanel::busy(bool running)
{
    send_.set_sensitive(!running);
    input_.set_sensitive(!running);
    settings_.set_sensitive(!running);
    clear_.set_sensitive(!running);
    cancel_.set_sensitive(running);
    if (running) {
        spinner_.start();
    } else {
        spinner_.stop();
    }
    status_.set_text(running ? M("CHAT_WORKING") : M("CHAT_READY"));
}

void ChatPanel::stop()
{
    connection_.cancel();
    busy(false);
}

void ChatPanel::send()
{
    if (!send_.get_sensitive()) {
        return;
    }
    const auto question = art::chat::committedText(input_);
    if (question.find_first_not_of(" \t\r\n") == Glib::ustring::npos) {
        return;
    }
    const ChatSettings settings{python_.get_text(), source_.get_text(),
                                 store_.get_text()};
    if (!Glib::path_is_absolute(settings.source)
        || !Glib::path_is_absolute(settings.store)
        || !Glib::file_test(Glib::build_filename(settings.source, "src",
                                             "artagent", "gui_bridge.py"),
                         Glib::FILE_TEST_IS_REGULAR)) {
        settings_.set_expanded(true);
        append(M("CHAT_TITLE"), M("CHAT_CONNECTION_ERROR"));
        return;
    }
    try {
        Glib::KeyFile saved;
        saved.set_string("Chat", "python", settings.python);
        saved.set_string("Chat", "source", settings.source);
        saved.set_string("Chat", "store", settings.store);
        saved.save_to_file(settingFile());
    } catch (const Glib::Error &) {
        append(M("CHAT_TITLE"), M("CHAT_SETTINGS_ERROR"));
    }
    append(M("CHAT_YOU"), question);
    input_.set_text("");
    busy(true);
    try {
        connection_.send(settings, question);
    } catch (const std::exception &) {
        received({"FAILED", M("CHAT_CONNECTION_ERROR"), {}});
    }
}

void ChatPanel::received(const ChatReply &reply)
{
    busy(false);
    append(M("CHAT_TITLE"), reply.message);
    for (const auto &step : reply.steps) {
        if (!step.text.empty()) {
            append(M("CHAT_ANSWER"), step.text, step.citations);
        }
        if (!step.error.empty()) {
            append(M("CHAT_NOTICE"), step.error);
        }
    }
    if (reply.status == "FAILED") {
        settings_.set_expanded(true);
    }
    input_.grab_focus();
}

void ChatPanel::welcome()
{
    auto box = append(M("CHAT_TITLE"), M("CHAT_WELCOME"));
    auto example = Gtk::manage(new Gtk::Button(M("CHAT_EXAMPLE")));
    example->signal_clicked().connect([this]() {
        if (send_.get_sensitive()) {
            input_.set_text(M("CHAT_EXAMPLE_QUESTION"));
            input_.grab_focus();
        }
    });
    box->pack_start(*example, Gtk::PACK_SHRINK);
    example->show();
}

Gtk::Box *ChatPanel::append(const Glib::ustring &who, const Glib::ustring &text,
                            const std::vector<ChatCitation> &citations)
{
    auto box = Gtk::manage(new Gtk::Box(Gtk::ORIENTATION_VERTICAL, 4));
    auto heading = Gtk::manage(new Gtk::Label(who));
    heading->set_xalign(0);
    heading->get_style_context()->add_class("dim-label");
    box->pack_start(*heading, Gtk::PACK_SHRINK);
    auto body = Gtk::manage(new Gtk::Label(text));
    body->set_xalign(0);
    body->set_line_wrap(true);
    body->set_line_wrap_mode(Pango::WRAP_WORD_CHAR);
    body->set_max_width_chars(42);
    body->set_selectable(true);
    box->pack_start(*body, Gtk::PACK_SHRINK);
    for (const auto &citation : citations) {
        if (citation.url.compare(0, 8, "https://") != 0
            && citation.url.compare(0, 7, "http://") != 0) {
            continue;
        }
        auto link = Gtk::manage(
            new Gtk::LinkButton(citation.url, citation.title));
        link->set_halign(Gtk::ALIGN_START);
        link->set_tooltip_text(citation.url);
        box->pack_start(*link, Gtk::PACK_SHRINK);
    }
    messages_.pack_start(*box, Gtk::PACK_SHRINK);
    if (messages_.get_children().size() > 100) {
        delete messages_.get_children().front();
    }
    box->show_all();
    return box;
}
