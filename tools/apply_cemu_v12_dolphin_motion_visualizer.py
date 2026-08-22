from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v12_dolphin_motion_visualizer.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


controller_h = root / "src/input/api/SDL/SDLController.h"
controller_cpp = root / "src/input/api/SDL/SDLController.cpp"
provider_h = root / "src/input/api/SDL/SDLControllerProvider.h"
provider_cpp = root / "src/input/api/SDL/SDLControllerProvider.cpp"
panel_cpp = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"

# =============================================================================
# 1) Expose read-only live motion/calibration state for native wxWidgets
#    visualizers. This is fed by the exact same samples used by KPAD/WPAD.
# =============================================================================
replace_once(
    provider_h,
    '''class SDLControllerProvider : public ControllerProviderBase
{
\tfriend class SDLController;
public:
''',
    '''class SDLControllerProvider : public ControllerProviderBase
{
\tfriend class SDLController;
public:
\tstruct DolphinMotionDebug
\t{
\t\tglm::vec3 gyro{};
\t\tglm::vec3 accel{};
\t\tglm::vec3 bias{};
\t\tfloat calibration_progress{};
\t\tfloat sample_rate_hz{};
\t\tbool stable{};
\t\tbool calibrated{};
\t\tuint64 timestamp{};
\t};

''',
    "declare Dolphin motion debug snapshot",
)

replace_once(
    provider_h,
    '''\tMotionSample motion_sample(SDL_JoystickID diid);
\tbool dolphin_pointer_motion(SDL_JoystickID diid, glm::vec3& gyro, glm::vec3& accel, uint64& timestamp);
''',
    '''\tMotionSample motion_sample(SDL_JoystickID diid);
\tbool dolphin_pointer_motion(SDL_JoystickID diid, glm::vec3& gyro, glm::vec3& accel, uint64& timestamp);
\tbool dolphin_motion_debug(SDL_JoystickID diid, DolphinMotionDebug& debug);
''',
    "expose Dolphin motion debug getter",
)

replace_once(
    provider_h,
    '''\t\tbool dolphin_calibration_initialized{};

\t\tMotionState() = default;
''',
    '''\t\tbool dolphin_calibration_initialized{};
\t\tbool dolphin_calibration_stable{};
\t\tbool dolphin_calibration_complete{};
\t\tfloat dolphin_sample_rate_hz{};
\t\tglm::vec3 dolphin_motion_gyro{};
\t\tglm::vec3 dolphin_motion_acc{};

\t\tMotionState() = default;
''',
    "store live Dolphin motion calibration state",
)

replace_once(
    provider_cpp,
    '''bool SDLControllerProvider::dolphin_pointer_motion(SDL_JoystickID diid, glm::vec3& gyro, glm::vec3& accel, uint64& timestamp)
{
\tstd::shared_lock lock(s_mutex);
\tconst auto it = s_motion_states.find(diid);
\tif (it == s_motion_states.end() || !it->second.dolphin_pointer_has_gyro || !it->second.dolphin_pointer_has_acc)
\t\treturn false;
\tgyro = it->second.dolphin_pointer_gyro;
\taccel = it->second.dolphin_pointer_acc;
\ttimestamp = it->second.dolphin_pointer_timestamp;
\treturn timestamp != 0;
}
''',
    '''bool SDLControllerProvider::dolphin_pointer_motion(SDL_JoystickID diid, glm::vec3& gyro, glm::vec3& accel, uint64& timestamp)
{
\tstd::shared_lock lock(s_mutex);
\tconst auto it = s_motion_states.find(diid);
\tif (it == s_motion_states.end() || !it->second.dolphin_pointer_has_gyro || !it->second.dolphin_pointer_has_acc)
\t\treturn false;
\tgyro = it->second.dolphin_pointer_gyro;
\taccel = it->second.dolphin_pointer_acc;
\ttimestamp = it->second.dolphin_pointer_timestamp;
\treturn timestamp != 0;
}

bool SDLControllerProvider::dolphin_motion_debug(SDL_JoystickID diid, DolphinMotionDebug& debug)
{
\tstd::shared_lock lock(s_mutex);
\tconst auto it = s_motion_states.find(diid);
\tif (it == s_motion_states.end() || !it->second.dolphin_pointer_has_gyro || !it->second.dolphin_pointer_has_acc)
\t\treturn false;
\tconst auto& state = it->second;
\tdebug.gyro = state.dolphin_motion_gyro;
\tdebug.accel = state.dolphin_motion_acc;
\tdebug.bias = state.dolphin_gyro_bias;
\tdebug.sample_rate_hz = state.dolphin_sample_rate_hz;
\tdebug.stable = state.dolphin_calibration_stable;
\tdebug.calibrated = state.dolphin_calibration_complete;
\tdebug.timestamp = state.dolphin_pointer_timestamp;
\tif (state.dolphin_calibration_start != 0 && debug.timestamp >= state.dolphin_calibration_start)
\t{
\t\tconst float elapsed = static_cast<float>(debug.timestamp - state.dolphin_calibration_start) / 3000000000.0f;
\t\tdebug.calibration_progress = std::clamp(elapsed, 0.0f, 1.0f);
\t}
\treturn debug.timestamp != 0;
}
''',
    "implement thread-safe Dolphin motion debug snapshot",
)

