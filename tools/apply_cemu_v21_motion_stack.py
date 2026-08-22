from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v21_motion_stack.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


def replace_function(path: Path, signature: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"{label}: signature not found")
    brace = text.find("{", start + len(signature))
    if brace < 0:
        raise RuntimeError(f"{label}: opening brace not found")
    depth = 0
    end = None
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise RuntimeError(f"{label}: closing brace not found")
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
    print(f"Patched {path}: {label}")


provider_h = root / "src/input/api/SDL/SDLControllerProvider.h"
provider_cpp = root / "src/input/api/SDL/SDLControllerProvider.cpp"
controller_h = root / "src/input/api/SDL/SDLController.h"
controller_cpp = root / "src/input/api/SDL/SDLController.cpp"
panel_cpp = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"
motion_h = root / "src/input/motion/MotionHandler.h"
mahony_h = root / "src/input/motion/Mahony.h"


# =============================================================================
# V21 architecture
# -----------------------------------------------------------------------------
# V16 is the behavioral baseline. V21 deliberately does NOT add V17/V18/V19/V20
# game-motion routing. Hardware/user testing plus source review exposed one root
# UI bug: the Motion Input choice displayed Sideways and Vertical but stored the
# opposite enum. That prevented the already-proven V15 Joy-Con R Sideways 180
# accelerometer correction from running when the UI said Sideways, and also fed
# Mario Kart/KPAD the Vertical sensor basis while the user believed it was using
# Sideways. Fix the enum/label mismatch first and preserve V16 KPAD exactly.
#
# Gyro is a separate problem: V14/V16 intentionally restored raw game gyro, so
# the Dolphin 2 deg/s + stable-period calibration shown in the UI only calibrated
# the pointer stream. V21 adds a real per-Joy-Con game-gyro stable-mean bias in
# the exact V16 game basis, and bypasses Cemu/Mahony's broad legacy 0.35 rad/s
# bias learner for those already-calibrated Joy-Con samples. Non-Joy-Con motion
# remains completely upstream.
#
# Pointer keeps its proven Dolphin stream, but gets an independent automatic
# calibration period. Both calibrations are per SDL joystick id and all X/Y/Z
# axes are calibrated independently.
# =============================================================================


# -----------------------------------------------------------------------------
# 1) Fix the confirmed Sideways / Vertical UI enum inversion.
# -----------------------------------------------------------------------------
replace_once(
    panel_cpp,
    "\torientation->SetSelection(original_orientation == SDLController::JoyConOrientation::Vertical ? 0 : 1);\n",
    "\t// V21: labels and enum now match 1:1. Sideways=0, Vertical=1.\n"
    "\torientation->SetSelection(original_orientation == SDLController::JoyConOrientation::Vertical ? 1 : 0);\n",
    "fix Motion Input orientation display mapping",
)

replace_once(
    panel_cpp,
    "\t\tjoycon->set_joycon_orientation(orientation->GetSelection() == 0 ?\n"
    "\t\t\tSDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);\n",
    "\t\t// V21: selecting Sideways stores Sideways; selecting Vertical stores Vertical.\n"
    "\t\tjoycon->set_joycon_orientation(orientation->GetSelection() == 0 ?\n"
    "\t\t\tSDLController::JoyConOrientation::Sideways : SDLController::JoyConOrientation::Vertical);\n",
    "fix Motion Input orientation save mapping",
)


# -----------------------------------------------------------------------------
# 2) Separate Pointer calibration period from Game Gyro calibration period.
# -----------------------------------------------------------------------------
replace_once(
    provider_h,
    "\t\tfloat gyro_deadzone_degrees{ 2.0f };\n"
    "\t\tfloat calibration_period_seconds{ 3.0f };\n"
    "\t\tbool stable{};\n",
    "\t\tfloat gyro_deadzone_degrees{ 2.0f };\n"
    "\t\t// Existing fields below describe POINTER calibration in V21.\n"
    "\t\tfloat calibration_period_seconds{ 3.0f };\n"
    "\t\tglm::vec3 game_bias{};\n"
    "\t\tfloat game_calibration_progress{};\n"
    "\t\tfloat game_sample_rate_hz{};\n"
    "\t\tfloat game_calibration_period_seconds{ 3.0f };\n"
    "\t\tbool game_stable{};\n"
    "\t\tbool game_calibrated{};\n"
    "\t\tbool stable{};\n",
    "extend live debug with independent game gyro calibration",
)

replace_once(
    provider_h,
    "\tvoid set_joycon_dolphin_motion_settings(SDL_JoystickID diid, float gyro_deadzone_degrees, float calibration_period_seconds);\n",
    "\tvoid set_joycon_dolphin_motion_settings(SDL_JoystickID diid, float gyro_deadzone_degrees, float calibration_period_seconds);\n"
    "\tvoid set_joycon_pointer_calibration_period(SDL_JoystickID diid, float calibration_period_seconds);\n",
    "declare independent pointer calibration provider setting",
)

