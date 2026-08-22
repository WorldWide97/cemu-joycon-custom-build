from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v10_dolphin_postfix.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# -----------------------------------------------------------------------------
# 1) Match BOTH proven Dolphin orientation behaviors.
#    L Sideways = stock Dolphin -90 degrees around Z.
#    R Sideways = user's custom +180 degree around Z.
#    Pointer stream remains pre-orientation, exactly like Dolphin.
# -----------------------------------------------------------------------------
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"

replace_once(
    provider,
    '''\t\t\tbool v10_is_joycon = false;\n\t\t\tbool v10_right_sideways = false;\n''',
    '''\t\t\tbool v10_is_joycon = false;\n\t\t\tbool v10_left_sideways = false;\n\t\t\tbool v10_right_sideways = false;\n''',
    "track Dolphin L and R Sideways orientations",
)

replace_once(
    provider,
    '''\t\t\t\tv10_is_joycon = true;\n\t\t\t\tv10_right_sideways = !config->second.is_left && !config->second.vertical;\n''',
    '''\t\t\t\tv10_is_joycon = true;\n\t\t\t\tv10_left_sideways = config->second.is_left && !config->second.vertical;\n\t\t\t\tv10_right_sideways = !config->second.is_left && !config->second.vertical;\n''',
    "derive physical Sideways per Joy-Con",
)

replace_once(
    provider,
    '''\t\t\t\t\t// User-tested Dolphin patch: a standalone 180-degree Z turn for R\n\t\t\t\t\t// in natural Sideways orientation. Pointer stream intentionally bypasses it.\n\t\t\t\t\tif (v10_right_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tdolphin_acc.x = -dolphin_acc.x;\n\t\t\t\t\t\tdolphin_acc.y = -dolphin_acc.y;\n\t\t\t\t\t}\n''',
    '''\t\t\t\t\t// Dolphin output orientation is applied AFTER the pointer stream is captured.\n\t\t\t\t\t// L Sideways: stock Dolphin RotateZ(-90 degrees): (x,y)->(y,-x).\n\t\t\t\t\t// R Sideways: user's proven custom RotateZ(180 degrees): (x,y)->(-x,-y).\n\t\t\t\t\tif (v10_left_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tconst float old_x = dolphin_acc.x;\n\t\t\t\t\t\tdolphin_acc.x = dolphin_acc.y;\n\t\t\t\t\t\tdolphin_acc.y = -old_x;\n\t\t\t\t\t}\n\t\t\t\t\telse if (v10_right_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tdolphin_acc.x = -dolphin_acc.x;\n\t\t\t\t\t\tdolphin_acc.y = -dolphin_acc.y;\n\t\t\t\t\t}\n''',
    "apply stock Dolphin L -90 and custom R 180 accelerometer orientation",
)

replace_once(
    provider,
    '''\t\t\t\t\tif (v10_right_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tdolphin_gyro.x = -dolphin_gyro.x;\n\t\t\t\t\t\tdolphin_gyro.y = -dolphin_gyro.y;\n\t\t\t\t\t}\n\t\t\t\t\ttracking.gyro = dolphin_gyro;\n''',
    '''\t\t\t\t\tif (v10_left_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tconst float old_x = dolphin_gyro.x;\n\t\t\t\t\t\tdolphin_gyro.x = dolphin_gyro.y;\n\t\t\t\t\t\tdolphin_gyro.y = -old_x;\n\t\t\t\t\t}\n\t\t\t\t\telse if (v10_right_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tdolphin_gyro.x = -dolphin_gyro.x;\n\t\t\t\t\t\tdolphin_gyro.y = -dolphin_gyro.y;\n\t\t\t\t\t}\n\t\t\t\t\ttracking.gyro = dolphin_gyro;\n''',
    "apply stock Dolphin L -90 and custom R 180 gyroscope orientation",
)


# -----------------------------------------------------------------------------
# 2) Cemu's stock MotionHandler performs its own gyro bias subtraction in
#    getMotionSample(). V10 already calibrated Joy-Con gyro using Dolphin's exact
#    3-second/2deg/s logic, so a second Cemu bias would distort sensitivity.
#    Add a dedicated already-calibrated path; non-Joy-Con behavior is unchanged.
# -----------------------------------------------------------------------------
motion = root / "src/input/motion/MotionHandler.h"