# Record the stable-window state without changing Dolphin's calibration rules.
replace_once(
    provider_cpp,
    '''\t\t\t\t\t\tconst double frequency = elapsed_s > 0.0 ? static_cast<double>(state.dolphin_calibration_count) / elapsed_s : kDolphinMinCalibrationHz;
\t\t\t\t\t\tconst bool unstable = std::abs(difference.x) > kDolphinGyroDeadzone ||
''',
    '''\t\t\t\t\t\tconst double frequency = elapsed_s > 0.0 ? static_cast<double>(state.dolphin_calibration_count) / elapsed_s : kDolphinMinCalibrationHz;
\t\t\t\t\t\tstate.dolphin_sample_rate_hz = static_cast<float>(frequency);
\t\t\t\t\t\tconst bool unstable = std::abs(difference.x) > kDolphinGyroDeadzone ||
''',
    "publish Dolphin stable sampling frequency",
)

replace_once(
    provider_cpp,
    '''\t\t\t\t\t\tif (unstable)
\t\t\t\t\t\t\trestart_calibration();
\t\t\t\t\t\telse
\t\t\t\t\t\t{
''',
    '''\t\t\t\t\t\tstate.dolphin_calibration_stable = !unstable;
\t\t\t\t\t\tif (unstable)
\t\t\t\t\t\t{
\t\t\t\t\t\t\tstate.dolphin_calibration_complete = false;
\t\t\t\t\t\t\trestart_calibration();
\t\t\t\t\t\t}
\t\t\t\t\t\telse
\t\t\t\t\t\t{
''',
    "track stable versus moving calibration window",
)

replace_once(
    provider_cpp,
    '''\t\t\t\t\t\t\tif (elapsed_ns >= kDolphinCalibrationPeriodNs)
\t\t\t\t\t\t\t\tstate.dolphin_gyro_bias = state.dolphin_calibration_sum / static_cast<float>(state.dolphin_calibration_count);
''',
    '''\t\t\t\t\t\t\tif (elapsed_ns >= kDolphinCalibrationPeriodNs)
\t\t\t\t\t\t\t{
\t\t\t\t\t\t\t\tstate.dolphin_gyro_bias = state.dolphin_calibration_sum / static_cast<float>(state.dolphin_calibration_count);
\t\t\t\t\t\t\t\tstate.dolphin_calibration_complete = true;
\t\t\t\t\t\t\t}
''',
    "mark completion after Dolphin 3 second stable mean",
)

# Apply the scale/invert values which V8-V11 persisted but never consumed.
replace_once(
    provider_cpp,
    '''\t\t\tif (tracking.hasAcc && tracking.hasGyro)
\t\t\t{
\t\t\t\tauto ts = std::max(tracking.lastTimestampGyro, tracking.lastTimestampAccel);
''',
    '''\t\t\tif (tracking.hasAcc && tracking.hasGyro)
\t\t\t{
\t\t\t\tif (const auto config = s_joycon_orientation_states.find(id);
\t\t\t\t\tconfig != s_joycon_orientation_states.end())
\t\t\t\t{
\t\t\t\t\tconst glm::vec3 scale{ config->second.motion_scale_x, config->second.motion_scale_y, config->second.motion_scale_z };
\t\t\t\t\ttracking.acc *= scale;
\t\t\t\t\ttracking.gyro *= scale;
\t\t\t\t\tstate.dolphin_motion_acc = tracking.acc;
\t\t\t\t\tstate.dolphin_motion_gyro = tracking.gyro;
\t\t\t\t}

\t\t\t\tauto ts = std::max(tracking.lastTimestampGyro, tracking.lastTimestampAccel);
''',
    "apply persisted Dolphin per-axis motion scale and inversion",
)

# =============================================================================
# 2) Pointer preview state, improved deadzone anchor, and a dedicated recenter
#    hotkey. Pointer enable/disable hotkey remains intact for V2-V11 users.
# =============================================================================
replace_once(
    controller_h,
    '''\tvoid set_pointer_enabled(bool enabled, bool notify = true);
\tvoid recenter_joycon_pointer(bool notify = true);
\tbool update_joycon_pointer(glm::vec2& position, glm::vec2& previous);
''',
    '''\tvoid set_pointer_enabled(bool enabled, bool notify = true);
\tvoid recenter_joycon_pointer(bool notify = true);
\tbool update_joycon_pointer(glm::vec2& position, glm::vec2& previous);
\tbool get_joycon_pointer_debug(glm::vec2& sensor_target, glm::vec2& deadzone_target, glm::vec2& output) const;
\tbool get_dolphin_motion_debug(SDLControllerProvider::DolphinMotionDebug& debug) const;
\tstd::vector<uint32> get_pointer_recenter_hotkey() const;
\tvoid set_pointer_recenter_hotkey(std::vector<uint32> buttons);
''',
    "declare V12 preview and recenter hotkey APIs",
)

replace_once(
    controller_h,
    '''\tstd::vector<uint32> m_pointer_hotkey{};
\tstd::atomic_bool m_pointer_enabled{ true };
''',
    '''\tstd::vector<uint32> m_pointer_hotkey{};
\tstd::vector<uint32> m_pointer_recenter_hotkey{};
\tstd::atomic_bool m_pointer_enabled{ true };
''',
    "store dedicated pointer recenter hotkey",
)

