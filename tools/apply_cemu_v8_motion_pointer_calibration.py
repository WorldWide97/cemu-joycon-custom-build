from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v8_motion_pointer_calibration.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


def regex_replace_once(path: Path, pattern: str, repl: str, label: str):
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    path.write_text(new_text, encoding="utf-8")
    print(f"Patched {path}: {label}")


# -----------------------------------------------------------------------------
# 1) Normalize the actual SDL Joy-Con sensor coordinate systems.
#
# SDL 3 mini-gamepad mode (which Cemu deliberately keeps enabled) publishes:
#   L mini: ( z, y, -x ) relative to SDL's vertical Joy-Con basis
#   R mini: (-z, y,  x ) relative to SDL's vertical Joy-Con basis
# Therefore R Sideways differs from L Sideways by X/Z signs. Normalizing those
# two signs is the software equivalent of the physical 180-degree flip reported
# during hardware testing. Vertical recovery remains V6's exact inverse of SDL.
# -----------------------------------------------------------------------------
provider_h = root / "src/input/api/SDL/SDLControllerProvider.h"
replace_once(
    provider_h,
    '''\tvoid set_joycon_orientation(SDL_JoystickID diid, bool is_left, bool vertical);\n\tvoid clear_joycon_orientation(SDL_JoystickID diid);\n''',
    '''\tvoid set_joycon_orientation(SDL_JoystickID diid, bool is_left, bool vertical);\n\tvoid set_joycon_motion_scale(SDL_JoystickID diid, float x, float y, float z);\n\tvoid clear_joycon_orientation(SDL_JoystickID diid);\n''',
    "provider motion calibration method",
)
replace_once(
    provider_h,
    '''\t\tbool is_left{};\n\t\tbool vertical{};\n\t};\n''',
    '''\t\tbool is_left{};\n\t\tbool vertical{};\n\t\tfloat motion_scale_x{ 1.0f };\n\t\tfloat motion_scale_y{ 1.0f };\n\t\tfloat motion_scale_z{ 1.0f };\n\t};\n''',
    "provider per-device motion scale state",
)

provider_cpp = root / "src/input/api/SDL/SDLControllerProvider.cpp"
replace_once(
    provider_cpp,
    '''void SDLControllerProvider::clear_joycon_orientation(SDL_JoystickID diid)\n{\n\tif (diid < 0)\n\t\treturn;\n\n\tstd::scoped_lock lock(s_mutex);\n\ts_joycon_orientation_states.erase(diid);\n\ts_motion_states.erase(diid);\n}\n''',
    '''void SDLControllerProvider::set_joycon_motion_scale(SDL_JoystickID diid, float x, float y, float z)\n{\n\tif (diid < 0)\n\t\treturn;\n\n\tstd::scoped_lock lock(s_mutex);\n\tauto& state = s_joycon_orientation_states[diid];\n\tif (state.motion_scale_x != x || state.motion_scale_y != y || state.motion_scale_z != z)\n\t{\n\t\tstate.motion_scale_x = x;\n\t\tstate.motion_scale_y = y;\n\t\tstate.motion_scale_z = z;\n\t\t// A basis/calibration change must restart Mahony integration.\n\t\ts_motion_states.erase(diid);\n\t}\n}\n\nvoid SDLControllerProvider::clear_joycon_orientation(SDL_JoystickID diid)\n{\n\tif (diid < 0)\n\t\treturn;\n\n\tstd::scoped_lock lock(s_mutex);\n\ts_joycon_orientation_states.erase(diid);\n\ts_motion_states.erase(diid);\n}\n''',
    "provider motion calibration implementation",
)
replace_once(
    provider_cpp,
    '''\n\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)\n''',
    '''\n\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\tconfig != s_joycon_orientation_states.end())\n\t\t\t{\n\t\t\t\t// SDL's standalone R mini-gamepad basis is the L basis with X/Z\n\t\t\t\t// reversed. Normalize R Sideways so identical physical movement\n\t\t\t\t// produces identical Wii Remote motion on both Joy-Cons.\n\t\t\t\tif (!config->second.vertical && !config->second.is_left)\n\t\t\t\t{\n\t\t\t\t\tsensor_data[0] = -sensor_data[0];\n\t\t\t\t\tsensor_data[2] = -sensor_data[2];\n\t\t\t\t}\n\n\t\t\t\tsensor_data[0] *= config->second.motion_scale_x;\n\t\t\t\tsensor_data[1] *= config->second.motion_scale_y;\n\t\t\t\tsensor_data[2] *= config->second.motion_scale_z;\n\t\t\t}\n\n\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)\n''',
    "normalize R Sideways and apply per-device motion calibration",
)