replace_once(
    provider_h,
    "\t\tfloat gyro_deadzone_degrees{ 2.0f };\n"
    "\t\tfloat calibration_period_seconds{ 3.0f };\n"
    "\t};\n",
    "\t\tfloat gyro_deadzone_degrees{ 2.0f };\n"
    "\t\t// Game gyro and pointer use separate stable-window timers.\n"
    "\t\tfloat calibration_period_seconds{ 3.0f };\n"
    "\t\tfloat pointer_calibration_period_seconds{ 3.0f };\n"
    "\t};\n",
    "store independent pointer calibration period per Joy-Con",
)

replace_once(
    provider_h,
    "\t\tfloat dolphin_sample_rate_hz{};\n"
    "\t\tglm::vec3 dolphin_motion_gyro{};\n"
    "\t\tglm::vec3 dolphin_motion_acc{};\n\n"
    "\t\tMotionState() = default;\n",
    "\t\tfloat dolphin_sample_rate_hz{};\n"
    "\t\tglm::vec3 dolphin_motion_gyro{};\n"
    "\t\tglm::vec3 dolphin_motion_acc{};\n\n"
    "\t\t// V21 game-gyro calibration state. This is deliberately separate from\n"
    "\t\t// the Dolphin/pointer calibration state above.\n"
    "\t\tglm::vec3 game_gyro_bias{};\n"
    "\t\tglm::vec3 game_calibration_sum{};\n"
    "\t\tuint64 game_calibration_count{};\n"
    "\t\tuint64 game_calibration_start{};\n"
    "\t\tbool game_calibration_stable{};\n"
    "\t\tbool game_calibration_complete{};\n"
    "\t\tfloat game_sample_rate_hz{};\n\n"
    "\t\tMotionState() = default;\n",
    "store independent game gyro calibration state",
)

replace_once(
    controller_h,
    "\tfloat get_dolphin_calibration_period_seconds() const { return m_dolphin_calibration_period_seconds.load(std::memory_order_relaxed); }\n"
    "\tvoid set_dolphin_motion_settings(float total_yaw_degrees, float accel_influence, float gyro_deadzone_degrees, float calibration_period_seconds);\n",
    "\tfloat get_dolphin_calibration_period_seconds() const { return m_dolphin_calibration_period_seconds.load(std::memory_order_relaxed); }\n"
    "\tfloat get_pointer_calibration_period_seconds() const { return m_pointer_calibration_period_seconds.load(std::memory_order_relaxed); }\n"
    "\tvoid set_dolphin_motion_settings(float total_yaw_degrees, float accel_influence, float gyro_deadzone_degrees, float calibration_period_seconds);\n"
    "\tvoid set_pointer_calibration_period_seconds(float calibration_period_seconds);\n",
    "declare independent pointer calibration setting on controller",
)

replace_once(
    controller_h,
    "\tstd::atomic<float> m_dolphin_gyro_deadzone_degrees{ 2.0f };\n"
    "\tstd::atomic<float> m_dolphin_calibration_period_seconds{ 3.0f };\n",
    "\tstd::atomic<float> m_dolphin_gyro_deadzone_degrees{ 2.0f };\n"
    "\t// Game gyro period remains the existing Dolphin-labelled profile field.\n"
    "\tstd::atomic<float> m_dolphin_calibration_period_seconds{ 3.0f };\n"
    "\tstd::atomic<float> m_pointer_calibration_period_seconds{ 3.0f };\n",
    "store independent pointer calibration setting on controller",
)

replace_once(
    provider_cpp,
    "void SDLControllerProvider::clear_joycon_orientation(SDL_JoystickID diid)\n",
    "void SDLControllerProvider::set_joycon_pointer_calibration_period(SDL_JoystickID diid, float calibration_period_seconds)\n"
    "{\n"
    "\tif (diid < 0)\n"
    "\t\treturn;\n\n"
    "\tcalibration_period_seconds = std::clamp(calibration_period_seconds, 0.0f, 30.0f);\n"
    "\tstd::scoped_lock lock(s_mutex);\n"
    "\tauto& config = s_joycon_orientation_states[diid];\n"
    "\tif (config.pointer_calibration_period_seconds != calibration_period_seconds)\n"
    "\t{\n"
    "\t\tconfig.pointer_calibration_period_seconds = calibration_period_seconds;\n"
    "\t\t// Reset both per-device filters so no old basis/bias survives a live setting change.\n"
    "\t\ts_motion_states.erase(diid);\n"
    "\t}\n"
    "}\n\n"
    "void SDLControllerProvider::clear_joycon_orientation(SDL_JoystickID diid)\n",
    "implement independent pointer calibration provider setting",
)

