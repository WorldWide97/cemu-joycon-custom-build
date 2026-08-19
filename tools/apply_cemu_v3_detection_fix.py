from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v3_detection_fix.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V2 used exact GUID equality to identify Joy-Con L/R. That can fail when SDL3
# exposes the correct Joy-Con gamepad type/name with a transport/driver-specific GUID.
# Replace it with runtime SDL_GamepadType detection, then name fallback, then GUID.
header = root / "src/input/api/SDL/SDLController.h"
old = '''\tbool is_left_joycon() const { return m_guid == kLeftJoyCon; }
\tbool is_right_joycon() const { return m_guid == kRightJoyCon; }
\tbool is_joycon() const { return is_left_joycon() || is_right_joycon(); }
'''
new = '''\tbool is_left_joycon() const;
\tbool is_right_joycon() const;
\tbool is_joycon() const { return is_left_joycon() || is_right_joycon(); }
'''
replace_once(header, old, new, "Joy-Con detection declarations")

cpp = root / "src/input/api/SDL/SDLController.cpp"
old = '''void SDLController::normalize_hotkey(std::vector<uint32>& buttons) const
{
'''
new = '''bool SDLController::is_left_joycon() const
{
\tstd::scoped_lock lock(m_controller_mutex);

\t// Primary source of truth: SDL3 explicitly distinguishes Joy-Con L and R.
\tif (m_controller)
\t{
\t\tconst auto type = SDL_GetGamepadType(m_controller);
\t\tif (type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT)
\t\t\treturn true;
\t\tif (type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT)
\t\t\treturn false;
\t}

\t// Robust fallback for saved/unopened SDL controller objects.
\tif (m_display_name.find("Joy-Con (L)") != std::string::npos ||
\t\tm_display_name.find("Joy-Con L") != std::string::npos ||
\t\tm_display_name.find("JoyCon (L)") != std::string::npos ||
\t\tm_display_name.find("JoyCon L") != std::string::npos)
\t\treturn true;
\tif (m_display_name.find("Joy-Con (R)") != std::string::npos ||
\t\tm_display_name.find("Joy-Con R") != std::string::npos ||
\t\tm_display_name.find("JoyCon (R)") != std::string::npos ||
\t\tm_display_name.find("JoyCon R") != std::string::npos)
\t\treturn false;

\t// Last fallback keeps compatibility with Cemu's historical Nintendo GUIDs.
\treturn m_guid == kLeftJoyCon;
}

bool SDLController::is_right_joycon() const
{
\tstd::scoped_lock lock(m_controller_mutex);

\tif (m_controller)
\t{
\t\tconst auto type = SDL_GetGamepadType(m_controller);
\t\tif (type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT)
\t\t\treturn true;
\t\tif (type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT)
\t\t\treturn false;
\t}

\tif (m_display_name.find("Joy-Con (R)") != std::string::npos ||
\t\tm_display_name.find("Joy-Con R") != std::string::npos ||
\t\tm_display_name.find("JoyCon (R)") != std::string::npos ||
\t\tm_display_name.find("JoyCon R") != std::string::npos)
\t\treturn true;
\tif (m_display_name.find("Joy-Con (L)") != std::string::npos ||
\t\tm_display_name.find("Joy-Con L") != std::string::npos ||
\t\tm_display_name.find("JoyCon (L)") != std::string::npos ||
\t\tm_display_name.find("JoyCon L") != std::string::npos)
\t\treturn false;

\treturn m_guid == kRightJoyCon;
}

void SDLController::normalize_hotkey(std::vector<uint32>& buttons) const
{
'''
replace_once(cpp, old, new, "runtime SDL Joy-Con type/name detection")

print("Cemu Joy-Con V3 robust L/R detection patch applied successfully.")
