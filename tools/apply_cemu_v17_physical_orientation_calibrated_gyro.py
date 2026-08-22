from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v17_physical_orientation_calibrated_gyro.py <cemu-source-root>")

root = Path(sys.argv[1])
provider_h = root / "src/input/api/SDL/SDLControllerProvider.h"
provider_cpp = root / "src/input/api/SDL/SDLControllerProvider.cpp"
controller_cpp = root / "src/input/api/SDL/SDLController.cpp"
panel_cpp = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V16 calibrated only the Dolphin pointer stream. The exact Cemu/V9 game stream
# still received raw angular velocity, creating visible drift and jitter. Keep
# its known-good axis basis, but apply Dolphin's stable-mean bias and per-axis
# deadzone before it reaches WiiUMotionHandler.
replace_once(
    provider_h,
    '''\t\tfloat dolphin_sample_rate_hz{};\n\t\tglm::vec3 dolphin_motion_gyro{};\n\t\tglm::vec3 dolphin_motion_acc{};\n''',
    '''\t\tfloat dolphin_sample_rate_hz{};\n\t\t// V17 game-motion calibration is intentionally separate from the pre-orientation\n\t\t// pointer calibration. It preserves Cemu's game axis contract while removing\n\t\t// the Joy-Con gyro bias before data reaches KPAD/MotionPlus.\n\t\tglm::vec3 dolphin_game_gyro_bias{};\n\t\tglm::vec3 dolphin_game_calibration_sum{};\n\t\tuint64 dolphin_game_calibration_count{};\n\t\tuint64 dolphin_game_calibration_start{};\n\t\tbool dolphin_game_calibration_initialized{};\n\t\tglm::vec3 dolphin_motion_gyro{};\n\t\tglm::vec3 dolphin_motion_acc{};\n''',
    "add independent calibrated Cemu game-gyro state",
)