replace_once(
    controller_cpp,
    "void SDLController::get_motion_scale(float& x, float& y, float& z) const\n",
    "void SDLController::set_pointer_calibration_period_seconds(float calibration_period_seconds)\n"
    "{\n"
    "\tcalibration_period_seconds = std::clamp(calibration_period_seconds, 0.0f, 30.0f);\n"
    "\tm_pointer_calibration_period_seconds.store(calibration_period_seconds, std::memory_order_relaxed);\n"
    "\tif (m_diid >= 0)\n"
    "\t\tm_provider->set_joycon_pointer_calibration_period(m_diid, calibration_period_seconds);\n"
    "}\n\n"
    "void SDLController::get_motion_scale(float& x, float& y, float& z) const\n",
    "implement independent pointer calibration controller setting",
)

replace_once(
    controller_cpp,
    "\tnode.append_child(\"joycon_dolphin_calibration_period_s\").append_child(pugi::node_pcdata).set_value(fmt::format(\"{:.3f}\", get_dolphin_calibration_period_seconds()).c_str());\n",
    "\tnode.append_child(\"joycon_dolphin_calibration_period_s\").append_child(pugi::node_pcdata).set_value(fmt::format(\"{:.3f}\", get_dolphin_calibration_period_seconds()).c_str());\n"
    "\tnode.append_child(\"joycon_pointer_calibration_period_s\").append_child(pugi::node_pcdata).set_value(fmt::format(\"{:.3f}\", get_pointer_calibration_period_seconds()).c_str());\n",
    "persist independent pointer calibration period",
)

replace_once(
    controller_cpp,
    "\tfloat calibration_period = 3.0f;\n"
    "\tif (const auto value = node.child(\"joycon_dolphin_total_yaw_deg\")) total_yaw = ConvertString<float>(value.child_value());\n",
    "\tfloat calibration_period = 3.0f;\n"
    "\tfloat pointer_calibration_period = 3.0f;\n"
    "\tif (const auto value = node.child(\"joycon_dolphin_total_yaw_deg\")) total_yaw = ConvertString<float>(value.child_value());\n",
    "declare pointer calibration profile value",
)

replace_once(
    controller_cpp,
    "\tif (const auto value = node.child(\"joycon_dolphin_calibration_period_s\")) calibration_period = ConvertString<float>(value.child_value());\n"
    "\tset_dolphin_motion_settings(total_yaw, accel_influence, gyro_deadzone, calibration_period);\n",
    "\tif (const auto value = node.child(\"joycon_dolphin_calibration_period_s\")) calibration_period = ConvertString<float>(value.child_value());\n"
    "\tif (const auto value = node.child(\"joycon_pointer_calibration_period_s\")) pointer_calibration_period = ConvertString<float>(value.child_value());\n"
    "\tset_dolphin_motion_settings(total_yaw, accel_influence, gyro_deadzone, calibration_period);\n"
    "\tset_pointer_calibration_period_seconds(pointer_calibration_period);\n",
    "load independent pointer calibration profile value",
)

replace_once(
    controller_cpp,
    "\t\tm_provider->set_joycon_dolphin_motion_settings(m_diid,\n"
    "\t\t\tm_dolphin_gyro_deadzone_degrees.load(std::memory_order_relaxed),\n"
    "\t\t\tm_dolphin_calibration_period_seconds.load(std::memory_order_relaxed));\n",
    "\t\tm_provider->set_joycon_dolphin_motion_settings(m_diid,\n"
    "\t\t\tm_dolphin_gyro_deadzone_degrees.load(std::memory_order_relaxed),\n"
    "\t\t\tm_dolphin_calibration_period_seconds.load(std::memory_order_relaxed));\n"
    "\t\tm_provider->set_joycon_pointer_calibration_period(m_diid,\n"
    "\t\t\tm_pointer_calibration_period_seconds.load(std::memory_order_relaxed));\n",
    "initialize provider with independent pointer calibration period",
)


# Pointer's existing stable-mean code now reads the independent pointer period.
replace_once(
    provider_cpp,
    "\t\tdebug.calibration_period_seconds = config->second.calibration_period_seconds;\n",
    "\t\tdebug.calibration_period_seconds = config->second.pointer_calibration_period_seconds;\n"
    "\t\tdebug.game_calibration_period_seconds = config->second.calibration_period_seconds;\n",
    "publish separate pointer and game calibration periods",
)

replace_once(
    provider_cpp,
    "\t\t\t\t\t\tkDolphinCalibrationPeriodNs = static_cast<uint64>(config->second.calibration_period_seconds * 1000000000.0f);\n",
    "\t\t\t\t\t\tkDolphinCalibrationPeriodNs = static_cast<uint64>(config->second.pointer_calibration_period_seconds * 1000000000.0f);\n",
    "drive pointer calibration from independent period",
)

