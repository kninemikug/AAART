#include "numericcontrols.h"
#include "adjuster.h"
#include "clutparamspanel.h"
#include "colorwheel.h"
#include "coordinateadjuster.h"
#include "shcselector.h"
#include "thresholdadjuster.h"
#include "toolpanel.h"
#include "../rtengine/curves.h"

#include <cmath>
#include <iostream>
#include <fstream>
#include <map>
#include <set>

namespace {
struct PhotoTool: Gtk::VBox, ToolPanel {
    PhotoTool(): ToolPanel("numeric-widget-fixture") {}
};

struct Coordinates: CoordinateProvider {
    double values[2] = {0, 0};
    unsigned changes = 0;
    void setPos(double value, int axis) override { values[axis] = value; ++changes; }
    void stopNumericalAdjustment() override {}
};

struct BoundariesListener: SHCListener {
    unsigned changes = 0;
    void shcChanged() override { ++changes; }
};

struct ThresholdListener: ThresholdAdjusterListener {
    unsigned changes = 0;
    unsigned secondaryChanges = 0;
    void adjusterChanged(ThresholdAdjuster *, double, double) override { ++changes; }
    void adjusterChanged(ThresholdAdjuster *, double, double, double, double) override { ++changes; }
    void adjusterChanged(ThresholdAdjuster *, int, int) override { ++changes; }
    void adjusterChanged(ThresholdAdjuster *, int, int, int, int) override { ++changes; }
    void adjusterChanged2(ThresholdAdjuster *, int, int, int, int) override { ++secondaryChanges; }
};
} // namespace

