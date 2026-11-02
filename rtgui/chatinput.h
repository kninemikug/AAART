#pragma once

#include <gtkmm.h>

namespace art {
namespace chat {

bool handleEditKey(Gtk::Widget *focus, GdkEventKey *event);
void configureInput(Gtk::Entry &entry);
Glib::ustring committedText(Gtk::Entry &entry);

} // namespace chat
} // namespace art