# Do not lock pointer bias to the very first sample; require the configured still window.
replace_once(
    provider_cpp,
    "\t\t\t\t\t\t// Dolphin immediately uses the first observed value as a useful bias\n"
    "\t\t\t\t\t\t// until a full stable calibration period is available.\n"
    "\t\t\t\t\t\tif (!state.dolphin_calibration_initialized)\n"
    "\t\t\t\t\t\t{\n"
    "\t\t\t\t\t\t\tstate.dolphin_gyro_bias = raw_gyro;\n"
    "\t\t\t\t\t\t\tstate.dolphin_calibration_initialized = true;\n"
    "\t\t\t\t\t\t}\n"
    "\t\t\t\t\t\trestart_calibration();\n",
    "\t\t\t\t\t\t// V21: learn pointer bias only from a completed stillness window.\n"
    "\t\t\t\t\t\tstate.dolphin_calibration_initialized = true;\n"
    "\t\t\t\t\t\trestart_calibration();\n",
    "require a real stable window before pointer bias is accepted",
)


# -----------------------------------------------------------------------------
# 3) Add actual GAME gyro calibration in V16's exact game coordinate basis.
# -----------------------------------------------------------------------------
replace_once(
    provider_cpp,
    "\t\t\t\t\t// Exact V9 gyro basis for games. Dolphin's calibrated gyro remains\n"
    "\t\t\t\t\t// isolated above for pointer integration and its stillness visualizer.\n"
    "\t\t\t\t\ttracking.gyro = glm::vec3{\n"
    "\t\t\t\t\t\tv9_game_sensor[0],\n"
    "\t\t\t\t\t\t-v9_game_sensor[1],\n"
    "\t\t\t\t\t\t-v9_game_sensor[2] };\n",
    "\t\t\t\t\t// V21 game gyro: preserve V16's exact physical axes, then calibrate\n"
    "\t\t\t\t\t// a per-Joy-Con bias only after the configured stillness window.\n"
    "\t\t\t\t\tglm::vec3 game_gyro_raw{\n"
    "\t\t\t\t\t\tv9_game_sensor[0],\n"
    "\t\t\t\t\t\t-v9_game_sensor[1],\n"
    "\t\t\t\t\t\t-v9_game_sensor[2] };\n"
    "\t\t\t\t\tconstexpr double kV21MinCalibrationHz = 25.0;\n"
    "\t\t\t\t\tfloat game_deadzone = 2.0f * 3.14159265358979323846f / 180.0f;\n"
    "\t\t\t\t\tuint64 game_period_ns = 3000000000ULL;\n"
    "\t\t\t\t\tif (const auto config = s_joycon_orientation_states.find(id); config != s_joycon_orientation_states.end())\n"
    "\t\t\t\t\t{\n"
    "\t\t\t\t\t\tgame_deadzone = config->second.gyro_deadzone_degrees * 3.14159265358979323846f / 180.0f;\n"
    "\t\t\t\t\t\tgame_period_ns = static_cast<uint64>(config->second.calibration_period_seconds * 1000000000.0f);\n"
    "\t\t\t\t\t}\n"
    "\t\t\t\t\tauto restart_game_calibration = [&]() {\n"
    "\t\t\t\t\t\tstate.game_calibration_start = ts;\n"
    "\t\t\t\t\t\tstate.game_calibration_sum = game_gyro_raw;\n"
    "\t\t\t\t\t\tstate.game_calibration_count = 1;\n"
    "\t\t\t\t\t};\n"
    "\t\t\t\t\tif (game_period_ns == 0)\n"
    "\t\t\t\t\t{\n"
    "\t\t\t\t\t\tstate.game_gyro_bias = {};\n"
    "\t\t\t\t\t\tstate.game_calibration_count = 0;\n"
    "\t\t\t\t\t\tstate.game_calibration_start = 0;\n"
    "\t\t\t\t\t\tstate.game_calibration_stable = true;\n"
    "\t\t\t\t\t\tstate.game_calibration_complete = true;\n"
    "\t\t\t\t\t\tstate.game_sample_rate_hz = 0.0f;\n"
    "\t\t\t\t\t}\n"
    "\t\t\t\t\telse if (state.game_calibration_count == 0)\n"
    "\t\t\t\t\t{\n"
    "\t\t\t\t\t\tstate.game_calibration_stable = false;\n"
    "\t\t\t\t\t\trestart_game_calibration();\n"
    "\t\t\t\t\t}\n"
    "\t\t\t\t\telse\n"
    "\t\t\t\t\t{\n"
    "\t\t\t\t\t\tconst uint64 elapsed_ns = ts - state.game_calibration_start;\n"
    "\t\t\t\t\t\tconst double elapsed_s = static_cast<double>(elapsed_ns) / 1000000000.0;\n"
    "\t\t\t\t\t\tconst glm::vec3 mean = state.game_calibration_sum / static_cast<float>(state.game_calibration_count);\n"
    "\t\t\t\t\t\tconst glm::vec3 difference = game_gyro_raw - mean;\n"
    "\t\t\t\t\t\tconst double frequency = elapsed_s > 0.0 ? static_cast<double>(state.game_calibration_count) / elapsed_s : kV21MinCalibrationHz;\n"
    "\t\t\t\t\t\tstate.game_sample_rate_hz = static_cast<float>(frequency);\n"
    "\t\t\t\t\t\tconst bool unstable = std::abs(difference.x) > game_deadzone ||\n"
    "\t\t\t\t\t\t\tstd::abs(difference.y) > game_deadzone ||\n"
    "\t\t\t\t\t\t\tstd::abs(difference.z) > game_deadzone ||\n"
    "\t\t\t\t\t\t\tfrequency < kV21MinCalibrationHz;\n"
    "\t\t\t\t\t\tstate.game_calibration_stable = !unstable;\n"
    "\t\t\t\t\t\tif (unstable)\n"
    "\t\t\t\t\t\t{\n"
    "\t\t\t\t\t\t\t// Keep the last valid bias while moving; only restart the candidate window.\n"
    "\t\t\t\t\t\t\trestart_game_calibration();\n"
    "\t\t\t\t\t\t}\n"
    "\t\t\t\t\t\telse\n"
    "\t\t\t\t\t\t{\n"
    "\t\t\t\t\t\t\tstate.game_calibration_sum += game_gyro_raw;\n"
    "\t\t\t\t\t\t\t++state.game_calibration_count;\n"
    "\t\t\t\t\t\t\tif (elapsed_ns >= game_period_ns)\n"
    "\t\t\t\t\t\t\t{\n"
    "\t\t\t\t\t\t\t\tstate.game_gyro_bias = state.game_calibration_sum / static_cast<float>(state.game_calibration_count);\n"
    "\t\t\t\t\t\t\t\tstate.game_calibration_complete = true;\n"
    "\t\t\t\t\t\t\t}\n"
    "\t\t\t\t\t\t}\n"
    "\t\t\t\t\t}\n"
    "\t\t\t\t\tglm::vec3 game_gyro = game_gyro_raw - state.game_gyro_bias;\n"
    "\t\t\t\t\tif (std::abs(game_gyro.x) <= game_deadzone) game_gyro.x = 0.0f;\n"
    "\t\t\t\t\tif (std::abs(game_gyro.y) <= game_deadzone) game_gyro.y = 0.0f;\n"
    "\t\t\t\t\tif (std::abs(game_gyro.z) <= game_deadzone) game_gyro.z = 0.0f;\n"
    "\t\t\t\t\ttracking.gyro = game_gyro;\n",
    "calibrate V16 game gyro independently per Joy-Con",
)


