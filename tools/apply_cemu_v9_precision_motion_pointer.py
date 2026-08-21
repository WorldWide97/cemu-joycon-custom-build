from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v9_precision_motion_pointer.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# -----------------------------------------------------------------------------
# 1) Motion: SDL already normalizes standalone Joy-Con L/R sensor orientation
# for mini-gamepad mode. V8 added an extra R-Sideways X/Z flip after SDL, which
# double-corrected the right Joy-Con. Remove that extra flip and keep both sides
# in SDL's common physical gamepad basis.
#
# Also make the old per-axis motion calibration sign-only in precision mode.
# Multiplying accelerometer magnitude changes the 1 g gravity vector and makes
# Wii Remote tilt steering (Mario Kart) feel wrong. Precision mode preserves
# physical sensor magnitude and only honors explicit axis inversion.
# -----------------------------------------------------------------------------
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
old_motion = '''\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\tconfig != s_joycon_orientation_states.end())\n\t\t\t{\n\t\t\t\t// SDL's standalone R mini-gamepad basis is the L basis with X/Z\n\t\t\t\t// reversed. Normalize R Sideways so identical physical movement\n\t\t\t\t// produces identical Wii Remote motion on both Joy-Cons.\n\t\t\t\tif (!config->second.vertical && !config->second.is_left)\n\t\t\t\t{\n\t\t\t\t\tsensor_data[0] = -sensor_data[0];\n\t\t\t\t\tsensor_data[2] = -sensor_data[2];\n\t\t\t\t}\n\n\t\t\t\tsensor_data[0] *= config->second.motion_scale_x;\n\t\t\t\tsensor_data[1] *= config->second.motion_scale_y;\n\t\t\t\tsensor_data[2] *= config->second.motion_scale_z;\n\t\t\t}\n'''
new_motion = '''\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\tconfig != s_joycon_orientation_states.end())\n\t\t\t{\n\t\t\t\t// V9 precision basis: SDL already maps standalone Joy-Con L and R\n\t\t\t\t// into the same mini-gamepad sensor convention. Do not flip R again.\n\t\t\t\t// Keep physical sensor magnitude 1:1; only explicit inversion survives.\n\t\t\t\tsensor_data[0] *= (config->second.motion_scale_x < 0.0f) ? -1.0f : 1.0f;\n\t\t\t\tsensor_data[1] *= (config->second.motion_scale_y < 0.0f) ? -1.0f : 1.0f;\n\t\t\t\tsensor_data[2] *= (config->second.motion_scale_z < 0.0f) ? -1.0f : 1.0f;\n\t\t\t}\n'''
replace_once(provider, old_motion, new_motion, "remove R Sideways double transform and preserve physical IMU magnitude")


# -----------------------------------------------------------------------------
# 2) Pointer: V8 already uses the full fused 3D attitude ray, but its default
# screen sign inherited V7's rate-based mapping and its default smoothing/deadzone
# made the cursor lag behind the hand. Keep the true 3D ray projection, make the
# screen directions physical (right -> right, up -> up), and default to direct
# low-latency tracking.
# -----------------------------------------------------------------------------
controller_h = root / "src/input/api/SDL/SDLController.h"
replace_once(
    controller_h,
    '''\tstd::atomic<float> m_pointer_deadzone_degrees{ 0.15f };\n\tstd::atomic<float> m_pointer_smoothing{ 0.08f };\n''',
    '''\tstd::atomic<float> m_pointer_deadzone_degrees{ 0.05f };\n\tstd::atomic<float> m_pointer_smoothing{ 0.0f };\n''',
    "use precision pointer defaults",
)

controller_cpp = root / "src/input/api/SDL/SDLController.cpp"
replace_once(
    controller_cpp,
    '''\t// Match the established Cemu/SDL gyro sign used by V7, but expose explicit\n\t// inversion switches so each physical Joy-Con can be corrected without rebuilds.\n\tfloat screen_horizontal = -horizontal_angle;\n\tfloat screen_vertical = -vertical_angle;\n''',
    '''\t// V9 physical screen directions from the full 3D pointing ray:\n\t// rotate/aim right -> cursor right; aim up -> cursor up.\n\tfloat screen_horizontal = horizontal_angle;\n\tfloat screen_vertical = -vertical_angle;\n''',
    "correct default pointer screen directions",
)

# Make tiny residual smoothing values truly direct, while retaining the UI option
# for users who explicitly choose smoothing.
replace_once(
    controller_cpp,
    '''\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\tconst float follow = 1.0f - get_pointer_smoothing();\n\tm_joycon_pointer_position += (target - m_joycon_pointer_position) * follow;\n''',
    '''\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\tconst float smoothing = get_pointer_smoothing();\n\tif (smoothing <= 0.001f)\n\t\tm_joycon_pointer_position = target;\n\telse\n\t{\n\t\tconst float follow = 1.0f - smoothing;\n\t\tm_joycon_pointer_position += (target - m_joycon_pointer_position) * follow;\n\t}\n''',
    "use direct pointer tracking when smoothing is disabled",
)

print("Cemu Joy-Con V9 precision motion + 3D pointer patch applied successfully.")
