from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v14_v9_game_motion.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
panel_h = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.h"
panel_cpp = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"


# V10 accidentally fed Dolphin binding-semantic axes directly into Cemu's
# WiiUMotionHandler. Keep that semantic stream only for the proven pointer, and
# build a second game stream using the exact V9/V6/V7 Cemu sensor basis.
replace_once(
    provider,
    '''\t\t\tbool v10_is_joycon = false;\n\t\t\tbool v10_left_sideways = false;\n\t\t\tbool v10_right_sideways = false;\n\t\t\tfloat v10_native[3] = { sensor_data[0], sensor_data[1], sensor_data[2] };\n''',
    '''\t\t\tbool v10_is_joycon = false;\n\t\t\tfloat v10_native[3] = { sensor_data[0], sensor_data[1], sensor_data[2] };\n\t\t\t// V14 split stream: V10 native/Dolphin semantics above are pointer-only.\n\t\t\t// The game stream below is the last known-good V9/V6/V7 Cemu basis.\n\t\t\tfloat v9_game_sensor[3] = { sensor_data[0], sensor_data[1], sensor_data[2] };\n''',
    "declare independent V9 game-motion sensor stream",
)

replace_once(
    provider,
    '''\t\t\t\tv10_left_sideways = config->second.is_left && !config->second.vertical;\n\t\t\t\tv10_right_sideways = !config->second.is_left && !config->second.vertical;\n''',
    "",
    "remove obsolete Dolphin orientation flags from game stream",
)

replace_once(
    provider,
    '''\t\t\t\telse\n\t\t\t\t{\n\t\t\t\t\t// Inverse of SDL R mini mapping: native -> (-z,y,x).\n\t\t\t\t\tv10_native[0] = z;\n\t\t\t\t\tv10_native[1] = y;\n\t\t\t\t\tv10_native[2] = -x;\n\t\t\t\t}\n\t\t\t}\n\n\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)\n''',
    '''\t\t\t\telse\n\t\t\t\t{\n\t\t\t\t\t// Inverse of SDL R mini mapping: native -> (-z,y,x).\n\t\t\t\t\tv10_native[0] = z;\n\t\t\t\t\tv10_native[1] = y;\n\t\t\t\t\tv10_native[2] = -x;\n\t\t\t\t}\n\n\t\t\t\t// Exact V9 physical-orientation transform for game/KPAD motion.\n\t\t\t\t// Sideways stays in SDL mini-gamepad coordinates. Vertical applies\n\t\t\t\t// one clean +/-90 degree Y rotation, with no Dolphin axis reorder.\n\t\t\t\tif (config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\tif (config->second.is_left)\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = -z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = x;\n\t\t\t\t\t}\n\t\t\t\t\telse\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = -x;\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\n\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)\n''',
    "restore exact V9 physical Sideways/Vertical game basis",
)

replace_once(
    provider,
    '''\t\t\t\t\tstate.dolphin_pointer_acc = dolphin_acc;\n\t\t\t\t\tstate.dolphin_pointer_has_acc = true;\n\t\t\t\t\t// Dolphin output orientation is applied AFTER the pointer stream is captured.\n\t\t\t\t\t// L Sideways: stock Dolphin RotateZ(-90 degrees): (x,y)->(y,-x).\n\t\t\t\t\t// R Sideways: user's proven custom RotateZ(180 degrees): (x,y)->(-x,-y).\n\t\t\t\t\tif (v10_left_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tconst float old_x = dolphin_acc.x;\n\t\t\t\t\t\tdolphin_acc.x = dolphin_acc.y;\n\t\t\t\t\t\tdolphin_acc.y = -old_x;\n\t\t\t\t\t}\n\t\t\t\t\telse if (v10_right_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tdolphin_acc.x = -dolphin_acc.x;\n\t\t\t\t\t\tdolphin_acc.y = -dolphin_acc.y;\n\t\t\t\t\t}\n\t\t\t\t\ttracking.acc = dolphin_acc;\n''',
    '''\t\t\t\t\tstate.dolphin_pointer_acc = dolphin_acc;\n\t\t\t\t\tstate.dolphin_pointer_has_acc = true;\n\t\t\t\t\t// Game motion is deliberately NOT Dolphin-oriented. Reproduce V9's\n\t\t\t\t\t// Cemu tracking vector; the adapter's historical Y/Z signs are applied\n\t\t\t\t\t// at processMotionSample below. Pointer remains pre-orientation.\n\t\t\t\t\ttracking.acc = glm::vec3{\n\t\t\t\t\t\t-v9_game_sensor[0] / 9.81f,\n\t\t\t\t\t\t-v9_game_sensor[1] / 9.81f,\n\t\t\t\t\t\t-v9_game_sensor[2] / 9.81f };\n''',
    "keep Dolphin accelerometer pointer stream and restore V9 game stream",
)