# -----------------------------------------------------------------------------
# 2) Put the pointer calibration and runtime engine on SDLController itself.
# This makes the same per-device engine available both to WPAD and to the live UI.
# The pointer uses the Mahony attitude matrix as a 3D pointing ray:
#   local Y = forward/top of controller, local X = right, local Z = up/face normal.
# Recenter stores a screen basis from the current pose. Projecting the current
# forward ray onto that fixed basis makes cursor aiming independent of controller
# roll and independent of whether the controller is flat on a table.
# -----------------------------------------------------------------------------
controller_h = root / "src/input/api/SDL/SDLController.h"
replace_once(
    controller_h,
    '''\tbool is_pointer_enabled() const { return m_pointer_enabled.load(std::memory_order_relaxed); }\n\tvoid set_pointer_enabled(bool enabled, bool notify = true);\n''',
    '''\tbool is_pointer_enabled() const { return m_pointer_enabled.load(std::memory_order_relaxed); }\n\tvoid set_pointer_enabled(bool enabled, bool notify = true);\n\tvoid recenter_joycon_pointer(bool notify = true);\n\tbool update_joycon_pointer(glm::vec2& position, glm::vec2& previous);\n\n\tfloat get_pointer_yaw_degrees() const { return m_pointer_yaw_degrees.load(std::memory_order_relaxed); }\n\tfloat get_pointer_pitch_degrees() const { return m_pointer_pitch_degrees.load(std::memory_order_relaxed); }\n\tfloat get_pointer_deadzone_degrees() const { return m_pointer_deadzone_degrees.load(std::memory_order_relaxed); }\n\tfloat get_pointer_smoothing() const { return m_pointer_smoothing.load(std::memory_order_relaxed); }\n\tbool get_pointer_invert_x() const { return m_pointer_invert_x.load(std::memory_order_relaxed); }\n\tbool get_pointer_invert_y() const { return m_pointer_invert_y.load(std::memory_order_relaxed); }\n\tvoid set_pointer_calibration(float yaw_degrees, float pitch_degrees, float deadzone_degrees, float smoothing, bool invert_x, bool invert_y);\n\n\tvoid get_motion_scale(float& x, float& y, float& z) const;\n\tvoid set_motion_scale(float x, float y, float z);\n''',
    "pointer/motion calibration public API",
)
replace_once(
    controller_h,
    '''\tstd::atomic_bool m_pointer_enabled{ true };\n\tbool m_vertical_hotkey_latched = false;\n''',
    '''\tstd::atomic_bool m_pointer_enabled{ true };\n\tstd::atomic<float> m_pointer_yaw_degrees{ 25.0f };\n\tstd::atomic<float> m_pointer_pitch_degrees{ 20.0f };\n\tstd::atomic<float> m_pointer_deadzone_degrees{ 0.15f };\n\tstd::atomic<float> m_pointer_smoothing{ 0.08f };\n\tstd::atomic_bool m_pointer_invert_x{ false };\n\tstd::atomic_bool m_pointer_invert_y{ false };\n\n\tstd::atomic<float> m_motion_scale_x{ 1.0f };\n\tstd::atomic<float> m_motion_scale_y{ 1.0f };\n\tstd::atomic<float> m_motion_scale_z{ 1.0f };\n\n\tmutable std::mutex m_joycon_pointer_mutex;\n\tbool m_joycon_pointer_initialized = false;\n\tstd::array<float, 9> m_joycon_pointer_reference_attitude{};\n\tglm::vec2 m_joycon_pointer_position{ 0.5f, 0.5f };\n\tglm::vec2 m_joycon_pointer_previous{ 0.5f, 0.5f };\n\n\tbool m_vertical_hotkey_latched = false;\n''',
    "pointer/motion calibration state",
)

controller_cpp = root / "src/input/api/SDL/SDLController.cpp"
# Ensure math helpers are explicitly available here.
replace_once(
    controller_cpp,
    '''#include <sstream>\n''',
    '''#include <sstream>\n#include <cmath>\n''',
    "controller pointer math include",
)

# Enabling pointer is also a deterministic recenter operation.
replace_once(
    controller_cpp,
    '''\tconst bool previous = m_pointer_enabled.exchange(enabled, std::memory_order_relaxed);\n\tif (notify && previous != enabled)\n''',
    '''\tconst bool previous = m_pointer_enabled.exchange(enabled, std::memory_order_relaxed);\n\tif (enabled && previous != enabled)\n\t\trecenter_joycon_pointer(false);\n\tif (notify && previous != enabled)\n''',
    "recenter pointer when enabled",
)

