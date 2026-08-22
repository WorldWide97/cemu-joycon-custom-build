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
# 1) Motion basis / Mario Kart steering
# -----------------------------------------------------------------------------
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
old_motion = '''\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\tconfig != s_joycon_orientation_states.end())\n\t\t\t{\n\t\t\t\t// SDL's standalone R mini-gamepad basis is the L basis with X/Z\n\t\t\t\t// reversed. Normalize R Sideways so identical physical movement\n\t\t\t\t// produces identical Wii Remote motion on both Joy-Cons.\n\t\t\t\tif (!config->second.vertical && !config->second.is_left)\n\t\t\t\t{\n\t\t\t\t\tsensor_data[0] = -sensor_data[0];\n\t\t\t\t\tsensor_data[2] = -sensor_data[2];\n\t\t\t\t}\n\n\t\t\t\tsensor_data[0] *= config->second.motion_scale_x;\n\t\t\t\tsensor_data[1] *= config->second.motion_scale_y;\n\t\t\t\tsensor_data[2] *= config->second.motion_scale_z;\n\t\t\t}\n'''
new_motion = '''\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\tconfig != s_joycon_orientation_states.end())\n\t\t\t{\n\t\t\t\t// V9 precision basis: SDL already maps standalone Joy-Con L and R\n\t\t\t\t// into the same mini-gamepad sensor convention. Do not flip R again.\n\t\t\t\t// Preserve physical sensor magnitude 1:1; only explicit inversion survives.\n\t\t\t\tsensor_data[0] *= (config->second.motion_scale_x < 0.0f) ? -1.0f : 1.0f;\n\t\t\t\tsensor_data[1] *= (config->second.motion_scale_y < 0.0f) ? -1.0f : 1.0f;\n\t\t\t\tsensor_data[2] *= (config->second.motion_scale_z < 0.0f) ? -1.0f : 1.0f;\n\t\t\t}\n'''
replace_once(provider, old_motion, new_motion, "remove R Sideways double transform and preserve physical IMU magnitude")


# -----------------------------------------------------------------------------
# 2) Pointer precision / true 3D pointing axis
# Cemu's captured VPAD matrices show that the device's top/nose direction is the
# third attitude vector (Z row), while the second vector is the face/up normal.
# V8 accidentally used the second row as the pointing ray, so yawing the hand
# while flat barely moved the pointer. Use Z as forward, X as right, Y as up.
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
    '''\t// MotionSample attitude rows are local X(right), Y(forward/top), Z(up/face).\n\tconst float* current_forward = attitude + 3;\n\tconst float* reference_right = m_joycon_pointer_reference_attitude.data() + 0;\n\tconst float* reference_forward = m_joycon_pointer_reference_attitude.data() + 3;\n\tconst float* reference_up = m_joycon_pointer_reference_attitude.data() + 6;\n''',
    '''\t// V9: Cemu's VPAD capture proves the Z row tracks the device top/nose\n\t// direction during flat yaw. X is screen-right and Y is face/up normal.\n\t// Use that full 3D basis so aiming follows the actual hand direction.\n\tconst float* current_forward = attitude + 6;\n\tconst float* reference_right = m_joycon_pointer_reference_attitude.data() + 0;\n\tconst float* reference_up = m_joycon_pointer_reference_attitude.data() + 3;\n\tconst float* reference_forward = m_joycon_pointer_reference_attitude.data() + 6;\n''',
    "use VPAD Z nose vector for real 3D pointer",
)

replace_once(
    controller_cpp,
    '''\t// Match the established Cemu/SDL gyro sign used by V7, but expose explicit\n\t// inversion switches so each physical Joy-Con can be corrected without rebuilds.\n\tfloat screen_horizontal = -horizontal_angle;\n\tfloat screen_vertical = -vertical_angle;\n''',
    '''\t// Physical screen directions: aim right -> cursor right; aim up -> cursor up.\n\tfloat screen_horizontal = horizontal_angle;\n\tfloat screen_vertical = -vertical_angle;\n''',
    "correct default pointer screen directions",
)

replace_once(
    controller_cpp,
    '''\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\tconst float follow = 1.0f - get_pointer_smoothing();\n\tm_joycon_pointer_position += (target - m_joycon_pointer_position) * follow;\n''',
    '''\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\tconst float smoothing = get_pointer_smoothing();\n\tif (smoothing <= 0.001f)\n\t\tm_joycon_pointer_position = target;\n\telse\n\t{\n\t\tconst float follow = 1.0f - smoothing;\n\t\tm_joycon_pointer_position += (target - m_joycon_pointer_position) * follow;\n\t}\n''',
    "use direct pointer tracking when smoothing is disabled",
)

print("Cemu Joy-Con V9 precision motion + true 3D pointer patch applied successfully.")
