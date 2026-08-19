from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v4_motion_osd.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# -----------------------------------------------------------------------------
# 1) Motion-only empirical correction.
#    DO NOT touch stick/buttons. Flip only the SDL sensor X axis in the two
#    user-tested combinations that have left/right motion reversed:
#      - Joy-Con L + Vertical
#      - Joy-Con R + Sideways
# -----------------------------------------------------------------------------
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
old = '''\t\t\tif (const auto config = s_joycon_orientation_states.find(id);
\t\t\t\tconfig != s_joycon_orientation_states.end() && config->second.vertical)
\t\t\t{
\t\t\t\tconst float x = sensor_data[0];
\t\t\t\tconst float y = sensor_data[1];
\t\t\t\tconst float z = sensor_data[2];
\t\t\t\tif (config->second.is_left)
\t\t\t\t{
\t\t\t\t\t// SDL L mini: vertical (x,y,z) -> (z,y,-x)
\t\t\t\t\tsensor_data[0] = -z;
\t\t\t\t\tsensor_data[1] = y;
\t\t\t\t\tsensor_data[2] = x;
\t\t\t\t}
\t\t\t\telse
\t\t\t\t{
\t\t\t\t\t// SDL R mini: vertical (x,y,z) -> (-z,y,x)
\t\t\t\t\tsensor_data[0] = z;
\t\t\t\t\tsensor_data[1] = y;
\t\t\t\t\tsensor_data[2] = -x;
\t\t\t\t}
\t\t\t}

\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)
'''
new = '''\t\t\tif (const auto config = s_joycon_orientation_states.find(id);
\t\t\t\tconfig != s_joycon_orientation_states.end() && config->second.vertical)
\t\t\t{
\t\t\t\tconst float x = sensor_data[0];
\t\t\t\tconst float y = sensor_data[1];
\t\t\t\tconst float z = sensor_data[2];
\t\t\t\tif (config->second.is_left)
\t\t\t\t{
\t\t\t\t\t// SDL L mini: vertical (x,y,z) -> (z,y,-x)
\t\t\t\t\tsensor_data[0] = -z;
\t\t\t\t\tsensor_data[1] = y;
\t\t\t\t\tsensor_data[2] = x;
\t\t\t\t}
\t\t\t\telse
\t\t\t\t{
\t\t\t\t\t// SDL R mini: vertical (x,y,z) -> (-z,y,x)
\t\t\t\t\tsensor_data[0] = z;
\t\t\t\t\tsensor_data[1] = y;
\t\t\t\t\tsensor_data[2] = -x;
\t\t\t\t}
\t\t\t}

\t\t\t// V4 empirical motion correction. The stick/button transforms are intentionally
\t\t\t// untouched. Only the horizontal sensor X sign is corrected for the two
\t\t\t// combinations confirmed reversed on real Joy-Cons.
\t\t\tif (const auto config = s_joycon_orientation_states.find(id);
\t\t\t\tconfig != s_joycon_orientation_states.end())
\t\t\t{
\t\t\t\tconst bool flip_horizontal_motion =
\t\t\t\t\t(config->second.is_left && config->second.vertical) ||
\t\t\t\t\t(!config->second.is_left && !config->second.vertical);
\t\t\t\tif (flip_horizontal_motion)
\t\t\t\t\tsensor_data[0] = -sensor_data[0];
\t\t\t}

\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)
'''
replace_once(provider, old, new, "V4 motion X sign correction")


# -----------------------------------------------------------------------------
# 2) Orientation OSD notification. Suppress it while loading a saved profile.
# -----------------------------------------------------------------------------
header = root / "src/input/api/SDL/SDLController.h"
replace_once(
    header,
    "\tvoid set_joycon_orientation(JoyConOrientation orientation);\n",
    "\tvoid set_joycon_orientation(JoyConOrientation orientation, bool notify = true);\n",
    "orientation notification API",
)

controller = root / "src/input/api/SDL/SDLController.cpp"
replace_once(
    controller,
    '#include "input/api/SDL/SDLControllerProvider.h"\n',
    '#include "input/api/SDL/SDLControllerProvider.h"\n#include "Cafe/HW/Latte/Core/LatteOverlay.h"\n',
    "orientation OSD include",
)

old = '''void SDLController::set_joycon_orientation(JoyConOrientation orientation)
{
\tif (!is_joycon())
\t\treturn;

\tstd::scoped_lock lock(m_controller_mutex);
\tm_joycon_orientation.store(orientation, std::memory_order_relaxed);
\tif (m_diid >= 0)
\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), orientation == JoyConOrientation::Vertical);
}
'''
new = '''void SDLController::set_joycon_orientation(JoyConOrientation orientation, bool notify)
{
\tif (!is_joycon())
\t\treturn;

\tstd::scoped_lock lock(m_controller_mutex);
\tconst auto previous = m_joycon_orientation.load(std::memory_order_relaxed);
\tm_joycon_orientation.store(orientation, std::memory_order_relaxed);
\tif (m_diid >= 0)
\t\tm_provider->set_joycon_orientation(m_diid, is_left_joycon(), orientation == JoyConOrientation::Vertical);

\tif (notify && previous != orientation)
\t{
\t\tconst char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";
\t\tconst char* mode = orientation == JoyConOrientation::Vertical ? "Vertical" : "Sideways";
\t\tLatteOverlay_pushNotification(fmt::format("{} -> {}", side, mode), 2200);
\t}
}
'''
replace_once(controller, old, new, "orientation OSD implementation")

replace_once(
    controller,
    "\tset_joycon_orientation(orientation);\n}\n",
    "\tset_joycon_orientation(orientation, false);\n}\n",
    "silent profile orientation restore",
)


# -----------------------------------------------------------------------------
# 3) Upstream Cemu already has a real Toggle fast-forward hotkey (1x <-> 4x).
#    Keep its behavior, add a visible OSD state notification.
# -----------------------------------------------------------------------------
hotkeys = root / "src/gui/wxgui/input/HotkeySettings.cpp"
replace_once(
    hotkeys,
    '#include "Cafe/HW/Latte/Renderer/Renderer.h"\n',
    '#include "Cafe/HW/Latte/Renderer/Renderer.h"\n#include "Cafe/HW/Latte/Core/LatteOverlay.h"\n',
    "fast-forward OSD include",
)

old = '''\t\t{&s_cfgHotkeys.toggleFastForward, [](void) {
\t\t\t ActiveSettings::SetTimerShiftFactor((ActiveSettings::GetTimerShiftFactor() < 3) ? 3 : 1);
\t\t }},
'''
new = '''\t\t{&s_cfgHotkeys.toggleFastForward, [](void) {
\t\t\t const bool enableFastForward = ActiveSettings::GetTimerShiftFactor() >= 3;
\t\t\t ActiveSettings::SetTimerShiftFactor(enableFastForward ? 1 : 3);
\t\t\t LatteOverlay_pushNotification(enableFastForward ? "Fast-forward ON (4x)" : "Fast-forward OFF (1x)", 2200);
\t\t }},
'''
replace_once(hotkeys, old, new, "fast-forward toggle OSD")

print("Cemu Joy-Con V4 motion + OSD patch applied successfully.")