# -----------------------------------------------------------------------------
# 4) Extend live debug so the UI proves both calibrations are actually running.
# -----------------------------------------------------------------------------
replace_once(
    provider_cpp,
    "\tdebug.bias = state.dolphin_gyro_bias;\n"
    "\tdebug.sample_rate_hz = state.dolphin_sample_rate_hz;\n",
    "\tdebug.bias = state.dolphin_gyro_bias;\n"
    "\tdebug.game_bias = state.game_gyro_bias;\n"
    "\tdebug.sample_rate_hz = state.dolphin_sample_rate_hz;\n"
    "\tdebug.game_sample_rate_hz = state.game_sample_rate_hz;\n",
    "publish game and pointer biases separately",
)

replace_once(
    provider_cpp,
    "\tdebug.stable = state.dolphin_calibration_stable;\n"
    "\tdebug.calibrated = state.dolphin_calibration_complete;\n",
    "\tdebug.stable = state.dolphin_calibration_stable;\n"
    "\tdebug.calibrated = state.dolphin_calibration_complete;\n"
    "\tdebug.game_stable = state.game_calibration_stable;\n"
    "\tdebug.game_calibrated = state.game_calibration_complete;\n",
    "publish game and pointer calibration state separately",
)

replace_once(
    provider_cpp,
    "\tif (state.dolphin_calibration_start != 0 && debug.timestamp >= state.dolphin_calibration_start &&\n"
    "\t\tdebug.calibration_period_seconds > 0.0f)\n"
    "\t{\n"
    "\t\tconst float period_ns = debug.calibration_period_seconds * 1000000000.0f;\n"
    "\t\tconst float elapsed = static_cast<float>(debug.timestamp - state.dolphin_calibration_start) / period_ns;\n"
    "\t\tdebug.calibration_progress = std::clamp(elapsed, 0.0f, 1.0f);\n"
    "\t}\n"
    "\treturn debug.timestamp != 0;\n",
    "\tif (state.dolphin_calibration_start != 0 && debug.timestamp >= state.dolphin_calibration_start &&\n"
    "\t\tdebug.calibration_period_seconds > 0.0f)\n"
    "\t{\n"
    "\t\tconst float period_ns = debug.calibration_period_seconds * 1000000000.0f;\n"
    "\t\tconst float elapsed = static_cast<float>(debug.timestamp - state.dolphin_calibration_start) / period_ns;\n"
    "\t\tdebug.calibration_progress = std::clamp(elapsed, 0.0f, 1.0f);\n"
    "\t}\n"
    "\tif (state.game_calibration_start != 0 && debug.timestamp >= state.game_calibration_start &&\n"
    "\t\tdebug.game_calibration_period_seconds > 0.0f)\n"
    "\t{\n"
    "\t\tconst float period_ns = debug.game_calibration_period_seconds * 1000000000.0f;\n"
    "\t\tconst float elapsed = static_cast<float>(debug.timestamp - state.game_calibration_start) / period_ns;\n"
    "\t\tdebug.game_calibration_progress = std::clamp(elapsed, 0.0f, 1.0f);\n"
    "\t}\n"
    "\treturn debug.timestamp != 0;\n",
    "publish independent game calibration progress",
)


