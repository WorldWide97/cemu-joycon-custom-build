from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v8_postfix.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
replace_once(
    provider,
    '''\tstd::scoped_lock lock(s_mutex);\n\tconst auto it = s_joycon_orientation_states.find(diid);\n\tif (it == s_joycon_orientation_states.end() ||\n\t\tit->second.is_left != is_left ||\n\t\tit->second.vertical != vertical)\n\t{\n\t\ts_motion_states.erase(diid);\n\t}\n\ts_joycon_orientation_states[diid] = { is_left, vertical };\n''',
    '''\tstd::scoped_lock lock(s_mutex);\n\tauto& state = s_joycon_orientation_states[diid];\n\tconst bool changed = state.is_left != is_left || state.vertical != vertical;\n\tif (changed)\n\t\ts_motion_states.erase(diid);\n\t// Preserve V8 per-device motion calibration while changing orientation.\n\tstate.is_left = is_left;\n\tstate.vertical = vertical;\n''',
    "preserve per-Joy-Con motion calibration across orientation changes",
)

controller = root / "src/input/api/SDL/SDLController.cpp"
replace_once(
    controller,
    '''\t\tstd::copy(std::begin(attitude), std::end(attitude), m_joycon_pointer_reference_attitude.begin());\n''',
    '''\t\tfor (size_t i = 0; i < m_joycon_pointer_reference_attitude.size(); ++i)\n\t\t\tm_joycon_pointer_reference_attitude[i] = attitude[i];\n''',
    "avoid iterator dependency in pointer reference copy",
)

panel = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"
replace_once(
    panel,
    '''#include <wx/dcbuffer.h>\n''',
    '''#include <wx/dcbuffer.h>\n#include <wx/settings.h>\n''',
    "include wx system settings for live pointer preview",
)

print("Cemu Joy-Con V8 postfix applied successfully.")