replace_once(
    provider,
    '''\t\t\t\t\tstate.dolphin_pointer_gyro = dolphin_gyro;\n\t\t\t\t\tstate.dolphin_pointer_timestamp = ts;\n\t\t\t\t\tstate.dolphin_pointer_has_gyro = true;\n\t\t\t\t\tif (v10_left_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tconst float old_x = dolphin_gyro.x;\n\t\t\t\t\t\tdolphin_gyro.x = dolphin_gyro.y;\n\t\t\t\t\t\tdolphin_gyro.y = -old_x;\n\t\t\t\t\t}\n\t\t\t\t\telse if (v10_right_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tdolphin_gyro.x = -dolphin_gyro.x;\n\t\t\t\t\t\tdolphin_gyro.y = -dolphin_gyro.y;\n\t\t\t\t\t}\n\t\t\t\t\ttracking.gyro = dolphin_gyro;\n''',
    '''\t\t\t\t\tstate.dolphin_pointer_gyro = dolphin_gyro;\n\t\t\t\t\tstate.dolphin_pointer_timestamp = ts;\n\t\t\t\t\tstate.dolphin_pointer_has_gyro = true;\n\t\t\t\t\t// Exact V9 gyro basis for games. Dolphin's calibrated gyro remains\n\t\t\t\t\t// isolated above for pointer integration and its stillness visualizer.\n\t\t\t\t\ttracking.gyro = glm::vec3{\n\t\t\t\t\t\tv9_game_sensor[0],\n\t\t\t\t\t\t-v9_game_sensor[1],\n\t\t\t\t\t\t-v9_game_sensor[2] };\n''',
    "keep Dolphin gyro pointer calibration and restore V9 game gyro",
)

replace_once(
    provider,
    '''\t\t\t\t// Dolphin direct sensor semantics use calibrated raw units. Legacy V8-V12\n\t\t\t\t// scale values must not amplify gravity or angular velocity.\n\t\t\t\tstate.dolphin_motion_acc = tracking.acc;\n\t\t\t\tstate.dolphin_motion_gyro = tracking.gyro;\n''',
    '''\t\t\t\t// Live game-motion view shows the exact values delivered to Cemu/KPAD.\n\t\t\t\t// The pointer debug view remains the independent Dolphin stream.\n\t\t\t\tstate.dolphin_motion_acc = glm::vec3{ tracking.acc.x, -tracking.acc.y, -tracking.acc.z };\n\t\t\t\tstate.dolphin_motion_gyro = tracking.gyro;\n''',
    "show exact V9 game-motion vectors in the live view",
)

replace_once(
    provider,
    '''\t\t\t\t\tif (s_joycon_orientation_states.contains(id))\n\t\t\t\t\t\tstate.handler.processDolphinMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, tracking.acc.y, tracking.acc.z);\n\t\t\t\t\telse\n\t\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n''',
    '''\t\t\t\t\t// V14: all game motion uses Cemu's proven V9 adapter contract. Never\n\t\t\t\t\t// feed Dolphin binding-semantic axes directly into WiiUMotionHandler.\n\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n''',
    "route Joy-Con game motion through exact V9 Cemu adapter",
)


# Remove the redundant standalone Pointer... entry shown in the user's screenshot.
# The complete Point UI and live pointer indicator remain inside Motion Input....
replace_once(
    panel_h,
    '''\twxButton* m_joycon_pointer_dialog = nullptr;\n''',
    "",
    "remove external Pointer dialog button member",
)

replace_once(
    panel_cpp,
    '''\tm_joycon_pointer_dialog = new wxButton(m_joycon_panel, wxID_ANY, _("Pointer..."));\n\tm_joycon_motion_dialog = new wxButton(m_joycon_panel, wxID_ANY, _("Motion Input..."));\n\tm_joycon_pointer_dialog->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_pointer_dialog, this);\n\tm_joycon_motion_dialog->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_motion_dialog, this);\n\tdolphin_settings->Add(m_joycon_pointer_dialog, 0, wxRIGHT, 6);\n\tdolphin_settings->Add(m_joycon_motion_dialog, 0, wxRIGHT, 8);\n\tdolphin_settings->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Each button opens all settings for that motion group.")), 1, wxALIGN_CENTER_VERTICAL);\n''',
    '''\tm_joycon_motion_dialog = new wxButton(m_joycon_panel, wxID_ANY, _("Motion Input..."));\n\tm_joycon_motion_dialog->Bind(wxEVT_BUTTON, &WiimoteInputPanel::on_joycon_motion_dialog, this);\n\tdolphin_settings->Add(m_joycon_motion_dialog, 0, wxRIGHT, 8);\n\tdolphin_settings->Add(new wxStaticText(m_joycon_panel, wxID_ANY, _("Point and motion settings are combined in one Dolphin-style window.")), 1, wxALIGN_CENTER_VERTICAL);\n''',
    "remove external Pointer button and keep unified Motion Input entry",
)

replace_once(
    panel_cpp,
    '''\t\t_("The Accelerometer and Gyroscope controls use the Joy-Con motion sensors directly, matching Dolphin's Wii Remote motion semantics.")),\n''',
    '''\t\t_("Point uses Dolphin pointer fusion. Accelerometer and Gyroscope game motion use the proven V9 Cemu Joy-Con basis.")),\n''',
    "describe the separated pointer and game-motion streams accurately",
)

replace_once(
    panel_cpp,
    '''\torientation_box->Add(new wxStaticText(&dialog, wxID_ANY, joycon->is_left_joycon() ?\n\t\t_("Joy-Con L Sideways = Dolphin -90 degree orientation") : _("Joy-Con R Sideways = proven Dolphin 180 degree fix")),\n\t\t1, wxALL | wxALIGN_CENTER_VERTICAL, 6);\n''',
    '''\torientation_box->Add(new wxStaticText(&dialog, wxID_ANY,\n\t\t_("Game motion = proven V9 Cemu basis; pointer = Dolphin pre-orientation")),\n\t\t1, wxALL | wxALIGN_CENTER_VERTICAL, 6);\n''',
    "clarify physical-orientation behavior after the stream split",
)

print("Applied Cemu V14 V9 game-motion restoration and removed external Pointer button")
