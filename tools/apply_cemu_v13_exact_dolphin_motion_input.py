from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v13_exact_dolphin_motion_input.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str) -> None:
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


# -----------------------------------------------------------------------------
# Dolphin settings are real runtime settings in V13. The legacy V8 motion scale
# remains loadable for profile compatibility, but is deliberately not part of
# the Dolphin direct-sensor path. A value such as Z=1.25 turned a correct 1.04 g
# sample into the 1.29 g sample visible in the user's V12 screenshot.
# -----------------------------------------------------------------------------
replace_once(
    provider_h,
    "\t\tfloat sample_rate_hz{};\n\t\tbool stable{};\n",
    "\t\tfloat sample_rate_hz{};\n\t\tfloat gyro_deadzone_degrees{ 2.0f };\n\t\tfloat calibration_period_seconds{ 3.0f };\n\t\tbool stable{};\n",
    "publish configurable Dolphin gyro values",
)

replace_once(
    provider_h,
    "\tvoid set_joycon_motion_scale(SDL_JoystickID diid, float x, float y, float z);\n",
    "\tvoid set_joycon_motion_scale(SDL_JoystickID diid, float x, float y, float z);\n"
    "\tvoid set_joycon_dolphin_motion_settings(SDL_JoystickID diid, float gyro_deadzone_degrees, float calibration_period_seconds);\n",
    "declare Dolphin calibration settings provider API",
)

replace_once(
    provider_h,
    "\t\tfloat motion_scale_z{ 1.0f };\n\t};\n",
    "\t\tfloat motion_scale_z{ 1.0f };\n"
    "\t\tfloat gyro_deadzone_degrees{ 2.0f };\n"
    "\t\tfloat calibration_period_seconds{ 3.0f };\n"
    "\t};\n",
    "store per-Joy-Con Dolphin calibration settings",
)

replace_once(
    provider_cpp,
    "\tdebug.sample_rate_hz = state.dolphin_sample_rate_hz;\n"
    "\tdebug.stable = state.dolphin_calibration_stable;\n",
    "\tdebug.sample_rate_hz = state.dolphin_sample_rate_hz;\n"
    "\tif (const auto config = s_joycon_orientation_states.find(diid); config != s_joycon_orientation_states.end())\n"
    "\t{\n"
    "\t\tdebug.gyro_deadzone_degrees = config->second.gyro_deadzone_degrees;\n"
    "\t\tdebug.calibration_period_seconds = config->second.calibration_period_seconds;\n"
    "\t}\n"
    "\tdebug.stable = state.dolphin_calibration_stable;\n",
    "include active Dolphin calibration values in live snapshot",
)

replace_once(
    provider_cpp,
    "\tif (state.dolphin_calibration_start != 0 && debug.timestamp >= state.dolphin_calibration_start)\n"
    "\t{\n"
    "\t\tconst float elapsed = static_cast<float>(debug.timestamp - state.dolphin_calibration_start) / 3000000000.0f;\n"
    "\t\tdebug.calibration_progress = std::clamp(elapsed, 0.0f, 1.0f);\n"
    "\t}\n",
    "\tif (state.dolphin_calibration_start != 0 && debug.timestamp >= state.dolphin_calibration_start &&\n"
    "\t\tdebug.calibration_period_seconds > 0.0f)\n"
    "\t{\n"
    "\t\tconst float period_ns = debug.calibration_period_seconds * 1000000000.0f;\n"
    "\t\tconst float elapsed = static_cast<float>(debug.timestamp - state.dolphin_calibration_start) / period_ns;\n"
    "\t\tdebug.calibration_progress = std::clamp(elapsed, 0.0f, 1.0f);\n"
    "\t}\n",
    "calculate live calibration progress from configured Dolphin period",
)

replace_once(
    provider_cpp,
    "void SDLControllerProvider::clear_joycon_orientation(SDL_JoystickID diid)\n",
    "void SDLControllerProvider::set_joycon_dolphin_motion_settings(SDL_JoystickID diid, float gyro_deadzone_degrees, float calibration_period_seconds)\n"
    "{\n"
    "\tif (diid < 0)\n"
    "\t\treturn;\n\n"
    "\tgyro_deadzone_degrees = std::clamp(gyro_deadzone_degrees, 0.0f, 180.0f);\n"
    "\tcalibration_period_seconds = std::clamp(calibration_period_seconds, 0.0f, 30.0f);\n"
    "\tstd::scoped_lock lock(s_mutex);\n"
    "\tauto& state = s_joycon_orientation_states[diid];\n"
    "\tif (state.gyro_deadzone_degrees != gyro_deadzone_degrees ||\n"
    "\t\tstate.calibration_period_seconds != calibration_period_seconds)\n"
    "\t{\n"
    "\t\tstate.gyro_deadzone_degrees = gyro_deadzone_degrees;\n"
    "\t\tstate.calibration_period_seconds = calibration_period_seconds;\n"
    "\t\ts_motion_states.erase(diid);\n"
    "\t}\n"
    "}\n\n"
    "void SDLControllerProvider::clear_joycon_orientation(SDL_JoystickID diid)\n",
    "implement Dolphin calibration settings provider API",
)