# Add calibration/3D pointer implementation immediately after pointer enable.
replace_once(
    controller_cpp,
    '''void SDLController::set_pointer_enabled(bool enabled, bool notify)\n{\n\tif (!is_joycon())\n\t\treturn;\n\n\tconst bool previous = m_pointer_enabled.exchange(enabled, std::memory_order_relaxed);\n\tif (enabled && previous != enabled)\n\t\trecenter_joycon_pointer(false);\n\tif (notify && previous != enabled)\n\t{\n\t\tconst char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";\n\t\tLatteOverlay_pushNotification(fmt::format("{} Pointer {}", side, enabled ? "ON" : "OFF"), 2200);\n\t}\n}\n''',
    '''void SDLController::set_pointer_enabled(bool enabled, bool notify)\n{\n\tif (!is_joycon())\n\t\treturn;\n\n\tconst bool previous = m_pointer_enabled.exchange(enabled, std::memory_order_relaxed);\n\tif (enabled && previous != enabled)\n\t\trecenter_joycon_pointer(false);\n\tif (notify && previous != enabled)\n\t{\n\t\tconst char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";\n\t\tLatteOverlay_pushNotification(fmt::format("{} Pointer {}", side, enabled ? "ON" : "OFF"), 2200);\n\t}\n}\n\nvoid SDLController::set_pointer_calibration(float yaw_degrees, float pitch_degrees, float deadzone_degrees, float smoothing, bool invert_x, bool invert_y)\n{\n\tyaw_degrees = std::clamp(yaw_degrees, 5.0f, 120.0f);\n\tpitch_degrees = std::clamp(pitch_degrees, 5.0f, 120.0f);\n\tdeadzone_degrees = std::clamp(deadzone_degrees, 0.0f, 5.0f);\n\tsmoothing = std::clamp(smoothing, 0.0f, 0.95f);\n\n\tm_pointer_yaw_degrees.store(yaw_degrees, std::memory_order_relaxed);\n\tm_pointer_pitch_degrees.store(pitch_degrees, std::memory_order_relaxed);\n\tm_pointer_deadzone_degrees.store(deadzone_degrees, std::memory_order_relaxed);\n\tm_pointer_smoothing.store(smoothing, std::memory_order_relaxed);\n\tm_pointer_invert_x.store(invert_x, std::memory_order_relaxed);\n\tm_pointer_invert_y.store(invert_y, std::memory_order_relaxed);\n}\n\nvoid SDLController::get_motion_scale(float& x, float& y, float& z) const\n{\n\tx = m_motion_scale_x.load(std::memory_order_relaxed);\n\ty = m_motion_scale_y.load(std::memory_order_relaxed);\n\tz = m_motion_scale_z.load(std::memory_order_relaxed);\n}\n\nvoid SDLController::set_motion_scale(float x, float y, float z)\n{\n\tauto clamp_scale = [](float value) {\n\t\tconst float sign = value < 0.0f ? -1.0f : 1.0f;\n\t\treturn sign * std::clamp(std::abs(value), 0.25f, 2.0f);\n\t};\n\tx = clamp_scale(x);\n\ty = clamp_scale(y);\n\tz = clamp_scale(z);\n\tm_motion_scale_x.store(x, std::memory_order_relaxed);\n\tm_motion_scale_y.store(y, std::memory_order_relaxed);\n\tm_motion_scale_z.store(z, std::memory_order_relaxed);\n\tif (m_diid >= 0)\n\t\tm_provider->set_joycon_motion_scale(m_diid, x, y, z);\n\trecenter_joycon_pointer(false);\n}\n\nvoid SDLController::recenter_joycon_pointer(bool notify)\n{\n\t{\n\t\tstd::scoped_lock lock(m_joycon_pointer_mutex);\n\t\tm_joycon_pointer_initialized = false;\n\t\tm_joycon_pointer_position = { 0.5f, 0.5f };\n\t\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\t}\n\tif (notify && is_joycon())\n\t{\n\t\tconst char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";\n\t\tLatteOverlay_pushNotification(fmt::format("{} Pointer centered", side), 1800);\n\t}\n}\n\nbool SDLController::update_joycon_pointer(glm::vec2& position, glm::vec2& previous)\n{\n\tif (!is_joycon() || !is_pointer_enabled() || !is_connected() || !has_motion())\n\t\treturn false;\n\n\tauto sample = get_motion_sample();\n\tfloat attitude[9]{};\n\tsample.getVPADAttitudeMatrix(attitude);\n\tfor (const float value : attitude)\n\t{\n\t\tif (!std::isfinite(value))\n\t\t\treturn false;\n\t}\n\n\tstd::scoped_lock lock(m_joycon_pointer_mutex);\n\tif (!m_joycon_pointer_initialized)\n\t{\n\t\tstd::copy(std::begin(attitude), std::end(attitude), m_joycon_pointer_reference_attitude.begin());\n\t\tm_joycon_pointer_position = { 0.5f, 0.5f };\n\t\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\t\tm_joycon_pointer_initialized = true;\n\t\tposition = m_joycon_pointer_position;\n\t\tprevious = m_joycon_pointer_previous;\n\t\treturn true;\n\t}\n\n\tauto dot3 = [](const float* a, const float* b) {\n\t\treturn a[0] * b[0] + a[1] * b[1] + a[2] * b[2];\n\t};\n\t// MotionSample attitude rows are local X(right), Y(forward/top), Z(up/face).\n\tconst float* current_forward = attitude + 3;\n\tconst float* reference_right = m_joycon_pointer_reference_attitude.data() + 0;\n\tconst float* reference_forward = m_joycon_pointer_reference_attitude.data() + 3;\n\tconst float* reference_up = m_joycon_pointer_reference_attitude.data() + 6;\n\n\tconst float forward_component = dot3(current_forward, reference_forward);\n\tfloat horizontal_angle = std::atan2(dot3(current_forward, reference_right), forward_component);\n\tfloat vertical_angle = std::atan2(dot3(current_forward, reference_up), forward_component);\n\n\tconstexpr float kPi = 3.14159265358979323846f;\n\tconst float deadzone = get_pointer_deadzone_degrees() * kPi / 180.0f;\n\tauto apply_deadzone = [deadzone](float angle) {\n\t\tconst float magnitude = std::abs(angle);\n\t\tif (magnitude <= deadzone)\n\t\t\treturn 0.0f;\n\t\treturn std::copysign(magnitude - deadzone, angle);\n\t};\n\thorizontal_angle = apply_deadzone(horizontal_angle);\n\tvertical_angle = apply_deadzone(vertical_angle);\n\n\t// Match the established Cemu/SDL gyro sign used by V7, but expose explicit\n\t// inversion switches so each physical Joy-Con can be corrected without rebuilds.\n\tfloat screen_horizontal = -horizontal_angle;\n\tfloat screen_vertical = -vertical_angle;\n\tif (get_pointer_invert_x()) screen_horizontal = -screen_horizontal;\n\tif (get_pointer_invert_y()) screen_vertical = -screen_vertical;\n\n\tconst float total_yaw = get_pointer_yaw_degrees() * kPi / 180.0f;\n\tconst float total_pitch = get_pointer_pitch_degrees() * kPi / 180.0f;\n\tconst glm::vec2 target{\n\t\tstd::clamp(0.5f + screen_horizontal / total_yaw, 0.0f, 1.0f),\n\t\tstd::clamp(0.5f + screen_vertical / total_pitch, 0.0f, 1.0f)\n\t};\n\n\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\tconst float follow = 1.0f - get_pointer_smoothing();\n\tm_joycon_pointer_position += (target - m_joycon_pointer_position) * follow;\n\tposition = m_joycon_pointer_position;\n\tprevious = m_joycon_pointer_previous;\n\treturn true;\n}\n''',
    "Dolphin-style 3D ray pointer and calibration engine",
)

