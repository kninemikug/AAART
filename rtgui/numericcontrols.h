#pragma once

#include <gtkmm.h>
#include <string>
#include <vector>

class ToolPanel;

namespace art {
namespace liveparam {

// GUI-thread-only snapshot. Widget pointers never cross the IPC boundary.
struct NumericControl {
    enum class Kind { ADJUSTER, SPIN, RANGE, THRESHOLD, SHC, WHEEL };
    std::string id;
    std::string tool;
    std::string toolLabel;
    std::string label;
    Kind kind = Kind::SPIN;
    double minimum = 0;
    double maximum = 0;
    double step = 1;
    double value = 0;
    bool enabled = true;
    bool available = true;
    bool pending = false;
    ToolPanel *owner = nullptr;
    Gtk::Widget *widget = nullptr;
    unsigned component = 0;
};

struct NumericApplyResult {
    std::string error = "INTERNAL_ERROR";
    double value = 0;
    std::vector<std::string> enabledTools;
};

std::vector<NumericControl> collectNumericControls(
    const std::vector<ToolPanel *> &panels);
std::string numericContextId(const std::vector<ToolPanel *> &panels);
void writeNumericControl(const NumericControl &control, double value);

} // namespace liveparam
} // namespace art