replace_once(
    provider_cpp,
    '''\t\t\t\t\tstate.dolphin_pointer_gyro = dolphin_gyro;\n\t\t\t\t\tstate.dolphin_pointer_timestamp = ts;\n\t\t\t\t\tstate.dolphin_pointer_has_gyro = true;\n\t\t\t\t\t// Exact V9 gyro basis for games. Dolphin's calibrated gyro remains\n\t\t\t\t\t// isolated above for pointer integration and its stillness visualizer.\n\t\t\t\t\ttracking.gyro = glm::vec3{\n\t\t\t\t\t\tv9_game_sensor[0],\n\t\t\t\t\t\t-v9_game_sensor[1],\n\t\t\t\t\t\t-v9_game_sensor[2] };\n''',
    '''\t\t\t\t\tstate.dolphin_pointer_gyro = dolphin_gyro;\n\t\t\t\t\tstate.dolphin_pointer_timestamp = ts;\n\t\t\t\t\tstate.dolphin_pointer_has_gyro = true;\n\n\t\t\t\t\t// V17: preserve the V9/Cemu game axis contract, but calibrate this\n\t\t\t\t\t// actual game stream with Dolphin's 3-second stable running mean.\n\t\t\t\t\t// V14/V16 sent this raw vector directly, which is the source of drift.\n\t\t\t\t\tconst glm::vec3 raw_game_gyro{\n\t\t\t\t\t\tv9_game_sensor[0],\n\t\t\t\t\t\t-v9_game_sensor[1],\n\t\t\t\t\t\t-v9_game_sensor[2] };\n\t\t\t\t\tauto restart_game_calibration = [&]() {\n\t\t\t\t\t\tstate.dolphin_game_calibration_start = ts;\n\t\t\t\t\t\tstate.dolphin_game_calibration_sum = raw_game_gyro;\n\t\t\t\t\t\tstate.dolphin_game_calibration_count = 1;\n\t\t\t\t\t};\n\t\t\t\t\tif (kDolphinCalibrationPeriodNs == 0)\n\t\t\t\t\t{\n\t\t\t\t\t\tstate.dolphin_game_gyro_bias = {};\n\t\t\t\t\t\tstate.dolphin_game_calibration_count = 0;\n\t\t\t\t\t}\n\t\t\t\t\telse if (state.dolphin_game_calibration_count == 0)\n\t\t\t\t\t{\n\t\t\t\t\t\tif (!state.dolphin_game_calibration_initialized)\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\tstate.dolphin_game_gyro_bias = raw_game_gyro;\n\t\t\t\t\t\t\tstate.dolphin_game_calibration_initialized = true;\n\t\t\t\t\t\t}\n\t\t\t\t\t\trestart_game_calibration();\n\t\t\t\t\t}\n\t\t\t\t\telse\n\t\t\t\t\t{\n\t\t\t\t\t\tconst uint64 elapsed_ns = ts - state.dolphin_game_calibration_start;\n\t\t\t\t\t\tconst double elapsed_s = static_cast<double>(elapsed_ns) / 1000000000.0;\n\t\t\t\t\t\tconst glm::vec3 mean = state.dolphin_game_calibration_sum / static_cast<float>(state.dolphin_game_calibration_count);\n\t\t\t\t\t\tconst glm::vec3 difference = raw_game_gyro - mean;\n\t\t\t\t\t\tconst double frequency = elapsed_s > 0.0 ? static_cast<double>(state.dolphin_game_calibration_count) / elapsed_s : kDolphinMinCalibrationHz;\n\t\t\t\t\t\tconst bool unstable = std::abs(difference.x) > kDolphinGyroDeadzone ||\n\t\t\t\t\t\t\tstd::abs(difference.y) > kDolphinGyroDeadzone ||\n\t\t\t\t\t\t\tstd::abs(difference.z) > kDolphinGyroDeadzone ||\n\t\t\t\t\t\t\tfrequency < kDolphinMinCalibrationHz;\n\t\t\t\t\t\tif (unstable)\n\t\t\t\t\t\t\trestart_game_calibration();\n\t\t\t\t\t\telse\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\tstate.dolphin_game_calibration_sum += raw_game_gyro;\n\t\t\t\t\t\t\t++state.dolphin_game_calibration_count;\n\t\t\t\t\t\t\tif (elapsed_ns >= kDolphinCalibrationPeriodNs)\n\t\t\t\t\t\t\t\tstate.dolphin_game_gyro_bias = state.dolphin_game_calibration_sum / static_cast<float>(state.dolphin_game_calibration_count);\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t\tglm::vec3 game_gyro = raw_game_gyro - state.dolphin_game_gyro_bias;\n\t\t\t\t\tif (std::abs(game_gyro.x) <= kDolphinGyroDeadzone) game_gyro.x = 0.0f;\n\t\t\t\t\tif (std::abs(game_gyro.y) <= kDolphinGyroDeadzone) game_gyro.y = 0.0f;\n\t\t\t\t\tif (std::abs(game_gyro.z) <= kDolphinGyroDeadzone) game_gyro.z = 0.0f;\n\t\t\t\t\ttracking.gyro = game_gyro;\n''',
    "calibrate V9/Cemu game gyro before KPAD delivery",
)

replace_once(
    provider_cpp,
    '''\tdebug.bias = state.dolphin_gyro_bias;\n''',
    '''\tdebug.bias = state.dolphin_game_gyro_bias;\n''',
    "show game-stream gyro bias in live dialog",
)

# The selector had been deliberately inverted to preserve an old profile quirk:
# its visible Vertical label actually selected internal Sideways. That is why
# the user's physical R orientation and the accelerometer drawing disagreed.
# V17 makes the native labels truthful in both the compact panel and dialog.
replace_once(
    panel_cpp,
    '''\t// Internal Vertical == physical Sideways; internal Sideways == physical Vertical.\n\tconst int selection = joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 0 : 1;\n''',
    '''\t// V17: labels now match the physical transform they select.\n\tconst int selection = joycon->get_joycon_orientation() == SDLController::JoyConOrientation::Vertical ? 1 : 0;\n''',
    "make compact orientation label truthful",
)