# -----------------------------------------------------------------------------
# 5) Pointer UI: independent automatic calibration period and status.
# -----------------------------------------------------------------------------
replace_once(
    panel_cpp,
    "\tconst float original_calibration_period = joycon->get_dolphin_calibration_period_seconds();\n"
    "\tconst auto original_orientation = joycon->get_joycon_orientation();\n",
    "\tconst float original_calibration_period = joycon->get_dolphin_calibration_period_seconds();\n"
    "\tconst float original_pointer_calibration_period = joycon->get_pointer_calibration_period_seconds();\n"
    "\tconst auto original_orientation = joycon->get_joycon_orientation();\n",
    "capture pointer calibration period when opening dialog",
)

replace_once(
    panel_cpp,
    "\tauto* pointer_smoothing = add_point_setting(_(\"Smooth (0 = direct)\"), original_smoothing, 0.0, 0.95, 0.01, 2);\n"
    "\tpoint_box->Add(point_grid, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);\n",
    "\tauto* pointer_smoothing = add_point_setting(_(\"Smooth (0 = direct)\"), original_smoothing, 0.0, 0.95, 0.01, 2);\n"
    "\tauto* pointer_calibration_period = add_point_setting(_(\"Pointer Calibration Period (s)\"), original_pointer_calibration_period, 0.0, 30.0, 0.25, 2);\n"
    "\tpoint_box->Add(point_grid, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);\n",
    "add independent pointer calibration period control",
)

replace_once(
    panel_cpp,
    "\tpoint_box->Add(recenter_binding, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);\n"
    "\tgroups->Add(point_box, 1, wxEXPAND | wxRIGHT, 6);\n",
    "\tpoint_box->Add(recenter_binding, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);\n"
    "\tauto* pointer_calibration_status = new wxStaticText(&dialog, wxID_ANY, _(\"Pointer Calibration: waiting for sensor\"));\n"
    "\tpoint_box->Add(pointer_calibration_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 6);\n"
    "\tgroups->Add(point_box, 1, wxEXPAND | wxRIGHT, 6);\n",
    "add live pointer calibration status",
)

replace_once(
    panel_cpp,
    "\t\tjoycon->set_dolphin_motion_settings((float)total_yaw->GetValue(), (float)accel_influence->GetValue() / 100.0f,\n"
    "\t\t\t(float)gyro_deadzone->GetValue(), (float)calibration_period->GetValue());\n"
    "\t};\n"
    "\tfor (auto* spin : {total_yaw, accel_influence, horizontal_fov, vertical_fov, pointer_deadzone, pointer_smoothing, gyro_deadzone, calibration_period})\n",
    "\t\tjoycon->set_dolphin_motion_settings((float)total_yaw->GetValue(), (float)accel_influence->GetValue() / 100.0f,\n"
    "\t\t\t(float)gyro_deadzone->GetValue(), (float)calibration_period->GetValue());\n"
    "\t\tjoycon->set_pointer_calibration_period_seconds((float)pointer_calibration_period->GetValue());\n"
    "\t};\n"
    "\tfor (auto* spin : {total_yaw, accel_influence, horizontal_fov, vertical_fov, pointer_deadzone, pointer_smoothing, pointer_calibration_period, gyro_deadzone, calibration_period})\n",
    "apply and bind independent pointer calibration setting live",
)