# Recenter when orientation changes so the current aiming pose becomes neutral.
replace_once(
    controller_cpp,
    '''\tm_joycon_orientation.store(orientation, std::memory_order_relaxed);\n''',
    '''\tm_joycon_orientation.store(orientation, std::memory_order_relaxed);\n\trecenter_joycon_pointer(false);\n''',
    "recenter pointer on orientation change",
)

# Restore per-device motion calibration on connect.
replace_once(
    controller_cpp,
    '''\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), physical_vertical);\n\t}\n\treturn true;\n''',
    '''\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), physical_vertical);\n\t\tm_provider->set_joycon_motion_scale(m_diid,\n\t\t\tm_motion_scale_x.load(std::memory_order_relaxed),\n\t\t\tm_motion_scale_y.load(std::memory_order_relaxed),\n\t\t\tm_motion_scale_z.load(std::memory_order_relaxed));\n\t}\n\treturn true;\n''',
    "restore motion calibration on connect",
)

# Persist calibration in the controller profile.
replace_once(
    controller_cpp,
    '''\tnode.append_child("joycon_pointer_enabled").append_child(pugi::node_pcdata).set_value(is_pointer_enabled() ? "1" : "0");\n''',
    '''\tnode.append_child("joycon_pointer_enabled").append_child(pugi::node_pcdata).set_value(is_pointer_enabled() ? "1" : "0");\n\tnode.append_child("joycon_pointer_yaw_deg").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_yaw_degrees()).c_str());\n\tnode.append_child("joycon_pointer_pitch_deg").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_pitch_degrees()).c_str());\n\tnode.append_child("joycon_pointer_deadzone_deg").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_deadzone_degrees()).c_str());\n\tnode.append_child("joycon_pointer_smoothing").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_smoothing()).c_str());\n\tnode.append_child("joycon_pointer_invert_x").append_child(pugi::node_pcdata).set_value(get_pointer_invert_x() ? "1" : "0");\n\tnode.append_child("joycon_pointer_invert_y").append_child(pugi::node_pcdata).set_value(get_pointer_invert_y() ? "1" : "0");\n\tfloat motion_x, motion_y, motion_z;\n\tget_motion_scale(motion_x, motion_y, motion_z);\n\tnode.append_child("joycon_motion_scale_x").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", motion_x).c_str());\n\tnode.append_child("joycon_motion_scale_y").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", motion_y).c_str());\n\tnode.append_child("joycon_motion_scale_z").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", motion_z).c_str());\n''',
    "save V8 pointer and motion calibration",
)
replace_once(
    controller_cpp,
    '''\tset_pointer_enabled(pointer_enabled, false);\n\tJoyConOrientation orientation = JoyConOrientation::Sideways;\n''',
    '''\tset_pointer_enabled(pointer_enabled, false);\n\tfloat pointer_yaw = 25.0f;\n\tfloat pointer_pitch = 20.0f;\n\tfloat pointer_deadzone = 0.15f;\n\tfloat pointer_smoothing = 0.08f;\n\tbool pointer_invert_x = false;\n\tbool pointer_invert_y = false;\n\tif (const auto value = node.child("joycon_pointer_yaw_deg")) pointer_yaw = ConvertString<float>(value.child_value());\n\tif (const auto value = node.child("joycon_pointer_pitch_deg")) pointer_pitch = ConvertString<float>(value.child_value());\n\tif (const auto value = node.child("joycon_pointer_deadzone_deg")) pointer_deadzone = ConvertString<float>(value.child_value());\n\tif (const auto value = node.child("joycon_pointer_smoothing")) pointer_smoothing = ConvertString<float>(value.child_value());\n\tif (const auto value = node.child("joycon_pointer_invert_x")) pointer_invert_x = ConvertString<int>(value.child_value()) != 0;\n\tif (const auto value = node.child("joycon_pointer_invert_y")) pointer_invert_y = ConvertString<int>(value.child_value()) != 0;\n\tset_pointer_calibration(pointer_yaw, pointer_pitch, pointer_deadzone, pointer_smoothing, pointer_invert_x, pointer_invert_y);\n\tfloat motion_x = 1.0f, motion_y = 1.0f, motion_z = 1.0f;\n\tif (const auto value = node.child("joycon_motion_scale_x")) motion_x = ConvertString<float>(value.child_value());\n\tif (const auto value = node.child("joycon_motion_scale_y")) motion_y = ConvertString<float>(value.child_value());\n\tif (const auto value = node.child("joycon_motion_scale_z")) motion_z = ConvertString<float>(value.child_value());\n\tset_motion_scale(motion_x, motion_y, motion_z);\n\tJoyConOrientation orientation = JoyConOrientation::Sideways;\n''',
    "load V8 pointer and motion calibration",
)


