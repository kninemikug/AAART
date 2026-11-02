// Native GTK regression checks; see docs/T22_execution_plan.md to run.
#include "chatinput.h"
#include <cstdio>

#ifdef __APPLE__
namespace {

GdkEventKey command(guint keyval, guint16 hardware, guint extra = 0)
{
    GdkEventKey event{};
    event.type = GDK_KEY_PRESS;
    event.keyval = keyval;
    event.hardware_keycode = hardware;
    event.state = GDK_MOD2_MASK | extra;
    return event;
}

void selectKorean()
{
    Gtk::Entry entry;
    entry.set_text("한글 입력 확인");
    // macOS can report a Hangul keysym while Command is held.
    auto event = command(0x1003141, 0); // ANSI A / ㅁ
    g_assert_true(art::chat::handleEditKey(&entry, &event));
    int start = -1, end = -1;
    g_assert_true(entry.get_selection_bounds(start, end));
    g_assert_cmpint(start, ==, 0);
    g_assert_cmpint(end, ==, 8);
}

void copyAnswer()
{
    Gtk::Window window;
    Gtk::Label answer("한글 답변과 출처");
    window.add(answer);
    window.show_all();
    answer.set_selectable(true);
    answer.select_region(0, -1);
    auto event = command(GDK_KEY_c, 8);
    g_assert_true(art::chat::handleEditKey(&answer, &event));
    const auto copied = Gtk::Clipboard::get()->wait_for_text();
    g_assert_true(copied == answer.get_text());
}

void preserveOtherModifiers()
{
    Gtk::Entry entry;
    entry.set_text("보존할 질문");
    auto event = command(GDK_KEY_a, 0, GDK_CONTROL_MASK);
    g_assert_false(art::chat::handleEditKey(&entry, &event));
    int start = -1, end = -1;
    g_assert_false(entry.get_selection_bounds(start, end));
}

void selectWithCommandArrow()
{
    Gtk::Entry entry;
    entry.set_text("한글 abc");
    entry.set_position(-1);
    auto event = command(GDK_KEY_Left, 123, GDK_SHIFT_MASK);
    g_assert_true(art::chat::handleEditKey(&entry, &event));
    int start = -1, end = -1;
    g_assert_true(entry.get_selection_bounds(start, end));
    g_assert_cmpint(start, ==, 0);
    g_assert_cmpint(end, ==, 6);
}

void preserveCompositionKeys()
{
    Gtk::Entry entry;
    auto event = command(0x100314e, 0);
    event.state = 0;
    g_assert_false(art::chat::handleEditKey(&entry, &event));
    event = command(GDK_KEY_space, 49);
    event.state = GDK_CONTROL_MASK;
    g_assert_false(art::chat::handleEditKey(&entry, &event));
}

void configureQuartz()
{
    Gtk::Entry entry;
    art::chat::configureInput(entry);
    if (!g_getenv("GTK_IM_MODULE")) {
        g_assert_true(entry.property_im_module().get_value() == "quartz");
    }
    // An explicitly selected module must survive configuration.
    entry.property_im_module() = "gtk-im-context-simple";
    art::chat::configureInput(entry);
    g_assert_true(entry.property_im_module().get_value()
                  == "gtk-im-context-simple");
}

void koreanClipboard()
{
    Gtk::Window window;
    Gtk::Entry entry;
    window.add(entry);
    window.show_all();
    entry.set_text("한글 복사·붙여넣기");
    entry.select_region(0, -1);
    auto event = command(0x100314a, 8); // ANSI C / ㅊ
    g_assert_true(art::chat::handleEditKey(&entry, &event));
    g_assert_true(Gtk::Clipboard::get()->wait_for_text() == entry.get_text());
    event = command(0x100314c, 7); // ANSI X / ㅌ
    g_assert_true(art::chat::handleEditKey(&entry, &event));
    g_assert_true(entry.get_text().empty());
    event = command(0x100314d, 9); // ANSI V / ㅍ
    g_assert_true(art::chat::handleEditKey(&entry, &event));
    const auto deadline = g_get_monotonic_time() + G_TIME_SPAN_SECOND;
    while (entry.get_text().empty() && g_get_monotonic_time() < deadline) {
        g_main_context_iteration(nullptr, false);
    }
    g_assert_true(entry.get_text() == "한글 복사·붙여넣기");
}

} // namespace
#endif

int main(int argc, char **argv)
{
    Gtk::Main app(argc, argv);
    g_test_init(&argc, &argv, nullptr);
#ifdef __APPLE__
    g_test_add_func("/chat/input/korean-command-a", selectKorean);
    g_test_add_func("/chat/input/copy-answer", copyAnswer);
    g_test_add_func("/chat/input/other-modifiers", preserveOtherModifiers);
    g_test_add_func("/chat/input/command-arrow", selectWithCommandArrow);
    g_test_add_func("/chat/input/composition-keys", preserveCompositionKeys);
    g_test_add_func("/chat/input/quartz-module", configureQuartz);
    g_test_add_func("/chat/input/korean-clipboard", koreanClipboard);
#endif
    return g_test_run();
}