replace_once(
    provider_cpp,
    "\t\t\t\t\tconstexpr float kDolphinGyroDeadzone = 2.0f * 3.14159265358979323846f / 180.0f;\n"
    "\t\t\t\t\tconstexpr uint64 kDolphinCalibrationPeriodNs = 3000000000ULL;\n"
    "\t\t\t\t\tconstexpr double kDolphinMinCalibrationHz = 25.0;\n"
    "\t\t\t\t\tglm::vec3 raw_gyro{ -v10_native[0], v10_native[2], v10_native[1] };\n",
    "\t\t\t\t\tconstexpr double kDolphinMinCalibrationHz = 25.0;\n"
    "\t\t\t\t\tfloat kDolphinGyroDeadzone = 2.0f * 3.14159265358979323846f / 180.0f;\n"
    "\t\t\t\t\tuint64 kDolphinCalibrationPeriodNs = 3000000000ULL;\n"
    "\t\t\t\t\tif (const auto config = s_joycon_orientation_states.find(id); config != s_joycon_orientation_states.end())\n"
    "\t\t\t\t\t{\n"
    "\t\t\t\t\t\tkDolphinGyroDeadzone = config->second.gyro_deadzone_degrees * 3.14159265358979323846f / 180.0f;\n"
    "\t\t\t\t\t\tkDolphinCalibrationPeriodNs = static_cast<uint64>(config->second.calibration_period_seconds * 1000000000.0f);\n"
    "\t\t\t\t\t}\n"
    "\t\t\t\t\tglm::vec3 raw_gyro{ -v10_native[0], v10_native[2], v10_native[1] };\n",
    "use adjustable Dolphin gyro deadzone and calibration period",
)

replace_once(
    provider_cpp,
    "\t\t\t\t\tif (state.dolphin_calibration_count == 0)\n"
    "\t\t\t\t\t{\n",
    "\t\t\t\t\tif (kDolphinCalibrationPeriodNs == 0)\n"
    "\t\t\t\t\t{\n"
    "\t\t\t\t\t\tstate.dolphin_gyro_bias = {};\n"
    "\t\t\t\t\t\tstate.dolphin_calibration_count = 0;\n"
    "\t\t\t\t\t\tstate.dolphin_calibration_stable = true;\n"
    "\t\t\t\t\t\tstate.dolphin_calibration_complete = true;\n"
    "\t\t\t\t\t}\n"
    "\t\t\t\t\telse if (state.dolphin_calibration_count == 0)\n"
    "\t\t\t\t\t{\n",
    "match Dolphin zero-period calibration disable behavior",
)

replace_once(
    provider_cpp,
    "\t\t\tif (tracking.hasAcc && tracking.hasGyro)\n"
    "\t\t\t{\n"
    "\t\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n"
    "\t\t\t\t\tconfig != s_joycon_orientation_states.end())\n"
    "\t\t\t\t{\n"
    "\t\t\t\t\tconst glm::vec3 scale{ config->second.motion_scale_x, config->second.motion_scale_y, config->second.motion_scale_z };\n"
    "\t\t\t\t\ttracking.acc *= scale;\n"
    "\t\t\t\t\ttracking.gyro *= scale;\n"
    "\t\t\t\t\tstate.dolphin_motion_acc = tracking.acc;\n"
    "\t\t\t\t\tstate.dolphin_motion_gyro = tracking.gyro;\n"
    "\t\t\t\t}\n\n",
    "\t\t\tif (tracking.hasAcc && tracking.hasGyro)\n"
    "\t\t\t{\n"
    "\t\t\t\t// Dolphin direct sensor semantics use calibrated raw units. Legacy V8-V12\n"
    "\t\t\t\t// scale values must not amplify gravity or angular velocity.\n"
    "\t\t\t\tstate.dolphin_motion_acc = tracking.acc;\n"
    "\t\t\t\tstate.dolphin_motion_gyro = tracking.gyro;\n\n",
    "remove legacy scale distortion from Dolphin direct motion path",
)


# Controller-side settings and profile persistence.
replace_once(
    controller_h,
    "\tvoid set_pointer_calibration(float yaw_degrees, float pitch_degrees, float deadzone_degrees, float smoothing, bool invert_x, bool invert_y);\n\n",
    "\tvoid set_pointer_calibration(float horizontal_fov_degrees, float vertical_fov_degrees, float deadzone_degrees, float smoothing, bool invert_x, bool invert_y);\n"
    "\tfloat get_dolphin_total_yaw_degrees() const { return m_dolphin_total_yaw_degrees.load(std::memory_order_relaxed); }\n"
    "\tfloat get_dolphin_accel_influence() const { return m_dolphin_accel_influence.load(std::memory_order_relaxed); }\n"
    "\tfloat get_dolphin_gyro_deadzone_degrees() const { return m_dolphin_gyro_deadzone_degrees.load(std::memory_order_relaxed); }\n"
    "\tfloat get_dolphin_calibration_period_seconds() const { return m_dolphin_calibration_period_seconds.load(std::memory_order_relaxed); }\n"
    "\tvoid set_dolphin_motion_settings(float total_yaw_degrees, float accel_influence, float gyro_deadzone_degrees, float calibration_period_seconds);\n\n",
    "declare exact Dolphin Point and Gyroscope settings",
)