replace_once(
    controller_h,
    '''\tbool m_dolphin_recenter_requested = true;
\tglm::vec2 m_dolphin_pointer_target{ 0.5f, 0.5f };
''',
    '''\tbool m_dolphin_recenter_requested = true;
\tglm::vec2 m_dolphin_pointer_sensor_target{ 0.5f, 0.5f };
\tglm::vec2 m_dolphin_pointer_target{ 0.5f, 0.5f };
''',
    "store raw pointer target for live visualization",
)

replace_once(
    controller_h,
    '''\tbool m_pointer_hotkey_latched = false;

\tbool is_hotkey_pressed(const ControllerButtonState& buttons, const std::vector<uint32>& hotkey) const;
''',
    '''\tbool m_pointer_hotkey_latched = false;
\tbool m_pointer_recenter_hotkey_latched = false;

\tbool is_hotkey_pressed(const ControllerButtonState& buttons, const std::vector<uint32>& hotkey, size_t minimum_buttons = 2) const;
''',
    "add recenter latch and single-button hotkey support",
)

replace_once(
    controller_cpp,
    '''void SDLController::normalize_hotkey(std::vector<uint32>& buttons) const
{
\tstd::erase_if(buttons, [](uint32 id) { return id >= SDL_GAMEPAD_BUTTON_COUNT; });
\tstd::sort(buttons.begin(), buttons.end());
\tbuttons.erase(std::unique(buttons.begin(), buttons.end()), buttons.end());
\tif (buttons.size() < 2)
\t\tbuttons.clear();
}
''',
    '''void SDLController::normalize_hotkey(std::vector<uint32>& buttons) const
{
\tstd::erase_if(buttons, [](uint32 id) { return id >= SDL_GAMEPAD_BUTTON_COUNT; });
\tstd::sort(buttons.begin(), buttons.end());
\tbuttons.erase(std::unique(buttons.begin(), buttons.end()), buttons.end());
\tif (buttons.size() < 2)
\t\tbuttons.clear();
}
''',
    "retain combo-only normalization for legacy hotkeys",
)

replace_once(
    controller_cpp,
    '''std::vector<uint32> SDLController::get_pointer_hotkey() const
{
\tstd::scoped_lock lock(m_controller_mutex);
\treturn m_pointer_hotkey;
}
''',
    '''std::vector<uint32> SDLController::get_pointer_hotkey() const
{
\tstd::scoped_lock lock(m_controller_mutex);
\treturn m_pointer_hotkey;
}

std::vector<uint32> SDLController::get_pointer_recenter_hotkey() const
{
\tstd::scoped_lock lock(m_controller_mutex);
\treturn m_pointer_recenter_hotkey;
}
''',
    "read dedicated pointer recenter hotkey",
)

replace_once(
    controller_cpp,
    '''void SDLController::set_pointer_hotkey(std::vector<uint32> buttons)
{
\tnormalize_hotkey(buttons);
\tstd::scoped_lock lock(m_controller_mutex);
\tm_pointer_hotkey = std::move(buttons);
\tm_pointer_hotkey_latched = false;
}
''',
    '''void SDLController::set_pointer_hotkey(std::vector<uint32> buttons)
{
\tnormalize_hotkey(buttons);
\tstd::scoped_lock lock(m_controller_mutex);
\tm_pointer_hotkey = std::move(buttons);
\tm_pointer_hotkey_latched = false;
}

void SDLController::set_pointer_recenter_hotkey(std::vector<uint32> buttons)
{
\tstd::erase_if(buttons, [](uint32 id) { return id >= SDL_GAMEPAD_BUTTON_COUNT; });
\tstd::sort(buttons.begin(), buttons.end());
\tbuttons.erase(std::unique(buttons.begin(), buttons.end()), buttons.end());
\tstd::scoped_lock lock(m_controller_mutex);
\tm_pointer_recenter_hotkey = std::move(buttons);
\tm_pointer_recenter_hotkey_latched = false;
}
''',
    "allow Dolphin-style one-button recenter shortcut",
)

replace_once(
    controller_cpp,
    '''\tconst glm::vec2 target{
\t\tstd::clamp(0.5f + 0.5f * (yaw / max_yaw), 0.0f, 1.0f),
\t\tstd::clamp(0.5f + 0.5f * (pitch / max_pitch), 0.0f, 1.0f)
\t};

\t// V11 presentation layer. Keep Dolphin's quaternion/IMU result above untouched;
''',
    '''\tconst glm::vec2 target{
\t\tstd::clamp(0.5f + 0.5f * (yaw / max_yaw), 0.0f, 1.0f),
\t\tstd::clamp(0.5f + 0.5f * (pitch / max_pitch), 0.0f, 1.0f)
\t};
\tm_dolphin_pointer_sensor_target = target;

\t// V11 presentation layer. Keep Dolphin's quaternion/IMU result above untouched;
''',
    "publish raw Dolphin pointer target",
)

replace_once(
    controller_cpp,
    '''\tconst glm::vec2 target_delta = target - m_joycon_pointer_position;
''',
    '''\tconst glm::vec2 target_delta = target - m_dolphin_pointer_target;
''',
    "measure pointer deadzone from accepted target instead of lagging output",
)

