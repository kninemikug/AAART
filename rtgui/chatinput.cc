#include "chatinput.h"

namespace art {
namespace chat {

bool handleEditKey(Gtk::Widget *focus, GdkEventKey *event)
{
#ifdef __APPLE__
    if (!focus || !(event->state & (GDK_MOD2_MASK | GDK_META_MASK))
        || (event->state & (GDK_CONTROL_MASK | GDK_MOD1_MASK))) {
        return false;
    }
    auto value = gdk_keyval_to_lower(event->keyval);
    // Quartz can report a Hangul keysym in the Korean input source. These
    // hardware codes identify the Command shortcuts on macOS keyboards.
    if (value > 127 && value != GDK_KEY_Left && value != GDK_KEY_Right) {
        switch (event->hardware_keycode) {
        case 0: value = GDK_KEY_a; break;
        case 7: value = GDK_KEY_x; break;
        case 8: value = GDK_KEY_c; break;
        case 9: value = GDK_KEY_v; break;
        }
    }
    auto entry = dynamic_cast<Gtk::Entry *>(focus);
    const bool shift = event->state & GDK_SHIFT_MASK;
    if (entry && (value == GDK_KEY_Left || value == GDK_KEY_Right)) {
        entry->reset_im_context();
        const int target = value == GDK_KEY_Left ? 0
            : static_cast<int>(entry->get_text_length());
        if (shift) {
            const int anchor = entry->property_selection_bound();
            entry->select_region(anchor, target);
        } else {
            entry->set_position(target);
        }
        return true;
    }
    if (shift) {
        return false;
    }
    if (entry && (value == GDK_KEY_a || value == GDK_KEY_c
                  || value == GDK_KEY_x || value == GDK_KEY_v)) {
        // Finish the current syllable before copying or changing the buffer.
        entry->reset_im_context();
        switch (value) {
        case GDK_KEY_v: entry->paste_clipboard(); return true;
        case GDK_KEY_c: entry->copy_clipboard(); return true;
        case GDK_KEY_x: entry->cut_clipboard(); return true;
        case GDK_KEY_a: entry->select_region(0, -1); return true;
        }
    }
    auto label = dynamic_cast<Gtk::Label *>(focus);
    if (label && label->get_selectable()) {
        if (value == GDK_KEY_a) {
            label->select_region(0, -1);
            return true;
        }
        if (value == GDK_KEY_c) {
            g_signal_emit_by_name(label->gobj(), "copy-clipboard");
            return true;
        }
    }
#endif
    return false;
}

void configureInput(Gtk::Entry &entry)
{
#ifdef __APPLE__
    // Do not depend on the launcher's locale choosing Quartz rather than the
    // simple input context, which inserts Hangul jamo without composing them.
    // Keep an explicitly configured input module intact.
    if (!g_getenv("GTK_IM_MODULE")
        && entry.property_im_module().get_value().empty()) {
        entry.property_im_module() = "quartz";
    }
#endif
}

Glib::ustring committedText(Gtk::Entry &entry)
{
    entry.reset_im_context();
    return entry.get_text();
}

} // namespace chat
} // namespace art
