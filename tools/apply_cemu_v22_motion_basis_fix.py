from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v22_motion_basis_fix.py <cemu-source-root>")

root = Path(sys.argv[1])
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"
panel = root / "src/gui/wxgui/input/panels/WiimoteInputPanel.cpp"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


# V21 only fixed the duplicated Motion Input choice mapping. Hardware testing proved
# the real game-motion basis itself was still opposite: the transform that produced
# natural horizontal motion was attached to Vertical instead of Sideways.
#
# V22 changes ONLY the game-motion IMU basis. Button/stick orientation remains the
# already-working SDLController::apply_vertical_transform path.
#
# Sideways now uses the inverse SDL mini-gamepad sensor rotation (the transform that
# hardware testing showed gives natural Sideways motion). Vertical remains in the
# unrotated mini-gamepad sensor basis. This affects both game accelerometer and game
# gyro because they share v9_game_sensor, but it does NOT touch the independent
# Dolphin pointer stream.
replace_once(
    provider,
    '''\t\t\t\tif (!config->second.is_left && !config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\t// V15 hardware-proven Joy-Con R Sideways correction: 180 degrees.\n\t\t\t\t\t// This is equivalent to physically turning R so its stick is right.\n\t\t\t\t\tv9_game_sensor[0] = -x;\n\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\tv9_game_sensor[2] = -z;\n\t\t\t\t}\n\t\t\t\telse if (config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\tif (config->second.is_left)\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = -z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = x;\n\t\t\t\t\t}\n\t\t\t\t\telse\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = -x;\n\t\t\t\t\t}\n\t\t\t\t}\n''',
    '''\t\t\t\t// V22 hardware-driven motion basis. SDL is globally kept in mini-gamepad\n\t\t\t\t// mode, but the physical Wii Remote Sideways pose needs the inverse mini\n\t\t\t\t// sensor rotation. Vertical deliberately keeps the raw mini sensor basis.\n\t\t\t\t// Stick/buttons are handled separately and are not changed here.\n\t\t\t\tif (!config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\tif (config->second.is_left)\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = -z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = x;\n\t\t\t\t\t}\n\t\t\t\t\telse\n\t\t\t\t\t{\n\t\t\t\t\t\tv9_game_sensor[0] = z;\n\t\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\t\tv9_game_sensor[2] = -x;\n\t\t\t\t\t}\n\t\t\t\t}\n''',
    "swap the actual game-motion Sideways/Vertical sensor basis",
)


# V15 applied R's 180-degree correction before the later axis conversion. The user
# correctly reported that R still had to be physically reversed. V22 therefore
# applies the requested 180-degree correction AFTER the orientation basis has been
# selected and AFTER the game accelerometer vector has been formed. In Cemu's game
# accelerometer contract, the proven physical 180 turn is X/Z sign inversion with Y
# unchanged. This is accelerometer-only: game gyro, pointer, KPAD formula, buttons and
# sticks do not inherit this correction.
replace_once(
    provider,
    '''\t\t\t\t\ttracking.acc = glm::vec3{\n\t\t\t\t\t\t-v9_game_sensor[0] / 9.81f,\n\t\t\t\t\t\t-v9_game_sensor[1] / 9.81f,\n\t\t\t\t\t\t-v9_game_sensor[2] / 9.81f };\n''',
    '''\t\t\t\t\ttracking.acc = glm::vec3{\n\t\t\t\t\t\t-v9_game_sensor[0] / 9.81f,\n\t\t\t\t\t\t-v9_game_sensor[1] / 9.81f,\n\t\t\t\t\t\t-v9_game_sensor[2] / 9.81f };\n\t\t\t\t\tif (const auto game_config = s_joycon_orientation_states.find(id);\n\t\t\t\t\t\tgame_config != s_joycon_orientation_states.end() && !game_config->second.is_left)\n\t\t\t\t\t{\n\t\t\t\t\t\t// V22: final Joy-Con R accelerometer = requested physical 180-degree\n\t\t\t\t\t\t// correction relative to L. Apply here so later axis routing cannot\n\t\t\t\t\t\t// cancel or reinterpret the correction. Y remains unchanged.\n\t\t\t\t\t\ttracking.acc.x = -tracking.acc.x;\n\t\t\t\t\t\ttracking.acc.z = -tracking.acc.z;\n\t\t\t\t\t}\n''',
    "apply Joy-Con R 180 correction to the final game accelerometer vector",
)

# Remove misleading V15 wording from Motion Input now that the 180 correction is
# accelerometer-only and occurs after physical orientation selection.
text = panel.read_text(encoding="utf-8")
text = text.replace(
    '_("Game motion = Cemu basis; R Sideways = hardware-verified 180 degree fix; pointer = Dolphin pre-orientation")',
    '_("V22: Sideways/Vertical motion basis is physical; Joy-Con R accelerometer receives final 180 degree correction; pointer remains independent")',
)
panel.write_text(text, encoding="utf-8")

print("Applied V22 actual motion-basis swap and final Joy-Con R accelerometer 180 correction")