bool testNumericWidgets()
{
    using namespace art::liveparam;
    const auto require = [](bool passed, const char *message) {
        if (!passed) { std::cerr << "Numeric widget failure: " << message << std::endl; }
        return passed;
    };
    PhotoTool tool;
    Coordinates coordinates;
    CoordinateAdjuster point(&coordinates, nullptr);
    SHCSelector boundaries;
    BoundariesListener listener;
    boundaries.setSHCListener(&listener);
    boundaries.setPositions(.2, .5, .8);
    ThresholdAdjuster threshold("Threshold", 0, 100, 10, 20, 90, 80, 0, false);
    ThresholdListener thresholdListener;
    threshold.setAdjusterListener(&thresholdListener);
    ColorWheel wheel;
    HueSatColorWheel hueSat;
    Gtk::SpinButton integer;
    integer.set_range(0, 10000);
    integer.set_increments(1, 10);
    integer.set_digits(0);
    Gtk::Scale range(Gtk::ORIENTATION_HORIZONTAL);
    range.set_range(-10, 10);
    range.set_increments(.1, 1);
    CLUTParamsPanel lut;
    for (auto *widget : std::vector<Gtk::Widget *>{&point, &boundaries, &threshold,
             &wheel, &hueSat, &integer, &range, &lut}) {
        tool.pack_start(*widget);
    }
    tool.show_all();
    const auto controls = [&]() { return collectNumericControls({&tool}); };
    const auto find = [&](Gtk::Widget *widget, unsigned component = 0) {
        for (const auto &entry : controls()) {
            if (entry.widget == widget && entry.component == component) { return entry; }
        }
        return NumericControl();
    };
    if (!require(!find(&integer).id.empty(), "standalone spin discovered")) { return false; }
    writeNumericControl(find(&integer), 1000.25);
    if (!require(integer.get_value() == integer.get_value_as_int(), "integer effective value matches native stored integer")) { return false; }
    writeNumericControl(find(&range), 2.5);
    if (!require(range.get_value() == 2.5, "standalone numeric range")) { return false; }

    for (unsigned component = 0; component < 4; ++component) {
        const auto entry = find(&threshold, component);
        const auto value = std::round((entry.minimum + entry.maximum) / 2);
        writeNumericControl(entry, value);
        if (!require(std::fabs(find(&threshold, component).value - value) < 1e-6,
                "all four threshold handles follow their native limits")) { return false; }
    }
    if (!require(thresholdListener.changes == 4 && thresholdListener.secondaryChanges == 4,
            "all threshold handles preserve both native callback forms")) { return false; }
    for (unsigned component = 0; component < 3; ++component) {
        const auto entry = find(&boundaries, component);
        writeNumericControl(entry, (entry.minimum + entry.maximum) / 2);
    }
    if (!require(listener.changes == 3, "SHC callbacks are synchronous and singular")) { return false; }
    for (auto *widget : std::vector<Gtk::Widget *>{&wheel, &hueSat}) {
        writeNumericControl(find(widget, 1), 25);
        writeNumericControl(find(widget, 0), 120);
        if (!require(std::fabs(find(widget, 0).value - 120) < 1e-5 &&
                     std::fabs(find(widget, 1).value - 25) < 1e-5, "wheel hue/saturation preserve each other")) { return false; }
    }
    writeNumericControl(find(&wheel, 2), 1.5);
    if (!require(std::fabs(find(&wheel, 2).value - 1.5) < 1e-5, "wheel scale follows native range")) { return false; }

    std::vector<CoordinateAdjuster::Boundaries> bounds(2);
    bounds[0].minVal = .1; bounds[0].maxVal = .9;
    bounds[1].minVal = .2; bounds[1].maxVal = .8;
    point.startNumericalAdjustment(bounds);
    std::vector<NumericControl> axes;
    for (const auto &entry : controls()) {
        if (entry.kind == NumericControl::Kind::SPIN && entry.widget != &integer) { axes.push_back(entry); }
    }
    if (!require(axes.size() == 2 && axes[0].available && axes[1].available,
            "selected curve point exposes two bounded numeric coordinates")) { return false; }
    const auto priorCoordinateChanges = coordinates.changes;
    if (axes[0].label != M("CURVEEDITOR_AXIS_IN")) { std::swap(axes[0], axes[1]); }
    writeNumericControl(axes[0], 40);
    writeNumericControl(axes[1], 60);
    std::cout << "  point axes: " << axes[0].label << ", " << axes[1].label << " = "
        << coordinates.values[0] << ", " << coordinates.values[1] << " changes="
        << priorCoordinateChanges << "->" << coordinates.changes << std::endl;
    if (!require(std::fabs(coordinates.values[0] - .4) < 1e-8 &&
                 std::fabs(coordinates.values[1] - .6) < 1e-8 && coordinates.changes == priorCoordinateChanges + 2,
            "curve coordinates use native normalized provider callbacks")) { return false; }
    const auto context = numericContextId({&tool});
    std::vector<double> samePoint = {.4, .6};
    point.switchAdjustedPoint(samePoint, bounds);
    if (!require(context != numericContextId({&tool}), "identical-valued points still have distinct binding contexts")) { return false; }
    point.stopNumericalAdjustment();
    for (const auto &entry : controls()) {
        if (entry.widget == axes[0].widget && !require(!entry.available, "deselected point cannot be edited")) { return false; }
    }

    rtengine::CLUTParamDescriptor descriptor;
    descriptor.name = "custom_strength";
    descriptor.type = rtengine::CLUTParamType::PT_FLOAT;
    descriptor.value_min = -5; descriptor.value_max = 5;
    descriptor.value_default = {0}; descriptor.gui_step = .1;
    descriptor.gui_name = "Custom strength";
    rtengine::CLUTParamDescriptorList descriptors;
    descriptors.push_back(descriptor);
    lut.setParams(descriptors);
    lut.show_all();
    std::string oldKey;
    for (const auto &entry : controls()) {
        if (entry.label == "Custom strength") {
            oldKey = entry.id;
            writeNumericControl(entry, 2.5);
        }
    }
    if (!require(!oldKey.empty() && lut.getValue().at("custom_strength")[0] == 2.5,
            "dynamically described LUT numeric field is editable without a whitelist")) { return false; }
    lut.setParams(descriptors);
    lut.show_all();
    for (const auto &entry : controls()) {
        if (!require(entry.id != oldKey, "rebuilt LUT controls never reuse an old key")) { return false; }
    }
    std::cout << "  -> native numeric widget families PASSED!" << std::endl;
    return true;
}