replace_once(
    panel_cpp,
    '''\t\tjoycon->set_joycon_orientation(m_joycon_orientation->GetSelection() == 1 ? SDLController::JoyConOrientation::Sideways : SDLController::JoyConOrientation::Vertical);\n''',
    '''\t\tjoycon->set_joycon_orientation(m_joycon_orientation->GetSelection() == 1 ? SDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);\n''',
    "make compact orientation selection truthful",
)

replace_once(
    panel_cpp,
    '''\torientation->SetSelection(original_orientation == SDLController::JoyConOrientation::Vertical ? 0 : 1);\n''',
    '''\torientation->SetSelection(original_orientation == SDLController::JoyConOrientation::Vertical ? 1 : 0);\n''',
    "make dialog orientation label truthful",
)

replace_once(
    panel_cpp,
    '''\t\tjoycon->set_joycon_orientation(orientation->GetSelection() == 0 ?\n\t\t\tSDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);\n''',
    '''\t\tjoycon->set_joycon_orientation(orientation->GetSelection() == 1 ?\n\t\t\tSDLController::JoyConOrientation::Vertical : SDLController::JoyConOrientation::Sideways);\n''',
    "make dialog orientation selection truthful",
)

# V5/V6 also carried the old inversion beneath the UI: the enum sent to the
# sensor provider, button transform, and hotkeys was opposite to its name.
# Correct every layer together, otherwise a truthful "Vertical" label would
# still produce Sideways accelerometer / gyro data.
replace_once(
    controller_cpp,
    '''\t\t// V5 user semantics: internal Sideways == physical Vertical.\n\t\tconst bool physical_vertical = orientation == JoyConOrientation::Sideways;\n''',
    '''\t\t// V17: the stored enum and the physical sensor orientation agree.\n\t\tconst bool physical_vertical = orientation == JoyConOrientation::Vertical;\n''',
    "send truthful physical orientation to motion provider",
)

replace_once(
    controller_cpp,
    '''\t\t// Internal Vertical is the physical Sideways transform and vice versa.\n\t\tconst char* mode = orientation == JoyConOrientation::Vertical ? "Sideways" : "Vertical";\n''',
    '''\t\tconst char* mode = orientation == JoyConOrientation::Vertical ? "Vertical" : "Sideways";\n''',
    "make orientation OSD truthful",
)

replace_once(
    controller_cpp,
    '''\t\t// V5 user semantics: internal Sideways == physical Vertical.\n\t\tconst bool physical_vertical = get_joycon_orientation() == JoyConOrientation::Sideways;\n''',
    '''\t\t// V17: restore the selected physical orientation after reconnecting.\n\t\tconst bool physical_vertical = get_joycon_orientation() == JoyConOrientation::Vertical;\n''',
    "restore truthful physical orientation on reconnect",
)

replace_once(
    controller_cpp,
    '''\t\t// The internal transform enum is opposite to the physical Joy-Con\n\t\t// orientation because SDL is permanently kept in mini-gamepad mode.\n\t\tif (vertical_pressed && !m_vertical_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Sideways);\n\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n''',
    '''\t\tif (vertical_pressed && !m_vertical_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Vertical);\n\t\tif (sideways_pressed && !m_sideways_hotkey_latched)\n\t\t\tset_joycon_orientation(JoyConOrientation::Sideways);\n''',
    "make physical orientation hotkeys truthful",
)

replace_once(
    controller_cpp,
    '''\t\t// SDL already exposes a separate Joy-Con as a horizontal mini-gamepad.\n\t\t// Rotate controls only when the USER is physically holding it Vertical.\n\t\tif (get_joycon_orientation() == JoyConOrientation::Sideways)\n\t\t\tapply_vertical_transform(result);\n''',
    '''\t\t// Rotate controls only when the selected physical orientation is Vertical.\n\t\tif (get_joycon_orientation() == JoyConOrientation::Vertical)\n\t\t\tapply_vertical_transform(result);\n''',
    "apply control transform in actual Vertical orientation",
)

print("Applied Cemu V17 physical orientation labels and calibrated game gyro")
