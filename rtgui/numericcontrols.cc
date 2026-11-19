#include "numericcontrols.h"
#include "adjuster.h"
#include "colorwheel.h"
#include "coordinateadjuster.h"
#include "multilangmgr.h"
#include "popuptogglebutton.h"
#include "shcselector.h"
#include "thresholdadjuster.h"
#include "toolpanel.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <locale>
#include <map>
#include <sstream>
#include <unordered_set>

namespace art {
namespace liveparam {
namespace {

std::string widgetId(Gtk::Widget *widget)
{
    static uint64_t next = 0;
    static const auto key = g_quark_from_static_string("art-numeric-control-id");
    auto *object = G_OBJECT(widget->gobj());
    auto *id = static_cast<const char *>(g_object_get_qdata(object, key));
    if (!id) {
        const auto value = "numeric-" + std::to_string(++next);
        g_object_set_qdata_full(object, key, g_strdup(value.c_str()), g_free);
        id = static_cast<const char *>(g_object_get_qdata(object, key));
    }
    return id;
}

template <typename Fn>
void forEachChild(Gtk::Widget *widget, Fn &&fn)
{
    gtk_container_foreach(
        GTK_CONTAINER(widget->gobj()),
        [](GtkWidget *childGobj, gpointer userData) {
            if (auto *child = Glib::wrap(childGobj)) {
                (*static_cast<Fn *>(userData))(child);
            }
        },
        &fn);
}

Gtk::SpinButton *spinIn(Gtk::Widget *widget)
{
    if (auto *spin = dynamic_cast<Gtk::SpinButton *>(widget)) {
        return spin;
    }
    if (GTK_IS_CONTAINER(widget->gobj())) {
        Gtk::SpinButton *found = nullptr;
        forEachChild(widget, [&](Gtk::Widget *child) {
            if (!found) {
                found = spinIn(child);
            }
        });
        return found;
    }
    return nullptr;
}

struct WidgetMeta {
    bool isContainer = false;
    bool isExpanderBox = false;
    Adjuster *adjuster = nullptr;
    Gtk::SpinButton *adjusterSpin = nullptr;
    ThresholdAdjuster *threshold = nullptr;
    SHCSelector *shc = nullptr;
    ColorWheel *wheel = nullptr;
    HueSatColorWheel *hsWheel = nullptr;
    Gtk::SpinButton *spin = nullptr;
    Gtk::Range *range = nullptr;
    Gtk::ComboBox *combo = nullptr;
    Gtk::ToggleButton *toggle = nullptr;
    PopUpToggleButton *popup = nullptr;
    Gtk::TreeView *tree = nullptr;
    CoordinateAdjuster *coordinates = nullptr;
};

const WidgetMeta &metaFor(Gtk::Widget *widget)
{
    static const auto key = g_quark_from_static_string("art-numeric-widget-meta");
    auto *object = G_OBJECT(widget->gobj());
    auto *meta = static_cast<WidgetMeta *>(g_object_get_qdata(object, key));
    if (!meta) {
        meta = new WidgetMeta();
        auto *gobj = widget->gobj();
        meta->isContainer = GTK_IS_CONTAINER(gobj);
        if (meta->isContainer) {
            meta->isExpanderBox = dynamic_cast<ExpanderBox *>(widget) != nullptr;
            if (GTK_IS_GRID(gobj)) {
                meta->adjuster = dynamic_cast<Adjuster *>(widget);
                if (meta->adjuster) {
                    meta->adjusterSpin = spinIn(widget);
                }
            } else if (GTK_IS_BOX(gobj)) {
                meta->threshold = dynamic_cast<ThresholdAdjuster *>(widget);
                if (!meta->threshold) {
                    meta->wheel = dynamic_cast<ColorWheel *>(widget);
                    if (meta->wheel) {
                        meta->hsWheel = dynamic_cast<HueSatColorWheel *>(meta->wheel);
                    }
                }
            }
            if (GTK_IS_COMBO_BOX(gobj)) {
                meta->combo = dynamic_cast<Gtk::ComboBox *>(widget);
            }
            if (GTK_IS_TOGGLE_BUTTON(gobj)) {
                meta->toggle = dynamic_cast<Gtk::ToggleButton *>(widget);
                if (meta->toggle) {
                    meta->popup = dynamic_cast<PopUpToggleButton *>(widget);
                }
            }
            if (GTK_IS_TREE_VIEW(gobj)) {
                meta->tree = dynamic_cast<Gtk::TreeView *>(widget);
            }
            if (GTK_IS_FLOW_BOX(gobj)) {
                meta->coordinates = dynamic_cast<CoordinateAdjuster *>(widget);
            }
        } else {
            if (GTK_IS_SPIN_BUTTON(gobj)) {
                meta->spin = dynamic_cast<Gtk::SpinButton *>(widget);
            } else if (GTK_IS_RANGE(gobj)) {
                meta->range = dynamic_cast<Gtk::Range *>(widget);
            } else if (GTK_IS_DRAWING_AREA(gobj)) {
                meta->shc = dynamic_cast<SHCSelector *>(widget);
            }
        }
        g_object_set_qdata_full(
            object, key, meta,
            [](gpointer ptr) { delete static_cast<WidgetMeta *>(ptr); });
    }
    return *meta;
}

std::string textOf(Gtk::Widget *widget)
{
    auto *label = dynamic_cast<Gtk::Label *>(widget);
    return label ? label->get_text().raw() : "";
}

std::string labelFor(Gtk::Widget *widget)
{
    const auto accessible = widget->get_accessible()->get_name();
    if (!accessible.empty()) {
        return accessible;
    }
    if (auto *parent = dynamic_cast<Gtk::Container *>(widget->get_parent())) {
        // Grids use the label directly to the left of the number.
        if (dynamic_cast<Gtk::Grid *>(parent)) {
            int column = 0, row = 0;
            gtk_container_child_get(GTK_CONTAINER(parent->gobj()), widget->gobj(),
                "left-attach", &column, "top-attach", &row, nullptr);
            for (auto *child : parent->get_children()) {
                int x = 0, y = 0;
                gtk_container_child_get(GTK_CONTAINER(parent->gobj()), child->gobj(),
                    "left-attach", &x, "top-attach", &y, nullptr);
                if (y == row && x == column - 1 && !textOf(child).empty()) {
                    return textOf(child);
                }
            }
        } else {
            std::string previous;
            for (auto *child : parent->get_children()) {
                if (child == widget && !previous.empty()) {
                    return previous;
                }
                if (!textOf(child).empty()) {
                    previous = textOf(child);
                }
            }
        }
    }
    return "";
}

std::string titleOf(Gtk::Widget *widget)
{
    const auto label = textOf(widget);
    if (!label.empty()) {
        return label;
    }
    if (auto *container = dynamic_cast<Gtk::Container *>(widget)) {
        for (auto *child : container->get_children()) {
            const auto title = titleOf(child);
            if (!title.empty()) { return title; }
        }
    }
    return "";
}

bool available(Gtk::Widget *widget, bool enabled)
{
    for (auto *node = widget; node; node = node->get_parent()) {
        if (!node->get_visible() && !metaFor(node).isExpanderBox) {
            return false;
        }
        if (enabled && !node->get_sensitive()) {
            return false;
        }
    }
    return true;
}

std::map<Gtk::Widget *, ToolPanel *> rootsFor(
    const std::vector<ToolPanel *> &panels)
{
    std::map<Gtk::Widget *, ToolPanel *> roots;
    for (auto *panel : panels) {
        auto *root = panel->getExpander()
            ? static_cast<Gtk::Widget *>(panel->getExpander())
            : dynamic_cast<Gtk::Widget *>(panel);
        if (root) {
            roots[root] = panel;
        }
    }
    return roots;
}

struct OwnerInfo {
    Gtk::Widget *root = nullptr;
    ToolPanel *owner = nullptr;
    std::string tool;
    std::string toolLabel;
    bool enabled = true;
};

void collect(Gtk::Widget *widget, const OwnerInfo &ownerInfo,
             const std::map<Gtk::Widget *, ToolPanel *> &roots,
             bool includeLabels,
             std::vector<NumericControl> &controls)
{
    const auto &meta = metaFor(widget);
    if (meta.isContainer && widget != ownerInfo.root && roots.count(widget)) {
        return; // A nested photo tool owns its own controls.
    }
    const auto initControl = [&]() {
        NumericControl control;
        control.id = widgetId(widget);
        control.tool = ownerInfo.tool;
        control.toolLabel = ownerInfo.toolLabel;
        control.enabled = ownerInfo.enabled;
        control.available = available(widget, control.enabled);
        control.widget = widget;
        control.owner = ownerInfo.owner;
        return control;
    };
    const auto append = [&](NumericControl value) {
        if (includeLabels) {
            // Frames distinguish repeated channel/curve labels without exposing IDs.
            for (auto *node = widget->get_parent(); node && node != ownerInfo.root; node = node->get_parent()) {
                if (GTK_IS_FRAME(node->gobj())) {
                    if (auto *frame = dynamic_cast<Gtk::Frame *>(node)) {
                        const auto label = frame->get_label().raw();
                        if (!label.empty() && label != value.label) {
                            value.label = label + (value.label.empty() ? "" : " / " + value.label);
                        }
                    }
                }
            }
            if (value.label.empty()) {
                value.label = "Value " + std::to_string(controls.size() + 1);
            }
        }
        controls.push_back(std::move(value));
    };
    if (auto *adjuster = meta.adjuster) {
        auto *spin = meta.adjusterSpin;
        if (!spin) {
            return;
        }
        auto control = initControl();
        control.kind = NumericControl::Kind::ADJUSTER;
        control.minimum = spin->get_adjustment()->get_lower();
        control.maximum = spin->get_adjustment()->get_upper();
        control.step = adjuster->getStepValue();
        control.value = adjuster->getValue();
        control.pending = adjuster->hasPendingNumericChange();
        if (includeLabels) {
            control.label = widget->get_accessible()->get_name();
            if (control.label.empty()) {
                control.label = adjuster->getLabel();
            }
            if (control.label.empty()) {
                control.label = labelFor(widget);
            }
        }
        if (control.tool == "exposure" && adjuster->getLabel() == M("TP_EXPOSURE_EXPCOMP")) {
            control.id = "Exposure.Compensation";
        }
        append(std::move(control));
        return; // The internal spin and scale represent this same value.
    }
    if (auto *threshold = meta.threshold) {
        auto control = initControl();
        auto *selector = threshold->getThresholdSelector();
        for (unsigned i = 0; i < (selector->isDouble() ? 4u : 2u); ++i) {
            auto component = control;
            component.kind = NumericControl::Kind::THRESHOLD;
            component.pending = threshold->hasPendingNumericChange();
            component.available = component.available && selector->numericComponentActive(i);
            component.component = i;
            component.id += "/" + std::to_string(i);
            if (includeLabels) {
                const char *names[] = {"Bottom left", "Top left", "Bottom right", "Top right"};
                component.label = threshold->getNumericLabel().raw() + " / " + names[i];
            }
            selector->numericRange(i, component.minimum, component.maximum, component.step);
            component.value = selector->shapePositionValue(
                static_cast<ThresholdSelector::ThreshCursorId>(i));
            append(std::move(component));
        }
        return;
    }
    if (auto *shc = meta.shc) {
        auto control = initControl();
        double values[3];
        shc->getPositions(values[0], values[1], values[2]);
        for (unsigned i = 0; i < 3; ++i) {
            auto component = control;
            component.kind = NumericControl::Kind::SHC;
            component.component = i;
            component.id += "/" + std::to_string(i);
            if (includeLabels) {
                component.label = "Curve boundary " + std::to_string(i + 1);
            }
            component.minimum = i ? values[i - 1] : 0;
            component.maximum = i < 2 ? values[i + 1] : 1;
            component.step = .001;
            component.value = values[i];
            append(std::move(component));
        }
        return;
    }
    if (auto *wheel = meta.wheel) {
        auto control = initControl();
        auto *hs = meta.hsWheel;
        double x = 0, y = 0, scale = 1, hue = 0, saturation = 0;
        if (hs) {
            hs->getParams(hue, saturation);
        } else {
            wheel->getParams(x, y, scale);
            hue = std::atan2(y, x) * 180 / std::acos(-1.0);
            if (hue < 0) { hue += 360; }
            saturation = std::hypot(x, y) * 100;
        }
        for (unsigned i = 0; i < (hs ? 2u : 3u); ++i) {
            auto component = control;
            component.kind = NumericControl::Kind::WHEEL;
            component.pending = wheel->hasPendingNumericChange();
            component.component = i;
            component.id += "/" + std::to_string(i);
            if (includeLabels) {
                component.label = i == 0 ? M("TP_COLORCORRECTION_H").raw()
                    : i == 1 ? M("TP_COLORCORRECTION_S").raw() : "Scale";
            }
            component.minimum = i == 2 ? .2 : 0;
            component.maximum = i == 0 ? 360 : i == 1 ? (hs ? 100 : 250) : 2.5;
            component.step = i == 2 ? .01 : .1;
            component.value = i == 0 ? hue : i == 1 ? saturation : scale;
            append(std::move(component));
        }
        return;
    }
    if (auto *spin = meta.spin) {
        auto control = initControl();
        control.kind = NumericControl::Kind::SPIN;
        control.minimum = spin->get_adjustment()->get_lower();
        control.maximum = spin->get_adjustment()->get_upper();
        control.step = spin->get_adjustment()->get_step_increment();
        control.value = spin->get_value();
        if (includeLabels) {
            control.label = labelFor(widget);
        }
        append(std::move(control));
        return;
    }
    if (auto *range = meta.range) {
        auto control = initControl();
        control.kind = NumericControl::Kind::RANGE;
        control.minimum = range->get_adjustment()->get_lower();
        control.maximum = range->get_adjustment()->get_upper();
        control.step = range->get_adjustment()->get_step_increment();
        control.value = range->get_value();
        if (includeLabels) {
            control.label = labelFor(widget);
        }
        append(std::move(control));
        return;
    }
    if (meta.isContainer) {
        forEachChild(widget, [&](Gtk::Widget *child) {
            collect(child, ownerInfo, roots, includeLabels, controls);
        });
    }
}

void contextWidgets(Gtk::Widget *widget,
                    std::unordered_set<Gtk::Widget *> &visited,
                    std::ostream &data)
{
    if (!visited.insert(widget).second) {
        return;
    }
    const auto &meta = metaFor(widget);
    if (auto *combo = meta.combo) {
        data << widgetId(widget) << ':' << combo->get_active_row_number() << '\n';
    }
    if (auto *toggle = meta.toggle) {
        data << widgetId(widget) << ':' << toggle->get_active() << '\n';
    }
    if (auto *popup = meta.popup) {
        data << widgetId(widget) << ':' << popup->getSelected() << '\n';
    }
    if (auto *tree = meta.tree) {
        data << widgetId(widget) << ':';
        for (const auto &path : tree->get_selection()->get_selected_rows()) {
            data << path.to_string() << ',';
        }
        data << '\n';
    }
    if (auto *coordinates = meta.coordinates) {
        data << widgetId(widget) << ':' << coordinates->numericBindingVersion() << '\n';
    }
    if (meta.isContainer) {
        forEachChild(widget, [&](Gtk::Widget *child) {
            contextWidgets(child, visited, data);
        });
    }
}

} // namespace

std::vector<NumericControl> collectNumericControls(
    const std::vector<ToolPanel *> &panels, bool includeLabels)
{
    const auto roots = rootsFor(panels);
    std::vector<NumericControl> controls;
    controls.reserve(384);
    for (const auto &entry : roots) {
        auto *root = entry.first;
        auto *owner = entry.second;
        auto *foldable = dynamic_cast<FoldableToolPanel *>(owner);
        OwnerInfo info;
        info.root = root;
        info.owner = owner;
        info.tool = owner->getToolName();
        if (includeLabels) {
            info.toolLabel = owner->getExpander()
                ? titleOf(owner->getExpander()->getLabelWidget()) : info.tool;
            if (info.toolLabel.empty()) {
                info.toolLabel = info.tool;
            }
        }
        info.enabled = !foldable || !foldable->getUseEnabled() || foldable->getEnabled();
        collect(root, info, roots, includeLabels, controls);
    }
    std::sort(controls.begin(), controls.end(), [](const NumericControl &a, const NumericControl &b) {
        return a.tool == b.tool ? a.id < b.id : a.tool < b.tool;
    });
    return controls;
}

std::string numericContextId(const std::vector<ToolPanel *> &panels)
{
    rtengine::procparams::ProcParams parameters;
    for (auto *panel : panels) {
        panel->write(&parameters);
    }
    std::ostringstream data;
    data.imbue(std::locale::classic());
    data << parameters.to_data() << std::setprecision(17);
    for (const auto &control : collectNumericControls(panels, false)) {
        data << control.id << ':' << control.value << ':' << control.minimum
            << ':' << control.maximum << ':' << control.available << '\n';
    }
    std::unordered_set<Gtk::Widget *> visited;
    visited.reserve(4096);
    for (const auto &root : rootsFor(panels)) {
        contextWidgets(root.first, visited, data);
    }
    const auto bytes = data.str();
    std::unique_ptr<gchar, decltype(&g_free)> digest(
        g_compute_checksum_for_string(G_CHECKSUM_SHA256, bytes.c_str(), bytes.size()), g_free);
    return digest.get();
}

void writeNumericControl(const NumericControl &control, double value)
{
    switch (control.kind) {
    case NumericControl::Kind::ADJUSTER:
        dynamic_cast<Adjuster *>(control.widget)->applyNumericValue(value);
        break;
    case NumericControl::Kind::SPIN: {
        auto *spin = dynamic_cast<Gtk::SpinButton *>(control.widget);
        spin->set_value(value);
        // Commit the displayed precision through GTK, as a typed edit does.
        // Integer fields must not acknowledge a fractional value they discard.
        spin->update();
        break;
    }
    case NumericControl::Kind::RANGE:
        dynamic_cast<Gtk::Range *>(control.widget)->set_value(value);
        break;
    case NumericControl::Kind::THRESHOLD:
        dynamic_cast<ThresholdAdjuster *>(control.widget)->applyNumericValue(control.component,
            std::round(value / control.step) * control.step);
        break;
    case NumericControl::Kind::SHC:
        dynamic_cast<SHCSelector *>(control.widget)->applyNumericValue(control.component, value);
        break;
    case NumericControl::Kind::WHEEL:
        dynamic_cast<ColorWheel *>(control.widget)->applyNumericValue(control.component, value);
        break;
    }
}

double readNumericControlValue(const NumericControl &control)
{
    if (!control.widget) {
        return control.value;
    }
    switch (control.kind) {
    case NumericControl::Kind::ADJUSTER:
        if (auto *adj = dynamic_cast<Adjuster *>(control.widget)) {
            return adj->getValue();
        }
        break;
    case NumericControl::Kind::SPIN:
        if (auto *spin = dynamic_cast<Gtk::SpinButton *>(control.widget)) {
            return spin->get_value();
        }
        break;
    case NumericControl::Kind::RANGE:
        if (auto *range = dynamic_cast<Gtk::Range *>(control.widget)) {
            return range->get_value();
        }
        break;
    case NumericControl::Kind::THRESHOLD:
        if (auto *threshold = dynamic_cast<ThresholdAdjuster *>(control.widget)) {
            if (auto *selector = threshold->getThresholdSelector()) {
                return selector->shapePositionValue(
                    static_cast<ThresholdSelector::ThreshCursorId>(control.component));
            }
        }
        break;
    case NumericControl::Kind::SHC:
        if (auto *shc = dynamic_cast<SHCSelector *>(control.widget)) {
            double values[3] = {0, 0, 0};
            shc->getPositions(values[0], values[1], values[2]);
            if (control.component < 3) {
                return values[control.component];
            }
        }
        break;
    case NumericControl::Kind::WHEEL:
        if (auto *wheel = dynamic_cast<ColorWheel *>(control.widget)) {
            auto *hs = dynamic_cast<HueSatColorWheel *>(wheel);
            double x = 0, y = 0, scale = 1, hue = 0, saturation = 0;
            if (hs) {
                hs->getParams(hue, saturation);
            } else {
                wheel->getParams(x, y, scale);
                hue = std::atan2(y, x) * 180 / std::acos(-1.0);
                if (hue < 0) { hue += 360; }
                saturation = std::hypot(x, y) * 100;
            }
            return control.component == 0 ? hue : control.component == 1 ? saturation : scale;
        }
        break;
    }
    return control.value;
}

} // namespace liveparam
} // namespace art