bool testNumericModes(const std::vector<ToolPanel *> &panels, const std::string &path)
{
    using namespace art::liveparam;
    using namespace rtengine::procparams;
    ProcParams initial;
    std::map<std::string, ToolPanel *> owners;
    for (auto *panel : panels) { panel->write(&initial); owners[panel->getToolName()] = panel; }
    std::ofstream inventory(path);
    std::set<std::string> fields;
    unsigned snapshots = 0;
    const auto record = [&](const std::string &mode) {
        ++snapshots;
        std::set<std::string> keys;
        for (const auto &entry : collectNumericControls(panels)) {
            if (!keys.insert(entry.id).second || entry.toolLabel.empty() || entry.label.empty() ||
                !std::isfinite(entry.minimum) || !std::isfinite(entry.maximum) || entry.step <= 0 ||
                entry.minimum > entry.maximum || !std::isfinite(entry.value)) { return false; }
            const auto field = entry.tool + "\t" + entry.label + "\t" + std::to_string(int(entry.kind));
            fields.insert(field);
            inventory << mode << '\t' << field << '\t' << entry.minimum << '\t' << entry.maximum
                << '\t' << entry.available << '\n';
        }
        return true;
    };
    if (!record("initial")) { return false; }
    const auto read = [&](const std::string &tool, const ProcParams &parameters, const std::string &mode) {
        if (!owners.count(tool)) { return false; }
        owners.at(tool)->read(&parameters);
        owners.at(tool)->autoOpenCurve();
        return record(tool + "/" + mode);
    };
    for (const std::string method : {"usm", "rld", "psf"}) {
        auto parameters = initial;
        parameters.sharpening.enabled = true;
        parameters.sharpening.method = method;
        parameters.sharpening.edgesonly = parameters.sharpening.halocontrol = true;
        if (!read("sharpening", parameters, method)) { return false; }
    }
    for (int specification = 0; specification < 5; ++specification) {
        auto parameters = initial;
        parameters.resize.enabled = true;
        parameters.resize.dataspec = specification;
        if (!read("resize", parameters, std::to_string(specification))) { return false; }
    }
    for (const auto method : {WBParams::CAMERA, WBParams::AUTO, WBParams::CUSTOM_TEMP,
                              WBParams::CUSTOM_MULT, WBParams::CUSTOM_MULT_LEGACY}) {
        auto parameters = initial;
        parameters.wb.enabled = true;
        parameters.wb.method = method;
        if (!read("whitebalance", parameters, std::to_string(int(method)))) { return false; }
    }
    for (const auto mode : {ColorCorrectionParams::Mode::YUV, ColorCorrectionParams::Mode::RGB,
                            ColorCorrectionParams::Mode::HSL, ColorCorrectionParams::Mode::JZAZBZ,
                            ColorCorrectionParams::Mode::LUT}) {
        auto parameters = initial;
        parameters.colorcorrection.enabled = true;
        parameters.colorcorrection.regions[0].mode = mode;
        if (!read("colorcorrection", parameters, std::to_string(int(mode)))) { return false; }
    }
    auto parameters = initial;
    parameters.toneCurve.curve = {DCT_Parametric, .25, .5, .75, 0, 0, 0, 0};
    if (!read("tonecurve", parameters, "parametric")) { return false; }
    parameters.toneCurve.curve = {DCT_NURBS, 0, 0, .5, .5, 1, 1};
    if (!read("tonecurve", parameters, "control-points")) { return false; }
    // Same-valued regions must still be different command contexts.
    parameters = initial;
    parameters.colorcorrection.regions.resize(2);
    parameters.colorcorrection.masks.resize(2);
    parameters.colorcorrection.selectedRegion = 0;
    if (!read("colorcorrection", parameters, "region-0")) { return false; }
    const auto firstRegion = numericContextId(panels);
    parameters.colorcorrection.selectedRegion = 1;
    if (!read("colorcorrection", parameters, "region-1") || firstRegion == numericContextId(panels)) { return false; }
    for (auto *panel : panels) { panel->read(&initial); }
    inventory.close();
    std::cout << "  numeric modes: " << snapshots << " snapshots, " << fields.size()
        << " distinct named numeric fields; " << path << std::endl;
    return inventory.good() && snapshots >= 23 && fields.size() > 300;
}