# -----------------------------------------------------------------------------
# 3) WPAD uses the per-Joy-Con 3D engine. This leaves KPAD and raw WPAD DPD paths
# intact while replacing V7's rate integration with the shared calibrated result.
# -----------------------------------------------------------------------------
wpad_cpp = root / "src/input/emulated/WPADController.cpp"
pattern = r'''bool WPADController::update_joycon_pointer\(glm::vec2& position, glm::vec2& previous\)\n\{.*?\n\}\n\nWPADDataFormat WPADController::get_default_data_format'''
replacement = r'''bool WPADController::update_joycon_pointer(glm::vec2& position, glm::vec2& previous)
{
	std::shared_ptr<SDLController> joycon;
	{
		std::shared_lock lock(m_mutex);
		for (const auto& controller : m_controllers)
		{
			auto candidate = std::dynamic_pointer_cast<SDLController>(controller);
			if (candidate && candidate->is_joycon() && candidate->use_motion())
			{
				joycon = std::move(candidate);
				break;
			}
		}
	}

	return joycon && joycon->update_joycon_pointer(position, previous);
}

WPADDataFormat WPADController::get_default_data_format'''
regex_replace_once(wpad_cpp, pattern, replacement, "delegate WPAD pointer to calibrated per-Joy-Con 3D engine")


# -----------------------------------------------------------------------------
# 4) Dolphin-like calibration controls and live preview in Wii Remote Input.
# -----------------------------------------------------------------------------
panel_h = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.h"
replace_once(
    panel_h,
    '''class wxStaticText;\nclass SDLController;\n''',
    '''class wxStaticText;\nclass wxSpinCtrlDouble;\nclass SDLController;\n''',
    "V8 UI forward declarations",
)
replace_once(
    panel_h,
    '''\twxCheckBox* m_joycon_pointer_enabled = nullptr;\n\twxButton* m_joycon_pointer_hotkey = nullptr;\n\twxStaticText* m_joycon_status = nullptr;\n''',
    '''\twxCheckBox* m_joycon_pointer_enabled = nullptr;\n\twxButton* m_joycon_pointer_hotkey = nullptr;\n\twxButton* m_joycon_pointer_recenter = nullptr;\n\twxPanel* m_joycon_pointer_preview = nullptr;\n\twxSpinCtrlDouble* m_joycon_pointer_yaw = nullptr;\n\twxSpinCtrlDouble* m_joycon_pointer_pitch = nullptr;\n\twxSpinCtrlDouble* m_joycon_pointer_deadzone = nullptr;\n\twxSpinCtrlDouble* m_joycon_pointer_smoothing = nullptr;\n\twxCheckBox* m_joycon_pointer_invert_x = nullptr;\n\twxCheckBox* m_joycon_pointer_invert_y = nullptr;\n\twxSpinCtrlDouble* m_joycon_motion_x = nullptr;\n\twxSpinCtrlDouble* m_joycon_motion_y = nullptr;\n\twxSpinCtrlDouble* m_joycon_motion_z = nullptr;\n\twxCheckBox* m_joycon_motion_invert_x = nullptr;\n\twxCheckBox* m_joycon_motion_invert_y = nullptr;\n\twxCheckBox* m_joycon_motion_invert_z = nullptr;\n\twxButton* m_joycon_motion_reset = nullptr;\n\twxStaticText* m_joycon_motion_live = nullptr;\n\twxStaticText* m_joycon_status = nullptr;\n\tfloat m_joycon_preview_x = 0.5f;\n\tfloat m_joycon_preview_y = 0.5f;\n\tbool m_joycon_preview_valid = false;\n''',
    "V8 calibration UI members",
)
replace_once(
    panel_h,
    '''\tvoid on_joycon_pointer_enable(wxCommandEvent& event);\n\tvoid on_joycon_hotkey_click(wxCommandEvent& event);\n''',
    '''\tvoid on_joycon_pointer_enable(wxCommandEvent& event);\n\tvoid on_joycon_pointer_recenter(wxCommandEvent& event);\n\tvoid on_joycon_pointer_settings(wxCommandEvent& event);\n\tvoid on_joycon_motion_settings(wxCommandEvent& event);\n\tvoid on_joycon_motion_reset(wxCommandEvent& event);\n\tvoid on_joycon_pointer_paint(wxPaintEvent& event);\n\tvoid on_joycon_hotkey_click(wxCommandEvent& event);\n''',
    "V8 calibration UI handlers",
)

