from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v19_physical_joycon_gyro.py <cemu-source-root>")

root = Path(sys.argv[1])
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V19 is intentionally gyro-only. V16's accelerometer, KPAD/down contract,
# pointer, UI, and hardware-proven R Sideways accelerometer basis remain exact.
#
# V16 still feeds game gyro from the V9/raw mini-gamepad coordinates. SDL maps
# standalone Joy-Con motion in the individual-controller frame, so treating L
# and R raw X/Y/Z as the same physical axes swaps/inverts pitch/roll/yaw.
#
# The V10/V13 code immediately above this assignment already reconstructs each
# Joy-Con's native frame and exposes raw_gyro in Wii Remote/Dolphin semantic
# axes:
#   raw_gyro = { pitch, roll, yaw }
# using the correct, side-specific inverse SDL mini-gamepad transform.
# Reuse ONLY that physical gyro basis for game motion. Do not route accelerometer
# through Dolphin and do not use the V17/V18 game-motion paths.
replace_once(
    provider,
    '''\t\t\t\t\t// Exact V9 gyro basis for games. Dolphin's calibrated gyro remains\n\t\t\t\t\t// isolated above for pointer integration and its stillness visualizer.\n\t\t\t\t\ttracking.gyro = glm::vec3{\n\t\t\t\t\t\tv9_game_sensor[0],\n\t\t\t\t\t\t-v9_game_sensor[1],\n\t\t\t\t\t\t-v9_game_sensor[2] };\n''',
    '''\t\t\t\t\t// V19 gyro-only fix: use the physical/native Joy-Con gyro basis\n\t\t\t\t\t// reconstructed above instead of V9 raw mini-gamepad X/Y/Z.\n\t\t\t\t\t// raw_gyro is intentionally NOT the deadzoned pointer gyro; Cemu's\n\t\t\t\t\t// existing MotionHandler keeps its normal game-side bias handling.\n\t\t\t\t\tglm::vec3 game_gyro = raw_gyro;\n\t\t\t\t\tif (const auto game_config = s_joycon_orientation_states.find(id);\n\t\t\t\t\t\tgame_config != s_joycon_orientation_states.end() && !game_config->second.vertical)\n\t\t\t\t\t{\n\t\t\t\t\t\tif (game_config->second.is_left)\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\t// Stock Dolphin Joy-Con L Sideways orientation: RotateZ(-90).\n\t\t\t\t\t\t\tconst float old_x = game_gyro.x;\n\t\t\t\t\t\t\tgame_gyro.x = game_gyro.y;\n\t\t\t\t\t\t\tgame_gyro.y = -old_x;\n\t\t\t\t\t\t}\n\t\t\t\t\t\telse\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\t// User/hardware-proven Joy-Con R Sideways orientation: RotateZ(180).\n\t\t\t\t\t\t\tgame_gyro.x = -game_gyro.x;\n\t\t\t\t\t\t\tgame_gyro.y = -game_gyro.y;\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t\ttracking.gyro = game_gyro;\n''',
    "replace V9 raw game gyro with physical Joy-Con gyro mapping",
)

print("Applied Cemu V19 physical Joy-Con gyro mapping; V16 accelerometer/KPAD/pointer remain unchanged")
