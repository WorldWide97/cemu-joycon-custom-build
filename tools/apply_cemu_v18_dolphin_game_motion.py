from pathlib import Path
import sys


if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v18_dolphin_game_motion.py <cemu-source-root>")


provider = Path(sys.argv[1]) / "src/input/api/SDL/SDLControllerProvider.cpp"


def replace_once(old: str, new: str, label: str) -> None:
    text = provider.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    provider.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {provider}: {label}")


# V14 kept the Dolphin semantic stream only for the pointer, then delivered a
# separate V9/raw stream to KPAD. That made the game behave exactly like V16.
# Keep the pointer pre-orientation, but give Wii Remote game motion the same
# calibrated Dolphin axes with its required general-motion postfix.
replace_once(
    '''\t\t\t\t\tstate.dolphin_pointer_acc = dolphin_acc;\n\t\t\t\t\tstate.dolphin_pointer_has_acc = true;\n\t\t\t\t\t// Game motion is deliberately NOT Dolphin-oriented. Reproduce V9's\n\t\t\t\t\t// Cemu tracking vector; the adapter's historical Y/Z signs are applied\n\t\t\t\t\t// at processMotionSample below. Pointer remains pre-orientation.\n\t\t\t\t\ttracking.acc = glm::vec3{\n\t\t\t\t\t\t-v9_game_sensor[0] / 9.81f,\n\t\t\t\t\t\t-v9_game_sensor[1] / 9.81f,\n\t\t\t\t\t\t-v9_game_sensor[2] / 9.81f };\n''',
    '''\t\t\t\t\tstate.dolphin_pointer_acc = dolphin_acc;\n\t\t\t\t\tstate.dolphin_pointer_has_acc = true;\n\t\t\t\t\t// V18: pointer stays pre-orientation, while game motion receives the\n\t\t\t\t\t// calibrated Dolphin semantic vector plus its general-motion postfix.\n\t\t\t\t\tglm::vec3 game_acc = dolphin_acc;\n\t\t\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\t\t\tconfig != s_joycon_orientation_states.end() && !config->second.vertical)\n\t\t\t\t\t{\n\t\t\t\t\t\tif (config->second.is_left)\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\tconst float old_x = game_acc.x;\n\t\t\t\t\t\t\tgame_acc.x = game_acc.y;\n\t\t\t\t\t\t\tgame_acc.y = -old_x;\n\t\t\t\t\t\t}\n\t\t\t\t\t\telse\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\t// Joy-Con R natural Sideways: Dolphin user's proven 180-degree fix.\n\t\t\t\t\t\t\tgame_acc.x = -game_acc.x;\n\t\t\t\t\t\t\tgame_acc.y = -game_acc.y;\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t\ttracking.acc = game_acc;\n''',
    "deliver Dolphin accelerometer axes to KPAD",
)

replace_once(
    '''\t\t\t\t\ttracking.gyro = game_gyro;\n''',
    '''\t\t\t\t\t// V18 game motion is the calibrated Dolphin semantic stream, not V9/raw.\n\t\t\t\t\t// Apply orientation only after calibration; the pointer above remains untouched.\n\t\t\t\t\tgame_gyro = dolphin_gyro;\n\t\t\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\t\t\tconfig != s_joycon_orientation_states.end() && !config->second.vertical)\n\t\t\t\t\t{\n\t\t\t\t\t\tif (config->second.is_left)\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\tconst float old_x = game_gyro.x;\n\t\t\t\t\t\t\tgame_gyro.x = game_gyro.y;\n\t\t\t\t\t\t\tgame_gyro.y = -old_x;\n\t\t\t\t\t\t}\n\t\t\t\t\t\telse\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\tgame_gyro.x = -game_gyro.x;\n\t\t\t\t\t\t\tgame_gyro.y = -game_gyro.y;\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t\ttracking.gyro = game_gyro;\n''',
    "deliver calibrated Dolphin gyro axes to KPAD",
)

replace_once(
    '''\t\t\t\t// Live game-motion view shows the exact values delivered to Cemu/KPAD.\n\t\t\t\t// The pointer debug view remains the independent Dolphin stream.\n\t\t\t\tstate.dolphin_motion_acc = glm::vec3{ tracking.acc.x, -tracking.acc.y, -tracking.acc.z };\n\t\t\t\tstate.dolphin_motion_gyro = tracking.gyro;\n''',
    '''\t\t\t\t// Live game-motion view is the calibrated Dolphin game stream.\n\t\t\t\tstate.dolphin_motion_acc = tracking.acc;\n\t\t\t\tstate.dolphin_motion_gyro = tracking.gyro;\n''',
    "show direct Dolphin game axes in live motion view",
)

replace_once(
    '''\t\t\t\t\t// V14: all game motion uses Cemu's proven V9 adapter contract. Never\n\t\t\t\t\t// feed Dolphin binding-semantic axes directly into WiiUMotionHandler.\n\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n''',
    '''\t\t\t\t\t// V18: Joy-Cons use the already-calibrated Dolphin game path. Non-Joy-Con\n\t\t\t\t\t// controllers retain Cemu's original motion adapter unchanged.\n\t\t\t\t\tif (s_joycon_orientation_states.contains(id))\n\t\t\t\t\t\tstate.handler.processDolphinMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, tracking.acc.y, tracking.acc.z);\n\t\t\t\t\telse\n\t\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n''',
    "route Joy-Con game motion through calibrated Dolphin handler",
)

print("Applied Cemu V18 direct Dolphin game-motion routing")