panel_cpp = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"
replace_once(
    panel_cpp,
    '''#include <wx/choice.h>\n''',
    '''#include <wx/choice.h>\n#include <wx/spinctrl.h>\n#include <wx/dcbuffer.h>\n''',
    "V8 wx calibration includes",
)

# Wrap the existing V7 top row in a vertical outer sizer and add two calibration rows.
replace_once(
    panel_cpp,
    '''\tm_joycon_panel->SetSizer(joycon_sizer);\n\tm_joycon_panel->Hide();\n''',
    '''\tauto* joycon_outer = new wxBoxSizer(wxVERTICAL);\n\tjoycon_outer->Add(joycon_sizer, 0, wxEXPAND | wxBOTTOM, 5);\n\n\tauto* pointer_sizer = new wxBoxSizer(wxHORIZONTAL);\n\tm_joycon_pointer_preview = new wxPanel(m_joycon_panel, wxID_ANY, wxDefaultPosition, wxSize(180, 95), wxBORDER_SIMPLE);\n\tm_joycon_pointer_preview->SetMinSize(wxSize(180, 95));\n\tm_joycon_pointer_preview->SetBackgroundStyle(wxBG_STYLE_PAINT);\n\tm_joycon_pointer_preview->Bind(wxEVT_PAINT, &WiimoteInputPanel::on_joycon_pointer_paint, this);\n\tpointer_sizer->Add(m_joycon_pointer_preview, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);\n\tm_joycon_pointer_recenter = new wxButton(m_joycon_panel, wxID_ANY, _("Recenter pointer"));\n\tm_joycon_pointer_recenter->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_pointer_recenter, this);\n\tpointer_sizer->Add(m_joycon_pointer_recenter, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);\n\n\tauto make_spin = [this, pointer_sizer](const wxString& label, double value, double min_value, double max_value, double increment, int digits) {\n\t\tpointer_sizer->Add(new wxStaticText(m_joycon_panel, wxID_ANY, label), 0, wxLEFT | wxRIGHT | wxALIGN_CENTER_VERTICAL, 3);\n\t\tauto* spin = new wxSpinCtrlDouble(m_joycon_panel, wxID_ANY);\n\t\tspin->SetRange(min_value, max_value);\n\t\tspin->SetIncrement(increment);\n\t\tspin->SetDigits(digits);\n\t\tspin->SetValue(value);\n\t\tspin->SetMinSize(wxSize(72, -1));\n\t\tspin->Bind(wxEVT_TEXT, &WiimoteInputPanel::on_joycon_pointer_settings, this);\n\t\tpointer_sizer->Add(spin, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);\n\t\treturn spin;\n\t};\n\tm_joycon_pointer_yaw = make_spin(_("Yaw °"), 25.0, 5.0, 120.0, 1.0, 1);\n\tm_joycon_pointer_pitch = make_spin(_("Pitch °"), 20.0, 5.0, 120.0, 1.0, 1);\n\tm_joycon_pointer_deadzone = make_spin(_("Deadzone °"), 0.15, 0.0, 5.0, 0.05, 2);\n\tm_joycon_pointer_smoothing = make_spin(_("Smooth"), 0.08, 0.0, 0.95, 0.01, 2);\n\tm_joycon_pointer_invert_x = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert X"));\n\tm_joycon_pointer_invert_y = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert Y"));\n\tm_joycon_pointer_invert_x->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_joycon_pointer_settings, this);\n\tm_joycon_pointer_invert_y->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_joycon_pointer_settings, this);\n\tpointer_sizer->Add(m_joycon_pointer_invert_x, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);\n\tpointer_sizer->Add(m_joycon_pointer_invert_y, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 5);\n\tjoycon_outer->Add(pointer_sizer, 0, wxEXPAND | wxBOTTOM, 5);\n\n\tauto* motion_sizer = new wxBoxSizer(wxHORIZONTAL);\n\tmotion_sizer->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Motion calibration:")), 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 6);\n\tauto make_motion_spin = [this, motion_sizer](const wxString& label) {\n\t\tmotion_sizer->Add(new wxStaticText(m_joycon_panel, wxID_ANY, label), 0, wxLEFT | wxRIGHT | wxALIGN_CENTER_VERTICAL, 3);\n\t\tauto* spin = new wxSpinCtrlDouble(m_joycon_panel, wxID_ANY);\n\t\tspin->SetRange(0.25, 2.0);\n\t\tspin->SetIncrement(0.05);\n\t\tspin->SetDigits(2);\n\t\tspin->SetValue(1.0);\n\t\tspin->SetMinSize(wxSize(70, -1));\n\t\tspin->Bind(wxEVT_TEXT, &WiimoteInputPanel::on_joycon_motion_settings, this);\n\t\tmotion_sizer->Add(spin, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 4);\n\t\treturn spin;\n\t};\n\tm_joycon_motion_x = make_motion_spin(_("X"));\n\tm_joycon_motion_y = make_motion_spin(_("Y"));\n\tm_joycon_motion_z = make_motion_spin(_("Z"));\n\tm_joycon_motion_invert_x = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert X"));\n\tm_joycon_motion_invert_y = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert Y"));\n\tm_joycon_motion_invert_z = new wxCheckBox(m_joycon_panel, wxID_ANY, _("Invert Z"));\n\tfor (auto* checkbox : { m_joycon_motion_invert_x, m_joycon_motion_invert_y, m_joycon_motion_invert_z })\n\t\tcheckbox->Bind(wxEVT_CHECKBOX, &WiimoteInputPanel::on_joycon_motion_settings, this);\n\tmotion_sizer->Add(m_joycon_motion_invert_x, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 4);\n\tmotion_sizer->Add(m_joycon_motion_invert_y, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 4);\n\tmotion_sizer->Add(m_joycon_motion_invert_z, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);\n\tm_joycon_motion_reset = new wxButton(m_joycon_panel, wxID_ANY, _("Reset motion"));\n\tm_joycon_motion_reset->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_motion_reset, this);\n\tmotion_sizer->Add(m_joycon_motion_reset, 0, wxRIGHT | wxALIGN_CENTER_VERTICAL, 8);\n\tm_joycon_motion_live = new wxStaticText(m_joycon_panel, wxID_ANY, _("Gyro 0 0 0 | Acc 0 0 0 | Pointer 50% 50%"));\n\tmotion_sizer->Add(m_joycon_motion_live, 1, wxALIGN_CENTER_VERTICAL);\n\tjoycon_outer->Add(motion_sizer, 0, wxEXPAND);\n\n\tm_joycon_panel->SetSizer(joycon_outer);\n\tm_joycon_panel->Hide();\n''',
    "add Dolphin-style pointer/motion calibration rows",
)