replace_once(
    controller_h,
    "\tstd::atomic<float> m_pointer_yaw_degrees{ 25.0f };\n"
    "\tstd::atomic<float> m_pointer_pitch_degrees{ 20.0f };\n",
    "\t// V13: these legacy profile fields now carry Dolphin Horizontal/Vertical FOV.\n"
    "\tstd::atomic<float> m_pointer_yaw_degrees{ 42.0f };\n"
    "\tstd::atomic<float> m_pointer_pitch_degrees{ 31.5f };\n"
    "\tstd::atomic<float> m_dolphin_total_yaw_degrees{ 25.0f };\n"
    "\tstd::atomic<float> m_dolphin_accel_influence{ 0.01f };\n"
    "\tstd::atomic<float> m_dolphin_gyro_deadzone_degrees{ 2.0f };\n"
    "\tstd::atomic<float> m_dolphin_calibration_period_seconds{ 3.0f };\n",
    "store exact Dolphin defaults separately",
)

replace_once(
    controller_cpp,
    "void SDLController::set_pointer_calibration(float yaw_degrees, float pitch_degrees, float deadzone_degrees, float smoothing, bool invert_x, bool invert_y)\n"
    "{\n"
    "\tyaw_degrees = std::clamp(yaw_degrees, 5.0f, 120.0f);\n"
    "\tpitch_degrees = std::clamp(pitch_degrees, 5.0f, 120.0f);\n",
    "void SDLController::set_pointer_calibration(float horizontal_fov_degrees, float vertical_fov_degrees, float deadzone_degrees, float smoothing, bool invert_x, bool invert_y)\n"
    "{\n"
    "\thorizontal_fov_degrees = std::clamp(horizontal_fov_degrees, 0.01f, 180.0f);\n"
    "\tvertical_fov_degrees = std::clamp(vertical_fov_degrees, 0.01f, 180.0f);\n",
    "give legacy pointer fields Dolphin FOV semantics",
)

replace_once(
    controller_cpp,
    "\tm_pointer_yaw_degrees.store(yaw_degrees, std::memory_order_relaxed);\n"
    "\tm_pointer_pitch_degrees.store(pitch_degrees, std::memory_order_relaxed);\n",
    "\tm_pointer_yaw_degrees.store(horizontal_fov_degrees, std::memory_order_relaxed);\n"
    "\tm_pointer_pitch_degrees.store(vertical_fov_degrees, std::memory_order_relaxed);\n",
    "persist Dolphin horizontal and vertical FOV",
)

replace_once(
    controller_cpp,
    "void SDLController::get_motion_scale(float& x, float& y, float& z) const\n",
    "void SDLController::set_dolphin_motion_settings(float total_yaw_degrees, float accel_influence, float gyro_deadzone_degrees, float calibration_period_seconds)\n"
    "{\n"
    "\ttotal_yaw_degrees = std::clamp(total_yaw_degrees, 0.0f, 360.0f);\n"
    "\taccel_influence = std::clamp(accel_influence, 0.0f, 1.0f);\n"
    "\tgyro_deadzone_degrees = std::clamp(gyro_deadzone_degrees, 0.0f, 180.0f);\n"
    "\tcalibration_period_seconds = std::clamp(calibration_period_seconds, 0.0f, 30.0f);\n"
    "\tm_dolphin_total_yaw_degrees.store(total_yaw_degrees, std::memory_order_relaxed);\n"
    "\tm_dolphin_accel_influence.store(accel_influence, std::memory_order_relaxed);\n"
    "\tm_dolphin_gyro_deadzone_degrees.store(gyro_deadzone_degrees, std::memory_order_relaxed);\n"
    "\tm_dolphin_calibration_period_seconds.store(calibration_period_seconds, std::memory_order_relaxed);\n"
    "\tif (m_diid >= 0)\n"
    "\t\tm_provider->set_joycon_dolphin_motion_settings(m_diid, gyro_deadzone_degrees, calibration_period_seconds);\n"
    "}\n\n"
    "void SDLController::get_motion_scale(float& x, float& y, float& z) const\n",
    "implement exact Dolphin Point and Gyroscope settings",
)

replace_once(
    controller_cpp,
    "\tconstexpr float kDolphinTotalYaw = 25.0f * kPi / 180.0f;\n"
    "\tconstexpr float kDolphinVerticalFov = 31.5f * kPi / 180.0f;\n"
    "\tconstexpr float kDolphinAccelInfluence = 0.01f; // user's working WiimoteNew.ini\n",
    "\tconst float kDolphinTotalYaw = get_dolphin_total_yaw_degrees() * kPi / 180.0f;\n"
    "\tconst float kDolphinHorizontalFov = get_pointer_yaw_degrees() * kPi / 180.0f;\n"
    "\tconst float kDolphinVerticalFov = get_pointer_pitch_degrees() * kPi / 180.0f;\n"
    "\tconst float kDolphinAccelInfluence = get_dolphin_accel_influence();\n",
    "use live Dolphin Point settings in quaternion fusion",
)

replace_once(
    controller_cpp,
    "\tconst float max_yaw = kDolphinTotalYaw * 0.5f;\n"
    "\tconst float max_pitch = kDolphinVerticalFov * 0.5f;\n"
    "\tconst glm::vec2 target{\n",
    "\t// Preserve the proven V10 default geometry while giving Horizontal FOV the\n"
    "\t// same sensitivity direction as Dolphin: a wider camera FOV needs more yaw.\n"
    "\tconst float max_yaw = std::max(0.0001f, kDolphinTotalYaw * 0.5f * (kDolphinHorizontalFov / (42.0f * kPi / 180.0f)));\n"
    "\tconst float max_pitch = std::max(0.0001f, kDolphinVerticalFov * 0.5f);\n"
    "\tconst glm::vec2 target{\n",
    "make Dolphin FOV controls affect pointer sensitivity without changing defaults",
)