replace_once(
    controller_cpp,
    '''\t\tfiltered_target = m_joycon_pointer_position;
''',
    '''\t\tfiltered_target = m_dolphin_pointer_target;
''',
    "hold accepted target inside pointer deadzone",
)

replace_once(
    controller_cpp,
    '''\t\tfiltered_target = m_joycon_pointer_position + target_delta * std::clamp(active_fraction, 0.0f, 1.0f);
''',
    '''\t\tfiltered_target = m_dolphin_pointer_target + target_delta * std::clamp(active_fraction, 0.0f, 1.0f);
''',
    "advance pointer deadzone anchor continuously without smoothing feedback",
)

replace_once(
    controller_cpp,
    '''\tposition = m_joycon_pointer_position;
\tprevious = m_joycon_pointer_previous;
\treturn true;
}

std::vector<uint32> SDLController::get_pressed_buttons_for_hotkey()
''',
    '''\tposition = m_joycon_pointer_position;
\tprevious = m_joycon_pointer_previous;
\treturn true;
}

bool SDLController::get_joycon_pointer_debug(glm::vec2& sensor_target, glm::vec2& deadzone_target, glm::vec2& output) const
{
\tstd::scoped_lock lock(m_joycon_pointer_mutex);
\tif (!m_joycon_pointer_initialized)
\t\treturn false;
\tsensor_target = m_dolphin_pointer_sensor_target;
\tdeadzone_target = m_dolphin_pointer_target;
\toutput = m_joycon_pointer_position;
\treturn true;
}

bool SDLController::get_dolphin_motion_debug(SDLControllerProvider::DolphinMotionDebug& debug) const
{
\treturn m_diid >= 0 && m_provider->dolphin_motion_debug(m_diid, debug);
}

std::vector<uint32> SDLController::get_pressed_buttons_for_hotkey()
''',
    "implement read-only pointer and motion preview APIs",
)

replace_once(
    controller_cpp,
    '''bool SDLController::is_hotkey_pressed(const ControllerButtonState& buttons, const std::vector<uint32>& hotkey) const
{
\tif (hotkey.size() < 2)
''',
    '''bool SDLController::is_hotkey_pressed(const ControllerButtonState& buttons, const std::vector<uint32>& hotkey, size_t minimum_buttons) const
{
\tif (hotkey.size() < minimum_buttons)
''',
    "support one-button recenter while legacy hotkeys stay combo-only",
)

replace_once(
    controller_cpp,
    '''\tnode.append_child("joycon_pointer_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_pointer_hotkey()).c_str());
''',
    '''\tnode.append_child("joycon_pointer_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_pointer_hotkey()).c_str());
\tnode.append_child("joycon_pointer_recenter_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_pointer_recenter_hotkey()).c_str());
''',
    "save pointer recenter shortcut in profile",
)

replace_once(
    controller_cpp,
    '''\tif (const auto value = node.child("joycon_pointer_hotkey"))
\t\tset_pointer_hotkey(ParseJoyConHotkey(value.child_value()));
''',
    '''\tif (const auto value = node.child("joycon_pointer_hotkey"))
\t\tset_pointer_hotkey(ParseJoyConHotkey(value.child_value()));
\tif (const auto value = node.child("joycon_pointer_recenter_hotkey"))
\t\tset_pointer_recenter_hotkey(ParseJoyConHotkey(value.child_value()));
''',
    "load pointer recenter shortcut from profile",
)

replace_once(
    controller_cpp,
    '''\t\tconst bool pointer_pressed = is_hotkey_pressed(result.buttons, m_pointer_hotkey);
''',
    '''\t\tconst bool pointer_pressed = is_hotkey_pressed(result.buttons, m_pointer_hotkey);
\t\tconst bool recenter_pressed = is_hotkey_pressed(result.buttons, m_pointer_recenter_hotkey, 1);
''',
    "detect dedicated recenter shortcut",
)

replace_once(
    controller_cpp,
    '''\t\tif (pointer_pressed && !m_pointer_hotkey_latched)
\t\t\tset_pointer_enabled(!is_pointer_enabled());
\t\tm_vertical_hotkey_latched = vertical_pressed;
''',
    '''\t\tif (pointer_pressed && !m_pointer_hotkey_latched)
\t\t\tset_pointer_enabled(!is_pointer_enabled());
\t\tif (recenter_pressed && !m_pointer_recenter_hotkey_latched)
\t\t\trecenter_joycon_pointer();
\t\tm_vertical_hotkey_latched = vertical_pressed;
''',
    "execute manual pointer recenter shortcut",
)

replace_once(
    controller_cpp,
    '''\t\tm_pointer_hotkey_latched = pointer_pressed;
\t\tif (vertical_pressed)
''',
    '''\t\tm_pointer_hotkey_latched = pointer_pressed;
\t\tm_pointer_recenter_hotkey_latched = recenter_pressed;
\t\tif (vertical_pressed)
''',
    "latch manual recenter shortcut",
)