# Refresh values and live preview from the selected physical Joy-Con.
replace_once(
    panel_cpp,
    '''\tif (m_joycon_capture != JoyConHotkeyCapture::Pointer)\n\t\tm_joycon_pointer_hotkey->SetLabel(_("Pointer hotkey: ") + joycon_hotkey_label(joycon, joycon->get_pointer_hotkey()));\n}\n''',
    '''\tif (m_joycon_capture != JoyConHotkeyCapture::Pointer)\n\t\tm_joycon_pointer_hotkey->SetLabel(_("Pointer hotkey: ") + joycon_hotkey_label(joycon, joycon->get_pointer_hotkey()));\n\tm_joycon_pointer_yaw->SetValue(joycon->get_pointer_yaw_degrees());\n\tm_joycon_pointer_pitch->SetValue(joycon->get_pointer_pitch_degrees());\n\tm_joycon_pointer_deadzone->SetValue(joycon->get_pointer_deadzone_degrees());\n\tm_joycon_pointer_smoothing->SetValue(joycon->get_pointer_smoothing());\n\tm_joycon_pointer_invert_x->SetValue(joycon->get_pointer_invert_x());\n\tm_joycon_pointer_invert_y->SetValue(joycon->get_pointer_invert_y());\n\tfloat motion_x, motion_y, motion_z;\n\tjoycon->get_motion_scale(motion_x, motion_y, motion_z);\n\tm_joycon_motion_x->SetValue(std::abs(motion_x));\n\tm_joycon_motion_y->SetValue(std::abs(motion_y));\n\tm_joycon_motion_z->SetValue(std::abs(motion_z));\n\tm_joycon_motion_invert_x->SetValue(motion_x < 0.0f);\n\tm_joycon_motion_invert_y->SetValue(motion_y < 0.0f);\n\tm_joycon_motion_invert_z->SetValue(motion_z < 0.0f);\n\n\tglm::vec2 pointer{}, previous{};\n\tm_joycon_preview_valid = joycon->update_joycon_pointer(pointer, previous);\n\tif (m_joycon_preview_valid)\n\t{\n\t\tm_joycon_preview_x = pointer.x;\n\t\tm_joycon_preview_y = pointer.y;\n\t}\n\tif (m_joycon_pointer_preview) m_joycon_pointer_preview->Refresh(false);\n\tauto motion = joycon->get_motion_sample();\n\tfloat gyro[3]{}, acc[3]{};\n\tmotion.getGyrometer(gyro);\n\tmotion.getAccelerometer(acc);\n\tm_joycon_motion_live->SetLabel(wxString::Format(_("Gyro %.2f %.2f %.2f | Acc %.2f %.2f %.2f | Pointer %.0f%% %.0f%%"),\n\t\tgyro[0], gyro[1], gyro[2], acc[0], acc[1], acc[2], m_joycon_preview_x * 100.0f, m_joycon_preview_y * 100.0f));\n}\n''',
    "refresh V8 calibration and live motion preview",
)