replace_once(
    panel_cpp,
    "\t\tif (debug_valid)\n"
    "\t\t{\n"
    "\t\t\tconst int percent = (int)std::lround(debug.calibration_progress * 100.0f);\n"
    "\t\t\tif (debug.calibrated && debug.stable) status->SetLabel(wxString::Format(_(\"Calibration: READY / STILL | stable mean complete | %.0f Hz\"), debug.sample_rate_hz));\n"
    "\t\t\telse if (debug.stable) status->SetLabel(wxString::Format(_(\"Calibration: KEEP STILL %d%% | %.0f Hz\"), percent, debug.sample_rate_hz));\n"
    "\t\t\telse status->SetLabel(wxString::Format(_(\"Calibration: MOVING - timer restarted | %.0f Hz\"), debug.sample_rate_hz));\n"
    "\t\t\tvalues->SetLabel(wxString::Format(_(\"Gyro: %+.3f %+.3f %+.3f rad/s | Acc: %+.3f %+.3f %+.3f g | Bias: %+.4f %+.4f %+.4f\"),\n"
    "\t\t\t\tdebug.gyro.x, debug.gyro.y, debug.gyro.z, debug.accel.x, debug.accel.y, debug.accel.z, debug.bias.x, debug.bias.y, debug.bias.z));\n"
    "\t\t}\n",
    "\t\tif (debug_valid)\n"
    "\t\t{\n"
    "\t\t\tconst int pointer_percent = (int)std::lround(debug.calibration_progress * 100.0f);\n"
    "\t\t\tif (debug.calibrated && debug.stable) pointer_calibration_status->SetLabel(wxString::Format(_(\"Pointer Calibration: READY / STILL | %.0f Hz\"), debug.sample_rate_hz));\n"
    "\t\t\telse if (debug.stable) pointer_calibration_status->SetLabel(wxString::Format(_(\"Pointer Calibration: KEEP STILL %d%% | %.0f Hz\"), pointer_percent, debug.sample_rate_hz));\n"
    "\t\t\telse pointer_calibration_status->SetLabel(wxString::Format(_(\"Pointer Calibration: MOVING - timer restarted | %.0f Hz\"), debug.sample_rate_hz));\n"
    "\n"
    "\t\t\tconst int game_percent = (int)std::lround(debug.game_calibration_progress * 100.0f);\n"
    "\t\t\tif (debug.game_calibrated && debug.game_stable) status->SetLabel(wxString::Format(_(\"Game Gyro Calibration: READY / STILL | %.0f Hz\"), debug.game_sample_rate_hz));\n"
    "\t\t\telse if (debug.game_stable) status->SetLabel(wxString::Format(_(\"Game Gyro Calibration: KEEP STILL %d%% | %.0f Hz\"), game_percent, debug.game_sample_rate_hz));\n"
    "\t\t\telse status->SetLabel(wxString::Format(_(\"Game Gyro Calibration: MOVING - timer restarted | %.0f Hz\"), debug.game_sample_rate_hz));\n"
    "\n"
    "\t\t\tvalues->SetLabel(wxString::Format(_(\"Gyro: %+.3f %+.3f %+.3f rad/s | Acc: %+.3f %+.3f %+.3f g | Game Bias: %+.4f %+.4f %+.4f | Pointer Bias: %+.4f %+.4f %+.4f\"),\n"
    "\t\t\t\tdebug.gyro.x, debug.gyro.y, debug.gyro.z, debug.accel.x, debug.accel.y, debug.accel.z,\n"
    "\t\t\t\tdebug.game_bias.x, debug.game_bias.y, debug.game_bias.z, debug.bias.x, debug.bias.y, debug.bias.z));\n"
    "\t\t}\n",
    "show independent game and pointer calibration live status",
)

replace_once(
    panel_cpp,
    "\t\t_(\"Dolphin defaults: Total Yaw 25 degrees | Accelerometer Influence 1% | FOV 42 / 31.5 degrees | Gyro Dead Zone 2 degrees/s | Calibration 3 s | minimum 25 Hz.\")),\n",
    "\t\t_(\"V21 defaults: Total Yaw 25 degrees | Accelerometer Influence 1% | FOV 42 / 31.5 degrees | Gyro Dead Zone 2 degrees/s | Game Gyro Calibration 3 s | Pointer Calibration 3 s | minimum 25 Hz.\")),\n",
    "describe split V21 calibration defaults",
)

replace_once(
    panel_cpp,
    "\t\tjoycon->set_dolphin_motion_settings(original_total_yaw, original_accel_influence, original_gyro_deadzone, original_calibration_period);\n"
    "\t\tjoycon->set_joycon_orientation(original_orientation, false);\n",
    "\t\tjoycon->set_dolphin_motion_settings(original_total_yaw, original_accel_influence, original_gyro_deadzone, original_calibration_period);\n"
    "\t\tjoycon->set_pointer_calibration_period_seconds(original_pointer_calibration_period);\n"
    "\t\tjoycon->set_joycon_orientation(original_orientation, false);\n",
    "restore pointer calibration setting when dialog is cancelled",
)