replace_once(
    controller_cpp,
    "\tnode.append_child(\"joycon_pointer_invert_y\").append_child(pugi::node_pcdata).set_value(get_pointer_invert_y() ? \"1\" : \"0\");\n",
    "\tnode.append_child(\"joycon_pointer_invert_y\").append_child(pugi::node_pcdata).set_value(get_pointer_invert_y() ? \"1\" : \"0\");\n"
    "\tnode.append_child(\"joycon_dolphin_total_yaw_deg\").append_child(pugi::node_pcdata).set_value(fmt::format(\"{:.3f}\", get_dolphin_total_yaw_degrees()).c_str());\n"
    "\tnode.append_child(\"joycon_dolphin_accel_influence\").append_child(pugi::node_pcdata).set_value(fmt::format(\"{:.4f}\", get_dolphin_accel_influence()).c_str());\n"
    "\tnode.append_child(\"joycon_dolphin_gyro_deadzone_deg_s\").append_child(pugi::node_pcdata).set_value(fmt::format(\"{:.3f}\", get_dolphin_gyro_deadzone_degrees()).c_str());\n"
    "\tnode.append_child(\"joycon_dolphin_calibration_period_s\").append_child(pugi::node_pcdata).set_value(fmt::format(\"{:.3f}\", get_dolphin_calibration_period_seconds()).c_str());\n",
    "save all Dolphin Motion Input settings",
)

replace_once(
    controller_cpp,
    "\tfloat pointer_yaw = 25.0f;\n\tfloat pointer_pitch = 20.0f;\n",
    "\tfloat pointer_yaw = 42.0f;\n\tfloat pointer_pitch = 31.5f;\n",
    "use Dolphin FOV profile defaults",
)

replace_once(
    controller_cpp,
    "\tif (const auto value = node.child(\"joycon_pointer_smoothing\")) pointer_smoothing = ConvertString<float>(value.child_value());\n"
    "\t// V10 displayed 2.00 / 0.01 but did not actually use those fields. Migrate only\n",
    "\tif (const auto value = node.child(\"joycon_pointer_smoothing\")) pointer_smoothing = ConvertString<float>(value.child_value());\n"
    "\t// V8-V12 called these fields yaw/pitch although V10's actual geometry was\n"
    "\t// fixed at Dolphin 25/31.5. Migrate only the untouched legacy defaults.\n"
    "\tif (std::abs(pointer_yaw - 25.0f) < 0.001f && std::abs(pointer_pitch - 20.0f) < 0.001f)\n"
    "\t{\n"
    "\t\tpointer_yaw = 42.0f;\n"
    "\t\tpointer_pitch = 31.5f;\n"
    "\t}\n"
    "\t// V10 displayed 2.00 / 0.01 but did not actually use those fields. Migrate only\n",
    "migrate untouched legacy pointer labels to Dolphin FOV defaults",
)

replace_once(
    controller_cpp,
    "\tset_pointer_calibration(pointer_yaw, pointer_pitch, pointer_deadzone, pointer_smoothing, pointer_invert_x, pointer_invert_y);\n"
    "\tfloat motion_x = 1.0f, motion_y = 1.0f, motion_z = 1.0f;\n"
    "\tif (const auto value = node.child(\"joycon_motion_scale_x\")) motion_x = ConvertString<float>(value.child_value());\n"
    "\tif (const auto value = node.child(\"joycon_motion_scale_y\")) motion_y = ConvertString<float>(value.child_value());\n"
    "\tif (const auto value = node.child(\"joycon_motion_scale_z\")) motion_z = ConvertString<float>(value.child_value());\n"
    "\tset_motion_scale(motion_x, motion_y, motion_z);\n",
    "\tset_pointer_calibration(pointer_yaw, pointer_pitch, pointer_deadzone, pointer_smoothing, pointer_invert_x, pointer_invert_y);\n"
    "\tfloat total_yaw = 25.0f;\n"
    "\tfloat accel_influence = 0.01f;\n"
    "\tfloat gyro_deadzone = 2.0f;\n"
    "\tfloat calibration_period = 3.0f;\n"
    "\tif (const auto value = node.child(\"joycon_dolphin_total_yaw_deg\")) total_yaw = ConvertString<float>(value.child_value());\n"
    "\tif (const auto value = node.child(\"joycon_dolphin_accel_influence\")) accel_influence = ConvertString<float>(value.child_value());\n"
    "\tif (const auto value = node.child(\"joycon_dolphin_gyro_deadzone_deg_s\")) gyro_deadzone = ConvertString<float>(value.child_value());\n"
    "\tif (const auto value = node.child(\"joycon_dolphin_calibration_period_s\")) calibration_period = ConvertString<float>(value.child_value());\n"
    "\tset_dolphin_motion_settings(total_yaw, accel_influence, gyro_deadzone, calibration_period);\n"
    "\t// V13 migration: these legacy controls were inert through V11 and distorted\n"
    "\t// physical units when V12 began consuming them. Dolphin direct input is 1:1.\n"
    "\tset_motion_scale(1.0f, 1.0f, 1.0f);\n",
    "migrate distorted legacy motion scales and load Dolphin settings",
)