replace_once(
    motion,
    '''\tvoid processMotionSample(\n\t\tfloat deltaTime,\n\t\tfloat gx, float gy, float gz,\n\t\tfloat accx, float accy, float accz)\n\t{\n''',
    '''\tvoid processMotionSample(\n\t\tfloat deltaTime,\n\t\tfloat gx, float gy, float gz,\n\t\tfloat accx, float accy, float accz)\n\t{\n\t\tm_gyroAlreadyCalibrated = false;\n''',
    "mark stock Cemu gyro as needing Cemu bias",
)

# Insert a dedicated Dolphin path immediately before getMotionSample().
replace_once(
    motion,
    '''\tMotionSample getMotionSample()\n\t{\n''',
    '''\t// V10 Joy-Con path: gyro is already bias-corrected and deadzoned exactly like\n\t// Dolphin 2606a. Keep Cemu's attitude adapter for KPAD/VPAD structures, but do\n\t// not subtract another Cemu gyro bias from the physical motion values.\n\tvoid processDolphinMotionSample(\n\t\tfloat deltaTime,\n\t\tfloat gx, float gy, float gz,\n\t\tfloat accx, float accy, float accz)\n\t{\n\t\tm_gyroAlreadyCalibrated = true;\n\t\tm_gyro[0] = gx;\n\t\tm_gyro[1] = gy;\n\t\tm_gyro[2] = gz;\n\t\tm_prevAcc[0] = m_acc[0];\n\t\tm_prevAcc[1] = m_acc[1];\n\t\tm_prevAcc[2] = m_acc[2];\n\t\tm_acc[0] = accx;\n\t\tm_acc[1] = accy;\n\t\tm_acc[2] = accz;\n\t\tm_imu.updateIMU(deltaTime, gx, gy, gz, accx, accy, accz);\n\t\tm_orientation[0] = _radToOrientation(-m_imu.getYawRadians()) - 0.50f;\n\t\tm_orientation[1] = _radToOrientation(-m_imu.getPitchRadians()) - 0.50f;\n\t\tm_orientation[2] = _radToOrientation(m_imu.getRollRadians());\n\t}\n\n\tMotionSample getMotionSample()\n\t{\n''',
    "add already-calibrated Dolphin Joy-Con motion path",
)

replace_once(
    motion,
    '''\t\tgyroDebiased[0] = m_gyro[0] - gBias[0];\n\t\tgyroDebiased[1] = m_gyro[1] - gBias[1];\n\t\tgyroDebiased[2] = m_gyro[2] - gBias[2];\n''',
    '''\t\tif (m_gyroAlreadyCalibrated)\n\t\t{\n\t\t\tgyroDebiased[0] = m_gyro[0];\n\t\t\tgyroDebiased[1] = m_gyro[1];\n\t\t\tgyroDebiased[2] = m_gyro[2];\n\t\t}\n\t\telse\n\t\t{\n\t\t\tgyroDebiased[0] = m_gyro[0] - gBias[0];\n\t\t\tgyroDebiased[1] = m_gyro[1] - gBias[1];\n\t\t\tgyroDebiased[2] = m_gyro[2] - gBias[2];\n\t\t}\n''',
    "prevent second Cemu bias subtraction on Dolphin gyro",
)

replace_once(
    motion,
    '''\tfloat m_orientation[3]{};\n''',
    '''\tfloat m_orientation[3]{};\n\tbool m_gyroAlreadyCalibrated{};\n''',
    "store calibrated gyro path state",
)

replace_once(
    provider,
    '''\t\t\t\t\tif (s_joycon_orientation_states.contains(id))\n\t\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, tracking.acc.y, tracking.acc.z);\n\t\t\t\t\telse\n''',
    '''\t\t\t\t\tif (s_joycon_orientation_states.contains(id))\n\t\t\t\t\t\tstate.handler.processDolphinMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, tracking.acc.y, tracking.acc.z);\n\t\t\t\t\telse\n''',
    "route Joy-Con through already-calibrated Dolphin motion path",
)

print("Cemu Joy-Con V10 Dolphin postfix applied: L -90, R 180, no double gyro bias.")