# Handlers are inserted before the V7 pointer checkbox handler.
replace_once(
    panel_cpp,
    '''void WiimoteInputPanel::on_joycon_pointer_enable(wxCommandEvent&)\n''',
    '''void WiimoteInputPanel::on_joycon_pointer_recenter(wxCommandEvent&)\n{\n\tif (const auto joycon = m_active_joycon.lock())\n\t\tjoycon->recenter_joycon_pointer();\n}\n\nvoid WiimoteInputPanel::on_joycon_pointer_settings(wxCommandEvent&)\n{\n\tif (const auto joycon = m_active_joycon.lock())\n\t{\n\t\tjoycon->set_pointer_calibration(\n\t\t\t(float)m_joycon_pointer_yaw->GetValue(),\n\t\t\t(float)m_joycon_pointer_pitch->GetValue(),\n\t\t\t(float)m_joycon_pointer_deadzone->GetValue(),\n\t\t\t(float)m_joycon_pointer_smoothing->GetValue(),\n\t\t\tm_joycon_pointer_invert_x->GetValue(),\n\t\t\tm_joycon_pointer_invert_y->GetValue());\n\t}\n}\n\nvoid WiimoteInputPanel::on_joycon_motion_settings(wxCommandEvent&)\n{\n\tif (const auto joycon = m_active_joycon.lock())\n\t{\n\t\tconst float x = (float)m_joycon_motion_x->GetValue() * (m_joycon_motion_invert_x->GetValue() ? -1.0f : 1.0f);\n\t\tconst float y = (float)m_joycon_motion_y->GetValue() * (m_joycon_motion_invert_y->GetValue() ? -1.0f : 1.0f);\n\t\tconst float z = (float)m_joycon_motion_z->GetValue() * (m_joycon_motion_invert_z->GetValue() ? -1.0f : 1.0f);\n\t\tjoycon->set_motion_scale(x, y, z);\n\t}\n}\n\nvoid WiimoteInputPanel::on_joycon_motion_reset(wxCommandEvent&)\n{\n\tm_joycon_motion_x->SetValue(1.0);\n\tm_joycon_motion_y->SetValue(1.0);\n\tm_joycon_motion_z->SetValue(1.0);\n\tm_joycon_motion_invert_x->SetValue(false);\n\tm_joycon_motion_invert_y->SetValue(false);\n\tm_joycon_motion_invert_z->SetValue(false);\n\tif (const auto joycon = m_active_joycon.lock())\n\t\tjoycon->set_motion_scale(1.0f, 1.0f, 1.0f);\n}\n\nvoid WiimoteInputPanel::on_joycon_pointer_paint(wxPaintEvent&)\n{\n\twxAutoBufferedPaintDC dc(m_joycon_pointer_preview);\n\tdc.SetBackground(wxBrush(wxSystemSettings::GetColour(wxSYS_COLOUR_WINDOW)));\n\tdc.Clear();\n\tconst wxSize size = m_joycon_pointer_preview->GetClientSize();\n\tdc.SetPen(wxPen(wxSystemSettings::GetColour(wxSYS_COLOUR_GRAYTEXT)));\n\tdc.DrawLine(size.x / 2, 0, size.x / 2, size.y);\n\tdc.DrawLine(0, size.y / 2, size.x, size.y / 2);\n\tif (m_joycon_preview_valid)\n\t{\n\t\tconst int x = std::clamp((int)std::lround(m_joycon_preview_x * (size.x - 1)), 0, std::max(0, size.x - 1));\n\t\tconst int y = std::clamp((int)std::lround(m_joycon_preview_y * (size.y - 1)), 0, std::max(0, size.y - 1));\n\t\tdc.SetPen(wxPen(wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHT), 2));\n\t\tdc.DrawCircle(x, y, 5);\n\t}\n}\n\nvoid WiimoteInputPanel::on_joycon_pointer_enable(wxCommandEvent&)\n''',
    "V8 calibration handlers and live pointer painter",
)

print("Cemu Joy-Con V8 3D pointer + R-Sideways normalization + calibration UI applied successfully.")