replace_once(
    controller_cpp,
    "\t\tm_provider->set_joycon_motion_scale(m_diid,\n"
    "\t\t\tm_motion_scale_x.load(std::memory_order_relaxed),\n"
    "\t\t\tm_motion_scale_y.load(std::memory_order_relaxed),\n"
    "\t\t\tm_motion_scale_z.load(std::memory_order_relaxed));\n",
    "\t\tm_provider->set_joycon_motion_scale(m_diid, 1.0f, 1.0f, 1.0f);\n"
    "\t\tm_provider->set_joycon_dolphin_motion_settings(m_diid,\n"
    "\t\t\tm_dolphin_gyro_deadzone_degrees.load(std::memory_order_relaxed),\n"
    "\t\t\tm_dolphin_calibration_period_seconds.load(std::memory_order_relaxed));\n",
    "initialize provider with exact Dolphin settings",
)


# -----------------------------------------------------------------------------
# Replace the compact V12 motion dialog with a native wxWidgets version of the
# Dolphin Motion Input organization. Point includes the requested live pointer.
# -----------------------------------------------------------------------------
replace_once(
    panel_cpp,
    "#include <cmath>\n",
    "#include <cmath>\n#include <utility>\n",
    "include pair utilities for Dolphin binding rows",
)

replace_once(
    panel_cpp,
    '\tauto* yaw = make_spin(_("Horizontal range / Yaw (degrees)"), joycon->get_pointer_yaw_degrees(), 5.0, 120.0, 1.0, 1);\n'
    '\tauto* pitch = make_spin(_("Vertical range / Pitch (degrees)"), joycon->get_pointer_pitch_degrees(), 5.0, 120.0, 1.0, 1);\n',
    '\tauto* yaw = make_spin(_("Horizontal FOV (degrees)"), joycon->get_pointer_yaw_degrees(), 0.01, 180.0, 0.5, 2);\n'
    '\tauto* pitch = make_spin(_("Vertical FOV (degrees)"), joycon->get_pointer_pitch_degrees(), 0.01, 180.0, 0.5, 2);\n',
    "give standalone Pointer dialog Dolphin FOV labels",
)

text = panel_cpp.read_text(encoding="utf-8")
start = text.find("void WiimoteInputPanel::on_joycon_motion_dialog(wxCommandEvent&)")
end = text.find("void WiimoteInputPanel::on_joycon_pointer_recenter(wxCommandEvent&)")
if start < 0 or end < 0 or end <= start:
    raise RuntimeError("V12 motion dialog anchors not found")