replace_once(
    controller_cpp,
    '''\t\tif (pointer_pressed)
\t\t\tconsume_hotkey(result.buttons, m_pointer_hotkey);
''',
    '''\t\tif (pointer_pressed)
\t\t\tconsume_hotkey(result.buttons, m_pointer_hotkey);
\t\tif (recenter_pressed)
\t\t\tconsume_hotkey(result.buttons, m_pointer_recenter_hotkey);
''',
    "consume configured recenter shortcut",
)

# =============================================================================
# 3) Replace V11 modal dialogs with live native wxWidgets visualizers and fix
#    V11's inverted physical-orientation selection. No Qt code is copied.
# =============================================================================
replace_once(
    panel_cpp,
    '''#include <wx/statbox.h>
#include <wx/settings.h>
''',
    '''#include <wx/statbox.h>
#include <wx/settings.h>
#include <wx/timer.h>
#include <cmath>
''',
    "V12 live visualizer includes",
)

start = panel_cpp.read_text(encoding="utf-8").find("void WiimoteInputPanel::on_joycon_pointer_dialog(wxCommandEvent&)")
end = panel_cpp.read_text(encoding="utf-8").find("void WiimoteInputPanel::on_joycon_pointer_recenter(wxCommandEvent&)")
if start < 0 or end < 0 or end <= start:
    raise RuntimeError("V11 dialog block anchors not found")