# -----------------------------------------------------------------------------
# 6) Joy-Con gyro is already externally calibrated in V21. Bypass Mahony's
#    broad legacy bias learner ONLY for that path so slow intended rotation is
#    never re-learned as bias a second time.
# -----------------------------------------------------------------------------
replace_function(
    mahony_h,
    "\tvoid updateIMU(float deltaTime, float gx, float gy, float gz, float ax, float ay, float az)\n",
    '''\tvoid updateIMU(float deltaTime, float gx, float gy, float gz, float ax, float ay, float az)\n\t{\n\t\tupdateIMUInternal(deltaTime, gx, gy, gz, ax, ay, az, true);\n\t}\n\n\t// V21: input gyro has already been debiased by the per-Joy-Con stable mean.\n\tvoid updateIMUCalibrated(float deltaTime, float gx, float gy, float gz, float ax, float ay, float az)\n\t{\n\t\tupdateIMUInternal(deltaTime, gx, gy, gz, ax, ay, az, false);\n\t}\n''',
    "split Mahony raw and externally-calibrated update entry points",
)

replace_once(
    mahony_h,
    "private:\n\n\t// calculate roll, yaw and pitch in radians. (-0.5 to 0.5)\n",
    '''private:\n\n\tvoid updateIMUInternal(float deltaTime, float gx, float gy, float gz, float ax, float ay, float az, bool learn_internal_bias)\n\t{\n\t\tVector3f av(ax, ay, az);\n\t\tVector3f gv(gx, gy, gz);\n\t\tif (deltaTime > 0.2f)\n\t\t\tdeltaTime = 0.2f;\n\t\tif (learn_internal_bias)\n\t\t{\n\t\t\tupdateGyroBias(gx, gy, gz);\n\t\t\tgv.x -= m_gyroBias[0];\n\t\t\tgv.y -= m_gyroBias[1];\n\t\t\tgv.z -= m_gyroBias[2];\n\t\t}\n\n\t\t// Preserve upstream Cemu's small-angle protection. V21's configurable\n\t\t// Joy-Con deadzone has already run before the calibrated entry point.\n\t\tif (fabs(gv.x) < 0.015f)\n\t\t\tgv.x = 0.0f;\n\t\tif (fabs(gv.y) < 0.015f)\n\t\t\tgv.y = 0.0f;\n\t\tif (fabs(gv.z) < 0.015f)\n\t\t\tgv.z = 0.0f;\n\n\t\tif (fabs(av.x) > 0.000001f || fabs(av.y) > 0.000001f || fabs(av.z) > 0.000001f)\n\t\t{\n\t\t\tav.Normalize();\n\t\t\tVector3f grav = m_imuQ.GetVectorZ();\n\t\t\tgrav.Scale(0.5f);\n\t\t\tVector3f errorFeedback = grav.Cross(av);\n\t\t\tgv -= errorFeedback;\n\t\t}\n\t\tgv.Scale(0.5f * deltaTime);\n\t\tm_imuQ += (m_imuQ * Quaternionf(0.0f, gv.x, gv.y, gv.z));\n\t\tm_imuQ.NormalizeXYZW();\n\t\tupdateOrientationAngles();\n\t}\n\n\t// calculate roll, yaw and pitch in radians. (-0.5 to 0.5)\n''',
    "add shared Mahony implementation with optional internal bias learner",
)

replace_once(
    motion_h,
    "\tMotionSample getMotionSample()\n",
    '''\t// V21 Joy-Con path: provider already performed per-device gyro calibration.\n\tvoid processCalibratedMotionSample(\n\t\tfloat deltaTime,\n\t\tfloat gx, float gy, float gz,\n\t\tfloat accx, float accy, float accz)\n\t{\n\t\tm_gyro[0] = gx;\n\t\tm_gyro[1] = gy;\n\t\tm_gyro[2] = gz;\n\t\tm_prevAcc[0] = m_acc[0];\n\t\tm_prevAcc[1] = m_acc[1];\n\t\tm_prevAcc[2] = m_acc[2];\n\t\tm_acc[0] = accx;\n\t\tm_acc[1] = accy;\n\t\tm_acc[2] = accz;\n\t\tm_imu.updateIMUCalibrated(deltaTime, gx, gy, gz, accx, accy, accz);\n\n\t\tm_orientation[0] = _radToOrientation(-m_imu.getYawRadians()) - 0.50f;\n\t\tm_orientation[1] = _radToOrientation(-m_imu.getPitchRadians()) - 0.50f;\n\t\tm_orientation[2] = _radToOrientation(m_imu.getRollRadians());\n\t}\n\n\tMotionSample getMotionSample()\n''',
    "add calibrated Joy-Con motion handler entry point",
)

replace_once(
    provider_cpp,
    "\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n",
    "\t\t\t\t\tif (s_joycon_orientation_states.contains(id))\n"
    "\t\t\t\t\t\tstate.handler.processCalibratedMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n"
    "\t\t\t\t\telse\n"
    "\t\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n",
    "bypass legacy Mahony bias learner only for calibrated Joy-Con gyro",
)


print("Applied V21 motion-stack fix: correct orientation labels, preserved V15/V16 accel+KPAD, independent game gyro and pointer auto-calibration")
