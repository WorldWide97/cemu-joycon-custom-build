from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v15_r_sideways_kpad_wheel.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
wpad = root / "src/input/emulated/WPADController.cpp"
panel = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"


# Hardware validation of V14 established that Joy-Con R must be turned over in
# Sideways mode for its motion to match L. Apply the same X/Z 180-degree basis
# correction that the physical turn produces, only to the game/KPAD stream.
# The independent Dolphin pointer stream remains untouched and pre-orientation.
replace_once(
    provider,
    '''\t\t\t\t// Exact V9 physical-orientation transform for game/KPAD motion.\n\t\t\t\t// Sideways stays in SDL mini-gamepad coordinates. Vertical applies\n\t\t\t\t// one clean +/-90 degree Y rotation, with no Dolphin axis reorder.\n''',
    '''\t\t\t\t// V15 game/KPAD physical basis: L Sideways stays in SDL mini-gamepad\n\t\t\t\t// coordinates, R Sideways gets the hardware-proven 180-degree X/Z\n\t\t\t\t// correction, and Vertical keeps V9's clean +/-90-degree Y rotation.\n''',
    "document the V15 hardware-tested game-motion basis",
)

replace_once(
    provider,
    '''\t\t\t\tif (config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\tif (config->second.is_left)\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = -z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = x;\n\t\t\t\t\t}\n\t\t\t\t\telse\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = -x;\n\t\t\t\t\t}\n\t\t\t\t}\n''',
    '''\t\t\t\tif (!config->second.is_left && !config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\t// V15 hardware-proven Joy-Con R Sideways correction: 180 degrees.\n\t\t\t\t\t// This is equivalent to physically turning R so its stick is right.\n\t\t\t\t\tv9_game_sensor[0] = -x;\n\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\tv9_game_sensor[2] = -z;\n\t\t\t\t}\n\t\t\t\telse if (config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\tif (config->second.is_left)\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = -z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = x;\n\t\t\t\t\t}\n\t\t\t\t\telse\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = -x;\n\t\t\t\t\t}\n\t\t\t\t}\n''',
    "apply hardware-proven Joy-Con R Sideways 180-degree game-motion fix",
)


# KPAD's `down` is a normalized 2D direction, not a pair of raw acceleration
# components. V11 preserved a sign on X, but that puts the neutral wheel on the
# negative half-plane. Mario Kart derives steering angle from this vector.
# Compute a stable unit vector: radial horizontal magnitude is non-negative,
# while Y keeps the signed roll component used for left/right steering.
replace_once(
    wpad,
    '''\t\t// KPAD calls this field `down`: it is a SIGNED 2D down vector from the\n\t\t// accelerometer. Never take abs() here; games such as Mario Kart and\n\t\t// Mario Party need the sign to distinguish left from right tilt.\n\t\tstatus.accVertical.x = std::clamp(acc.x + acc.y, -1.0f, 1.0f);\n\t\tstatus.accVertical.y = std::clamp(-acc.z, -1.0f, 1.0f);\n''',
    '''\t\t// KPAD calls this field `down`: it is a normalized 2D direction.\n\t\t// X is the non-negative horizontal radius; Y is signed wheel roll.\n\t\t// Keeping this on the correct half-plane is required by Mario Kart.\n\t\tconst float down_horizontal = std::sqrt(acc.x * acc.x + acc.y * acc.y);\n\t\tconst float down_length = std::sqrt(down_horizontal * down_horizontal + acc.z * acc.z);\n\t\tif (down_length > 0.0001f)\n\t\t{\n\t\t\tstatus.accVertical.x = std::clamp(down_horizontal / down_length, 0.0f, 1.0f);\n\t\t\tstatus.accVertical.y = std::clamp(-acc.z / down_length, -1.0f, 1.0f);\n\t\t}\n\t\telse\n\t\t{\n\t\t\tstatus.accVertical.x = 0.0f;\n\t\t\tstatus.accVertical.y = 0.0f;\n\t\t}\n''',
    "emit normalized KPAD down vector for Mario Kart wheel steering",
)


replace_once(
    panel,
    '''\t\t_("Point uses Dolphin pointer fusion. Accelerometer and Gyroscope game motion use the proven V9 Cemu Joy-Con basis.")),\n''',
    '''\t\t_("Point uses Dolphin pointer fusion. Game motion uses the proven Cemu basis plus the hardware-verified Joy-Con R Sideways fix.")),\n''',
    "describe V15 R Sideways motion correction",
)

replace_once(
    panel,
    '''\t\t_("Game motion = proven V9 Cemu basis; pointer = Dolphin pre-orientation")),\n''',
    '''\t\t_("Game motion = Cemu basis; R Sideways = hardware-verified 180 degree fix; pointer = Dolphin pre-orientation")),\n''',
    "show the hardware-verified R Sideways behavior",
)

print("Applied Cemu V15 Joy-Con R Sideways and normalized KPAD wheel steering fixes")