text = panel_cpp.read_text(encoding="utf-8")
new_dialogs = r'''void WiimoteInputPanel::on_joycon_pointer_dialog(wxCommandEvent&)
{
	const auto joycon = m_active_joycon.lock();
	if (!joycon)
		return;

	wxDialog dialog(this, wxID_ANY, _("Pointer - Dolphin Motion"), wxDefaultPosition, wxDefaultSize,
		wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
	const float original_yaw = joycon->get_pointer_yaw_degrees();
	const float original_pitch = joycon->get_pointer_pitch_degrees();
	const float original_deadzone = joycon->get_pointer_deadzone_degrees();
	const float original_smoothing = joycon->get_pointer_smoothing();
	const bool original_invert_x = joycon->get_pointer_invert_x();
	const bool original_invert_y = joycon->get_pointer_invert_y();
	auto* outer = new wxBoxSizer(wxVERTICAL);
	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Live pointer view: yellow = sensor, blue = deadzone target, green = smoothed game output.")),
		0, wxEXPAND | wxALL, 10);

	glm::vec2 sensor{0.5f}, accepted{0.5f}, output{0.5f};
	bool preview_valid = joycon->get_joycon_pointer_debug(sensor, accepted, output);
	auto* preview = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(520, 230), wxBORDER_SIMPLE);
	preview->SetMinSize(wxSize(440, 190));
	preview->SetBackgroundStyle(wxBG_STYLE_PAINT);
	preview->Bind(wxEVT_PAINT, [&](wxPaintEvent&) {
		wxAutoBufferedPaintDC dc(preview);
		const wxSize size = preview->GetClientSize();
		dc.SetBackground(wxBrush(wxColour(24, 27, 32)));
		dc.Clear();
		dc.SetPen(wxPen(wxColour(70, 76, 86), 1));
		dc.DrawLine(size.x / 2, 0, size.x / 2, size.y);
		dc.DrawLine(0, size.y / 2, size.x, size.y / 2);
		auto point = [&](const glm::vec2& value) {
			return wxPoint((int)std::lround(std::clamp(value.x, 0.0f, 1.0f) * (size.x - 1)),
				(int)std::lround(std::clamp(value.y, 0.0f, 1.0f) * (size.y - 1)));
		};
		if (!preview_valid)
		{
			dc.SetTextForeground(wxColour(210, 210, 210));
			dc.DrawText(_("Waiting for Joy-Con motion data..."), 12, 12);
			return;
		}
		const wxPoint raw = point(sensor);
		const wxPoint target = point(accepted);
		const wxPoint game = point(output);
		dc.SetPen(wxPen(wxColour(80, 155, 255), 2));
		dc.DrawLine(target, game);
		dc.SetPen(*wxTRANSPARENT_PEN);
		dc.SetBrush(wxBrush(wxColour(255, 205, 65)));
		dc.DrawCircle(raw, 5);
		dc.SetBrush(wxBrush(wxColour(75, 150, 255)));
		dc.DrawCircle(target, 6);
		dc.SetBrush(wxBrush(wxColour(70, 220, 120)));
		dc.DrawCircle(game, 7);
	});
	outer->Add(preview, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Point"));
	auto* grid = new wxFlexGridSizer(2, 6, 10);
	grid->AddGrowableCol(1, 1);
	auto make_spin = [&](const wxString& label, double value, double minv, double maxv, double step, int digits) {
		grid->Add(new wxStaticText(&dialog, wxID_ANY, label), 0, wxALIGN_CENTER_VERTICAL);
		auto* spin = new wxSpinCtrlDouble(&dialog, wxID_ANY);
		spin->SetRange(minv, maxv);
		spin->SetIncrement(step);
		spin->SetDigits(digits);
		spin->SetValue(value);
		grid->Add(spin, 1, wxEXPAND);
		return spin;
	};
	auto* yaw = make_spin(_("Horizontal range / Yaw (degrees)"), joycon->get_pointer_yaw_degrees(), 5.0, 120.0, 1.0, 1);
	auto* pitch = make_spin(_("Vertical range / Pitch (degrees)"), joycon->get_pointer_pitch_degrees(), 5.0, 120.0, 1.0, 1);
	auto* deadzone = make_spin(_("Deadzone (degrees)"), joycon->get_pointer_deadzone_degrees(), 0.0, 5.0, 0.05, 2);
	auto* smoothing = make_spin(_("Smooth (0 = direct)"), joycon->get_pointer_smoothing(), 0.0, 0.95, 0.01, 2);
	box->Add(grid, 0, wxEXPAND | wxALL, 8);

	auto* flags = new wxBoxSizer(wxHORIZONTAL);
	auto* invert_x = new wxCheckBox(&dialog, wxID_ANY, _("Invert X"));
	auto* invert_y = new wxCheckBox(&dialog, wxID_ANY, _("Invert Y"));
	invert_x->SetValue(joycon->get_pointer_invert_x());
	invert_y->SetValue(joycon->get_pointer_invert_y());
	flags->Add(invert_x, 0, wxRIGHT, 10);
	flags->Add(invert_y, 0, wxRIGHT, 10);
	auto* recenter = new wxButton(&dialog, wxID_ANY, _("Recenter now"));
	recenter->Bind(wxEVT_BUTTON, [joycon](wxCommandEvent&) { joycon->recenter_joycon_pointer(); });
	flags->Add(recenter, 0, wxRIGHT, 10);
	box->Add(flags, 0, wxLEFT | wxRIGHT | wxBOTTOM, 8);

	std::vector<uint32> recenter_hotkey = joycon->get_pointer_recenter_hotkey();
	bool capture_active = false;
	bool capture_wait_idle = false;
	bool capture_pressed = false;
	auto hotkey_text = [&]() {
		return _("Recenter shortcut: ") + joycon_hotkey_label(joycon, recenter_hotkey);
	};
	auto* hotkey = new wxButton(&dialog, wxID_ANY, hotkey_text());
	hotkey->SetToolTip(_("Click, release all buttons, then press and release one button or a combo. Right-click to clear."));
	box->Add(hotkey, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 8);
	outer->Add(box, 0, wxEXPAND | wxLEFT | wxRIGHT, 10);

	auto apply_preview_settings = [=](wxCommandEvent&) {
		joycon->set_pointer_calibration((float)yaw->GetValue(), (float)pitch->GetValue(),
			(float)deadzone->GetValue(), (float)smoothing->GetValue(), invert_x->GetValue(), invert_y->GetValue());
	};
	for (auto* spin : {yaw, pitch, deadzone, smoothing}) spin->Bind(wxEVT_SPINCTRLDOUBLE, apply_preview_settings);
	invert_x->Bind(wxEVT_CHECKBOX, apply_preview_settings);
	invert_y->Bind(wxEVT_CHECKBOX, apply_preview_settings);

	wxTimer refresh_timer(&dialog);
	dialog.Bind(wxEVT_TIMER, [&](wxTimerEvent&) {
		glm::vec2 live_position{}, live_previous{};
		joycon->update_joycon_pointer(live_position, live_previous);
		preview_valid = joycon->get_joycon_pointer_debug(sensor, accepted, output);
		preview->Refresh(false);
		if (!capture_active) return;
		const auto pressed = joycon->get_pressed_buttons_for_hotkey();
		if (capture_wait_idle)
		{
			if (pressed.empty())
			{
				capture_wait_idle = false;
				hotkey->SetLabel(_("Press recenter button(s), then release..."));
			}
			return;
		}
		if (!pressed.empty())
		{
			recenter_hotkey = pressed;
			capture_pressed = true;
			hotkey->SetLabel(_("Release to save recenter shortcut..."));
		}
		else if (capture_pressed)
		{
			capture_active = false;
			capture_pressed = false;
			hotkey->SetLabel(hotkey_text());
		}
	}, refresh_timer.GetId());
	hotkey->Bind(wxEVT_BUTTON, [&](wxCommandEvent&) {
		capture_active = true;
		capture_wait_idle = true;
		capture_pressed = false;
		recenter_hotkey.clear();
		hotkey->SetLabel(_("Release all controller buttons..."));
	});
	hotkey->Bind(wxEVT_RIGHT_UP, [&](wxMouseEvent&) {
		capture_active = false;
		capture_wait_idle = false;
		capture_pressed = false;
		recenter_hotkey.clear();
		hotkey->SetLabel(hotkey_text());
	});
	refresh_timer.Start(33);

	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Recommended start: Deadzone 0.35 degrees, Smooth 0.10. Recenter is manual; stillness calibration changes gyro bias only.")),
		0, wxEXPAND | wxALL, 10);
	outer->Add(dialog.CreateStdDialogButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
	dialog.SetSizerAndFit(outer);
	dialog.SetMinSize(wxSize(600, 650));

	if (dialog.ShowModal() == wxID_OK)
	{
		joycon->set_pointer_calibration((float)yaw->GetValue(), (float)pitch->GetValue(),
			(float)deadzone->GetValue(), (float)smoothing->GetValue(), invert_x->GetValue(), invert_y->GetValue());
		joycon->set_pointer_recenter_hotkey(std::move(recenter_hotkey));
	}
	else
	{
		joycon->set_pointer_calibration(original_yaw, original_pitch, original_deadzone,
			original_smoothing, original_invert_x, original_invert_y);
	}
}

void WiimoteInputPanel::on_joycon_motion_dialog(wxCommandEvent&)
{
	const auto joycon = m_active_joycon.lock();
	if (!joycon)
		return;

	wxDialog dialog(this, wxID_ANY, _("Motion Input - Dolphin Wii Remote"), wxDefaultPosition, wxDefaultSize,
		wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
	auto* outer = new wxBoxSizer(wxVERTICAL);
	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Live Dolphin Wii Remote axes. Put the Joy-Con down and keep it still for 3 seconds to update gyro bias.")),
		0, wxEXPAND | wxALL, 10);

	SDLControllerProvider::DolphinMotionDebug debug{};
	bool debug_valid = joycon->get_dolphin_motion_debug(debug);
	auto* visual = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(600, 230), wxBORDER_SIMPLE);
	visual->SetMinSize(wxSize(520, 190));
	visual->SetBackgroundStyle(wxBG_STYLE_PAINT);
	visual->Bind(wxEVT_PAINT, [&](wxPaintEvent&) {
		wxAutoBufferedPaintDC dc(visual);
		const wxSize size = visual->GetClientSize();
		dc.SetBackground(wxBrush(wxColour(24, 27, 32)));
		dc.Clear();
		dc.SetTextForeground(wxColour(225, 225, 225));
		if (!debug_valid)
		{
			dc.DrawText(_("Waiting for Joy-Con motion data..."), 12, 12);
			return;
		}
		const int cx = size.x / 4;
		const int cy = size.y / 2;
		const int radius = std::max(35, std::min(size.y / 2 - 25, size.x / 5));
		dc.SetPen(wxPen(wxColour(90, 96, 106), 1));
		dc.SetBrush(*wxTRANSPARENT_BRUSH);
		dc.DrawCircle(cx, cy, radius);
		dc.DrawLine(cx - radius, cy, cx + radius, cy);
		dc.DrawLine(cx, cy - radius, cx, cy + radius);
		const int ax = cx + (int)std::lround(std::clamp(debug.accel.x, -1.0f, 1.0f) * radius);
		const int ay = cy - (int)std::lround(std::clamp(debug.accel.z, -1.0f, 1.0f) * radius);
		dc.SetPen(wxPen(wxColour(70, 220, 120), 3));
		dc.DrawLine(cx, cy, ax, ay);
		dc.SetBrush(wxBrush(wxColour(70, 220, 120)));
		dc.DrawCircle(ax, ay, 6);
		dc.DrawText(_("Tilt / gravity"), cx - 45, cy + radius + 5);

		const int bar_x = size.x / 2 + 35;
		const int bar_w = std::max(80, size.x / 2 - 70);
		const wxColour colors[3] = {wxColour(255, 105, 105), wxColour(90, 170, 255), wxColour(255, 205, 65)};
		const wxString labels[3] = {_("X"), _("Y"), _("Z")};
		for (int i = 0; i < 3; ++i)
		{
			const int y = 45 + i * 48;
			const float value = std::clamp(debug.gyro[i] / 3.14159265f, -1.0f, 1.0f);
			dc.SetPen(wxPen(wxColour(85, 90, 100), 1));
			dc.DrawLine(bar_x, y, bar_x + bar_w, y);
			dc.DrawLine(bar_x + bar_w / 2, y - 8, bar_x + bar_w / 2, y + 8);
			dc.SetPen(wxPen(colors[i], 6));
			dc.DrawLine(bar_x + bar_w / 2, y, bar_x + bar_w / 2 + (int)std::lround(value * bar_w / 2), y);
			dc.SetTextForeground(colors[i]);
			dc.DrawText(labels[i], bar_x - 24, y - 9);
		}
		dc.SetTextForeground(wxColour(225, 225, 225));
		dc.DrawText(_("Gyroscope"), bar_x, 12);
	});
	outer->Add(visual, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* status = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
	auto* values = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
	outer->Add(status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);
	outer->Add(values, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* orientation_box = new wxStaticBoxSizer(wxHORIZONTAL, &dialog, _("Joy-Con / Wii Remote orientation"));
	orientation_box->Add(new wxStaticText(&dialog, wxID_ANY, _("Physical orientation:")), 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);
	auto* orientation = new wxChoice(&dialog, wxID_ANY);
	orientation->Append(_("Sideways"));
	orientation->Append(_("Vertical"));
	// Internal Vertical means physical Sideways in the preserved V5-V11 profile format.
	orientation->SetSelection(joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 0 : 1);
	orientation_box->Add(orientation, 0, wxRIGHT, 12);
	orientation_box->Add(new wxStaticText(&dialog, wxID_ANY,
		joycon->is_left_joycon() ? _("Joy-Con L Sideways: Dolphin -90 degree orientation") : _("Joy-Con R Sideways: proven Dolphin 180 degree fix")),
		1, wxALIGN_CENTER_VERTICAL);
	outer->Add(orientation_box, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	float sx, sy, sz;
	joycon->get_motion_scale(sx, sy, sz);
	auto* accel_box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Accelerometer / gyroscope axes"));
	auto* grid = new wxFlexGridSizer(4, 6, 10);
	grid->Add(new wxStaticText(&dialog, wxID_ANY, _("Axis")), 0);
	grid->Add(new wxStaticText(&dialog, wxID_ANY, _("Scale")), 0);
	grid->Add(new wxStaticText(&dialog, wxID_ANY, _("Invert")), 0);
	grid->Add(new wxStaticText(&dialog, wxID_ANY, _("Dolphin semantic direction")), 0);
	auto add_axis = [&](const wxString& name, float value, const wxString& direction, wxSpinCtrlDouble*& spin, wxCheckBox*& invert) {
		grid->Add(new wxStaticText(&dialog, wxID_ANY, name), 0, wxALIGN_CENTER_VERTICAL);
		spin = new wxSpinCtrlDouble(&dialog, wxID_ANY);
		spin->SetRange(0.25, 2.0);
		spin->SetIncrement(0.05);
		spin->SetDigits(2);
		spin->SetValue(std::abs(value));
		grid->Add(spin, 0, wxEXPAND);
		invert = new wxCheckBox(&dialog, wxID_ANY, wxEmptyString);
		invert->SetValue(value < 0.0f);
		grid->Add(invert, 0, wxALIGN_CENTER);
		grid->Add(new wxStaticText(&dialog, wxID_ANY, direction), 0, wxALIGN_CENTER_VERTICAL);
	};
	wxSpinCtrlDouble *spin_x{}, *spin_y{}, *spin_z{};
	wxCheckBox *inv_x{}, *inv_y{}, *inv_z{};
	add_axis(_("X"), sx, _("Left / Right"), spin_x, inv_x);
	add_axis(_("Y"), sy, _("Forward / Backward"), spin_y, inv_y);
	add_axis(_("Z"), sz, _("Up / Down"), spin_z, inv_z);
	accel_box->Add(grid, 0, wxEXPAND | wxALL, 8);
	outer->Add(accel_box, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* reset = new wxButton(&dialog, wxID_ANY, _("Reset motion scale"));
	reset->Bind(wxEVT_BUTTON, [=](wxCommandEvent&) {
		spin_x->SetValue(1.0); spin_y->SetValue(1.0); spin_z->SetValue(1.0);
		inv_x->SetValue(false); inv_y->SetValue(false); inv_z->SetValue(false);
	});
	outer->Add(reset, 0, wxLEFT | wxRIGHT | wxBOTTOM, 10);

	wxTimer refresh_timer(&dialog);
	dialog.Bind(wxEVT_TIMER, [&](wxTimerEvent&) {
		debug_valid = joycon->get_dolphin_motion_debug(debug);
		visual->Refresh(false);
		if (!debug_valid)
		{
			status->SetLabel(_("Calibration: waiting for sensor data"));
			values->SetLabel(wxEmptyString);
			return;
		}
		const int percent = (int)std::lround(debug.calibration_progress * 100.0f);
		if (debug.calibrated && debug.stable)
			status->SetLabel(wxString::Format(_("Calibration: READY / STILL | stable mean complete | %.0f Hz"), debug.sample_rate_hz));
		else if (debug.stable)
			status->SetLabel(wxString::Format(_("Calibration: KEEP STILL %d%% | %.0f Hz"), percent, debug.sample_rate_hz));
		else
			status->SetLabel(wxString::Format(_("Calibration: MOVING - 3 second timer restarted | %.0f Hz"), debug.sample_rate_hz));
		values->SetLabel(wxString::Format(_("Gyro: %+.3f %+.3f %+.3f rad/s | Acc: %+.3f %+.3f %+.3f g | Bias: %+.4f %+.4f %+.4f"),
			debug.gyro.x, debug.gyro.y, debug.gyro.z, debug.accel.x, debug.accel.y, debug.accel.z,
			debug.bias.x, debug.bias.y, debug.bias.z));
	}, refresh_timer.GetId());
	refresh_timer.Start(33);

	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Dolphin auto calibration: 3.0 s stable mean | Dead zone: 2 degrees/s | minimum stable sampling: 25 Hz. Auto calibration never recenters the pointer.")),
		0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);
	outer->Add(dialog.CreateStdDialogButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
	dialog.SetSizerAndFit(outer);
	dialog.SetMinSize(wxSize(700, 760));

	if (dialog.ShowModal() == wxID_OK)
	{
		// Preserve V5-V11 profile representation while presenting physical words correctly.
		joycon->set_joycon_orientation(orientation->GetSelection() == 0 ?
			SDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);
		auto signed_scale = [](wxSpinCtrlDouble* spin, wxCheckBox* invert) {
			const float value = (float)spin->GetValue();
			return invert->GetValue() ? -value : value;
		};
		joycon->set_motion_scale(signed_scale(spin_x, inv_x), signed_scale(spin_y, inv_y), signed_scale(spin_z, inv_z));
	}
}

'''
panel_cpp.write_text(text[:start] + new_dialogs + text[end:], encoding="utf-8")
print(f"Patched {panel_cpp}: replace V11 dialogs with V12 live visualizers and physical orientation fix")

print("Applied Cemu V12 Dolphin motion visualizer, stillness calibration status, pointer preview, and recenter hotkey")