new_motion_dialog = r'''void WiimoteInputPanel::on_joycon_motion_dialog(wxCommandEvent&)
{
	const auto joycon = m_active_joycon.lock();
	if (!joycon)
		return;

	wxDialog dialog(this, wxID_ANY, _("Motion Input - Dolphin Wii Remote"), wxDefaultPosition, wxDefaultSize,
		wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
	auto* outer = new wxBoxSizer(wxVERTICAL);
	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("The Accelerometer and Gyroscope controls use the Joy-Con motion sensors directly, matching Dolphin's Wii Remote motion semantics.")),
		0, wxEXPAND | wxALL, 10);

	const float original_hfov = joycon->get_pointer_yaw_degrees();
	const float original_vfov = joycon->get_pointer_pitch_degrees();
	const float original_deadzone = joycon->get_pointer_deadzone_degrees();
	const float original_smoothing = joycon->get_pointer_smoothing();
	const bool original_invert_x = joycon->get_pointer_invert_x();
	const bool original_invert_y = joycon->get_pointer_invert_y();
	const float original_total_yaw = joycon->get_dolphin_total_yaw_degrees();
	const float original_accel_influence = joycon->get_dolphin_accel_influence();
	const float original_gyro_deadzone = joycon->get_dolphin_gyro_deadzone_degrees();
	const float original_calibration_period = joycon->get_dolphin_calibration_period_seconds();
	const auto original_orientation = joycon->get_joycon_orientation();

	SDLControllerProvider::DolphinMotionDebug debug{};
	bool debug_valid = joycon->get_dolphin_motion_debug(debug);
	glm::vec2 pointer_sensor{0.5f}, pointer_target{0.5f}, pointer_output{0.5f};
	bool pointer_valid = joycon->get_joycon_pointer_debug(pointer_sensor, pointer_target, pointer_output);

	auto* groups = new wxBoxSizer(wxHORIZONTAL);
	auto* point_box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Point"));
	auto* point_preview = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(250, 170), wxBORDER_SIMPLE);
	point_preview->SetMinSize(wxSize(230, 150));
	point_preview->SetBackgroundStyle(wxBG_STYLE_PAINT);
	point_preview->Bind(wxEVT_PAINT, [&](wxPaintEvent&) {
		wxAutoBufferedPaintDC dc(point_preview);
		const wxSize size = point_preview->GetClientSize();
		dc.SetBackground(wxBrush(wxColour(24, 27, 32)));
		dc.Clear();
		dc.SetPen(wxPen(wxColour(70, 76, 86), 1));
		dc.DrawLine(size.x / 2, 0, size.x / 2, size.y);
		dc.DrawLine(0, size.y / 2, size.x, size.y / 2);
		if (!pointer_valid)
		{
			dc.SetTextForeground(wxColour(210, 210, 210));
			dc.DrawText(_("Waiting for pointer..."), 8, 8);
			return;
		}
		auto p = [&](const glm::vec2& value) {
			return wxPoint((int)std::lround(std::clamp(value.x, 0.0f, 1.0f) * (size.x - 1)),
				(int)std::lround(std::clamp(value.y, 0.0f, 1.0f) * (size.y - 1)));
		};
		dc.SetPen(*wxTRANSPARENT_PEN);
		dc.SetBrush(wxBrush(wxColour(255, 205, 65))); dc.DrawCircle(p(pointer_sensor), 4);
		dc.SetBrush(wxBrush(wxColour(75, 150, 255))); dc.DrawCircle(p(pointer_target), 5);
		dc.SetBrush(wxBrush(wxColour(70, 220, 120))); dc.DrawCircle(p(pointer_output), 6);
	});
	point_box->Add(point_preview, 0, wxEXPAND | wxALL, 6);
	point_box->Add(new wxStaticText(&dialog, wxID_ANY, _("Yellow sensor | Blue deadzone | Green game output")), 0, wxLEFT | wxRIGHT | wxBOTTOM, 6);

	auto* point_grid = new wxFlexGridSizer(3, 5, 6);
	point_grid->AddGrowableCol(1, 1);
	auto add_point_setting = [&](const wxString& label, double value, double minv, double maxv, double step, int digits) {
		point_grid->Add(new wxStaticText(&dialog, wxID_ANY, label), 0, wxALIGN_CENTER_VERTICAL);
		auto* spin = new wxSpinCtrlDouble(&dialog, wxID_ANY);
		spin->SetRange(minv, maxv); spin->SetIncrement(step); spin->SetDigits(digits); spin->SetValue(value);
		point_grid->Add(spin, 1, wxEXPAND);
		point_grid->Add(new wxButton(&dialog, wxID_ANY, _("..."), wxDefaultPosition, wxSize(38, -1)), 0);
		return spin;
	};
	auto* total_yaw = add_point_setting(_("Total Yaw"), original_total_yaw, 0.0, 360.0, 1.0, 2);
	auto* accel_influence = add_point_setting(_("Accelerometer Influence (%)"), original_accel_influence * 100.0f, 0.0, 100.0, 0.1, 2);
	auto* horizontal_fov = add_point_setting(_("Horizontal FOV"), original_hfov, 0.01, 180.0, 0.5, 2);
	auto* vertical_fov = add_point_setting(_("Vertical FOV"), original_vfov, 0.01, 180.0, 0.5, 2);
	auto* pointer_deadzone = add_point_setting(_("Pointer Deadzone"), original_deadzone, 0.0, 5.0, 0.05, 2);
	auto* pointer_smoothing = add_point_setting(_("Smooth (0 = direct)"), original_smoothing, 0.0, 0.95, 0.01, 2);
	point_box->Add(point_grid, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);

	auto* point_flags = new wxBoxSizer(wxHORIZONTAL);
	auto* enabled = new wxCheckBox(&dialog, wxID_ANY, _("Enabled")); enabled->SetValue(joycon->is_pointer_enabled());
	auto* invert_x = new wxCheckBox(&dialog, wxID_ANY, _("Invert X")); invert_x->SetValue(original_invert_x);
	auto* invert_y = new wxCheckBox(&dialog, wxID_ANY, _("Invert Y")); invert_y->SetValue(original_invert_y);
	point_flags->Add(enabled, 0, wxRIGHT, 8); point_flags->Add(invert_x, 0, wxRIGHT, 8); point_flags->Add(invert_y, 0);
	point_box->Add(point_flags, 0, wxLEFT | wxRIGHT | wxBOTTOM, 6);
	auto* recenter = new wxButton(&dialog, wxID_ANY, _("Recenter now"));
	recenter->Bind(wxEVT_BUTTON, [joycon](wxCommandEvent&) { joycon->recenter_joycon_pointer(); });
	point_box->Add(recenter, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);
	std::vector<uint32> recenter_hotkey = joycon->get_pointer_recenter_hotkey();
	auto* recenter_binding = new wxButton(&dialog, wxID_ANY,
		_("Recenter: ") + joycon_hotkey_label(joycon, recenter_hotkey));
	point_box->Add(recenter_binding, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);
	groups->Add(point_box, 1, wxEXPAND | wxRIGHT, 6);

	auto* passthrough_box = new wxStaticBoxSizer(wxVERTICAL, &dialog, _("Point (Passthrough)"));
	auto* passthrough_view = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(150, 170), wxBORDER_SIMPLE);
	passthrough_view->SetBackgroundColour(wxColour(24, 27, 32));
	passthrough_box->Add(passthrough_view, 0, wxEXPAND | wxALL, 6);
	auto* passthrough_enabled = new wxCheckBox(&dialog, wxID_ANY, _("Enabled"));
	passthrough_enabled->SetValue(false); passthrough_enabled->Enable(false);
	passthrough_box->Add(passthrough_enabled, 0, wxLEFT | wxRIGHT | wxBOTTOM, 6);
	passthrough_box->Add(new wxStaticText(&dialog, wxID_ANY, _("Native Joy-Con IMU pointer.\nCemu generates DPD objects\nautomatically.")),
		0, wxLEFT | wxRIGHT | wxBOTTOM, 6);
	groups->Add(passthrough_box, 0, wxEXPAND | wxRIGHT, 6);

	auto make_sensor_box = [&](const wxString& title, bool gyro) {
		auto* box = new wxStaticBoxSizer(wxVERTICAL, &dialog, title);
		auto* view = new wxPanel(&dialog, wxID_ANY, wxDefaultPosition, wxSize(190, 170), wxBORDER_SIMPLE);
		view->SetMinSize(wxSize(175, 150)); view->SetBackgroundStyle(wxBG_STYLE_PAINT);
		view->Bind(wxEVT_PAINT, [&, view, gyro](wxPaintEvent&) {
			wxAutoBufferedPaintDC dc(view);
			const wxSize size = view->GetClientSize();
			dc.SetBackground(wxBrush(wxColour(24, 27, 32))); dc.Clear();
			const int radius = std::max(25, std::min(size.x, size.y) / 2 - 24);
			const wxPoint center(size.x / 2, size.y / 2);
			dc.SetPen(wxPen(wxColour(95, 100, 110))); dc.SetBrush(*wxTRANSPARENT_BRUSH);
			dc.DrawCircle(center, radius); dc.DrawLine(center.x - radius, center.y, center.x + radius, center.y);
			dc.DrawLine(center.x, center.y - radius, center.x, center.y + radius);
			if (!debug_valid) return;
			const glm::vec3 value = gyro ? debug.gyro : debug.accel;
			const float scale = gyro ? 3.14159265f : 1.0f;
			const wxPoint tip(center.x + (int)std::lround(std::clamp(value.x / scale, -1.0f, 1.0f) * radius),
				center.y - (int)std::lround(std::clamp(value.z / scale, -1.0f, 1.0f) * radius));
			dc.SetPen(wxPen(gyro ? wxColour(80, 135, 255) : wxColour(70, 220, 120), 2)); dc.DrawLine(center, tip);
			dc.SetBrush(wxBrush(gyro ? wxColour(80, 135, 255) : wxColour(70, 220, 120))); dc.DrawCircle(tip, 5);
		});
		box->Add(view, 0, wxEXPAND | wxALL, 6);
		return std::pair<wxStaticBoxSizer*, wxPanel*>(box, view);
	};
	auto [accel_box, accel_view] = make_sensor_box(_("Accelerometer"), false);
	for (const auto& row : {std::pair<const wchar_t*, const wchar_t*>(L"Up", L"Accel Up"), {L"Down", L"Accel Down"},
		{L"Left", L"Accel Left"}, {L"Right", L"Accel Right"}, {L"Forward", L"Accel Forward"}, {L"Backward", L"Accel Backward"}})
	{
		auto* line = new wxBoxSizer(wxHORIZONTAL); line->Add(new wxStaticText(&dialog, wxID_ANY, wxString(row.first)), 1, wxALIGN_CENTER_VERTICAL);
		auto* binding = new wxButton(&dialog, wxID_ANY, wxString(row.second)); binding->Enable(false); line->Add(binding, 0);
		accel_box->Add(line, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 4);
	}
	groups->Add(accel_box, 0, wxEXPAND | wxRIGHT, 6);

	auto [gyro_box, gyro_view] = make_sensor_box(_("Gyroscope"), true);
	for (const auto& row : {std::pair<const wchar_t*, const wchar_t*>(L"Pitch Up", L"Gyro Pitch Up"), {L"Pitch Down", L"Gyro Pitch Down"},
		{L"Roll Left", L"Gyro Roll Left"}, {L"Roll Right", L"Gyro Roll Right"}, {L"Yaw Left", L"Gyro Yaw Left"}, {L"Yaw Right", L"Gyro Yaw Right"}})
	{
		auto* line = new wxBoxSizer(wxHORIZONTAL); line->Add(new wxStaticText(&dialog, wxID_ANY, wxString(row.first)), 1, wxALIGN_CENTER_VERTICAL);
		auto* binding = new wxButton(&dialog, wxID_ANY, wxString(row.second)); binding->Enable(false); line->Add(binding, 0);
		gyro_box->Add(line, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 4);
	}
	auto add_gyro_setting = [&](const wxString& label, double value, double minv, double maxv, double step) {
		auto* line = new wxBoxSizer(wxHORIZONTAL); line->Add(new wxStaticText(&dialog, wxID_ANY, label), 1, wxALIGN_CENTER_VERTICAL);
		auto* spin = new wxSpinCtrlDouble(&dialog, wxID_ANY); spin->SetRange(minv, maxv); spin->SetIncrement(step); spin->SetDigits(2); spin->SetValue(value);
		line->Add(spin, 0); gyro_box->Add(line, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 4); return spin;
	};
	auto* gyro_deadzone = add_gyro_setting(_("Dead Zone (degrees/s)"), original_gyro_deadzone, 0.0, 180.0, 0.1);
	auto* calibration_period = add_gyro_setting(_("Calibration Period (s)"), original_calibration_period, 0.0, 30.0, 0.25);
	groups->Add(gyro_box, 0, wxEXPAND);
	outer->Add(groups, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* orientation_box = new wxStaticBoxSizer(wxHORIZONTAL, &dialog, _("Physical orientation"));
	auto* orientation = new wxChoice(&dialog, wxID_ANY); orientation->Append(_("Sideways")); orientation->Append(_("Vertical"));
	orientation->SetSelection(original_orientation == SDLController::JoyConOrientation::Vertical ? 0 : 1);
	orientation_box->Add(orientation, 0, wxALL, 6);
	orientation_box->Add(new wxStaticText(&dialog, wxID_ANY, joycon->is_left_joycon() ?
		_("Joy-Con L Sideways = Dolphin -90 degree orientation") : _("Joy-Con R Sideways = proven Dolphin 180 degree fix")),
		1, wxALL | wxALIGN_CENTER_VERTICAL, 6);
	outer->Add(orientation_box, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);

	auto* status = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
	auto* values = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
	outer->Add(status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);
	outer->Add(values, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);

	bool capture_active = false, capture_wait_idle = false, capture_pressed = false;
	recenter_binding->Bind(wxEVT_BUTTON, [&](wxCommandEvent&) {
		capture_active = true; capture_wait_idle = true; capture_pressed = false; recenter_hotkey.clear();
		recenter_binding->SetLabel(_("Release all controller buttons..."));
	});
	auto apply_live = [=](wxCommandEvent&) {
		joycon->set_pointer_calibration((float)horizontal_fov->GetValue(), (float)vertical_fov->GetValue(),
			(float)pointer_deadzone->GetValue(), (float)pointer_smoothing->GetValue(), invert_x->GetValue(), invert_y->GetValue());
		joycon->set_dolphin_motion_settings((float)total_yaw->GetValue(), (float)accel_influence->GetValue() / 100.0f,
			(float)gyro_deadzone->GetValue(), (float)calibration_period->GetValue());
	};
	for (auto* spin : {total_yaw, accel_influence, horizontal_fov, vertical_fov, pointer_deadzone, pointer_smoothing, gyro_deadzone, calibration_period})
		spin->Bind(wxEVT_SPINCTRLDOUBLE, apply_live);
	invert_x->Bind(wxEVT_CHECKBOX, apply_live); invert_y->Bind(wxEVT_CHECKBOX, apply_live);

	wxTimer refresh_timer(&dialog);
	dialog.Bind(wxEVT_TIMER, [&](wxTimerEvent&) {
		glm::vec2 live{}, previous{}; joycon->update_joycon_pointer(live, previous);
		pointer_valid = joycon->get_joycon_pointer_debug(pointer_sensor, pointer_target, pointer_output);
		debug_valid = joycon->get_dolphin_motion_debug(debug);
		point_preview->Refresh(false); accel_view->Refresh(false); gyro_view->Refresh(false);
		if (debug_valid)
		{
			const int percent = (int)std::lround(debug.calibration_progress * 100.0f);
			if (debug.calibrated && debug.stable) status->SetLabel(wxString::Format(_("Calibration: READY / STILL | stable mean complete | %.0f Hz"), debug.sample_rate_hz));
			else if (debug.stable) status->SetLabel(wxString::Format(_("Calibration: KEEP STILL %d%% | %.0f Hz"), percent, debug.sample_rate_hz));
			else status->SetLabel(wxString::Format(_("Calibration: MOVING - timer restarted | %.0f Hz"), debug.sample_rate_hz));
			values->SetLabel(wxString::Format(_("Gyro: %+.3f %+.3f %+.3f rad/s | Acc: %+.3f %+.3f %+.3f g | Bias: %+.4f %+.4f %+.4f"),
				debug.gyro.x, debug.gyro.y, debug.gyro.z, debug.accel.x, debug.accel.y, debug.accel.z, debug.bias.x, debug.bias.y, debug.bias.z));
		}
		if (!capture_active) return;
		const auto pressed = joycon->get_pressed_buttons_for_hotkey();
		if (capture_wait_idle) { if (pressed.empty()) { capture_wait_idle = false; recenter_binding->SetLabel(_("Press Recenter button(s), then release...")); } return; }
		if (!pressed.empty()) { recenter_hotkey = pressed; capture_pressed = true; recenter_binding->SetLabel(_("Release to save Recenter...")); }
		else if (capture_pressed) { capture_active = false; capture_pressed = false; recenter_binding->SetLabel(_("Recenter: ") + joycon_hotkey_label(joycon, recenter_hotkey)); }
	}, refresh_timer.GetId());
	refresh_timer.Start(33);

	outer->Add(new wxStaticText(&dialog, wxID_ANY,
		_("Dolphin defaults: Total Yaw 25 degrees | Accelerometer Influence 1% | FOV 42 / 31.5 degrees | Gyro Dead Zone 2 degrees/s | Calibration 3 s | minimum 25 Hz.")),
		0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 8);
	outer->Add(dialog.CreateStdDialogButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
	dialog.SetSizerAndFit(outer);
	dialog.SetMinSize(wxSize(1120, 760));

	if (dialog.ShowModal() == wxID_OK)
	{
		joycon->set_pointer_enabled(enabled->GetValue(), false);
		joycon->set_pointer_recenter_hotkey(std::move(recenter_hotkey));
		joycon->set_joycon_orientation(orientation->GetSelection() == 0 ?
			SDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);
		joycon->set_motion_scale(1.0f, 1.0f, 1.0f);
	}
	else
	{
		joycon->set_pointer_calibration(original_hfov, original_vfov, original_deadzone, original_smoothing, original_invert_x, original_invert_y);
		joycon->set_dolphin_motion_settings(original_total_yaw, original_accel_influence, original_gyro_deadzone, original_calibration_period);
		joycon->set_joycon_orientation(original_orientation, false);
	}
}

'''

panel_cpp.write_text(text[:start] + new_motion_dialog + text[end:], encoding="utf-8")
print(f"Patched {panel_cpp}: Dolphin-organized Motion Input with live pointer, accelerometer, and gyroscope")

print("Applied Cemu V13 exact Dolphin Motion Input settings, raw-unit motion fix, and unified visualizers")
