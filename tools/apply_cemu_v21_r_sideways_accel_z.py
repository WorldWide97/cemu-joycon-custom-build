from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v21_r_sideways_accel_z.py <cemu-source-root>")

root = Path(sys.argv[1])
provider = root / "src/input/api/SDL/SDLControllerProvider.cpp"

text = provider.read_text(encoding="utf-8")
old = '''\t\t\t\tif (!config->second.is_left && !config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\t// V15 hardware-proven Joy-Con R Sideways correction: 180 degrees.\n\t\t\t\t\t// This is equivalent to physically turning R so its stick is right.\n\t\t\t\t\tv9_game_sensor[0] = -x;\n\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\tv9_game_sensor[2] = -z;\n\t\t\t\t}\n'''
new = '''\t\t\t\tif (!config->second.is_left && !config->second.vertical)\n\t\t\t\t{\n\t\t\t\t\t// V21 hardware correction from side-by-side L/R motion visualizer test.\n\t\t\t\t\t// R already matches L on the live/game X axis; only the gravity/roll Z\n\t\t\t\t\t// axis is inverted. Preserve the required R X correction and stop\n\t\t\t\t\t// double-inverting Z. This feeds both the live Accelerometer view and\n\t\t\t\t\t// Cemu/KPAD through the existing V16 processMotionSample contract.\n\t\t\t\t\tv9_game_sensor[0] = -x;\n\t\t\t\t\tv9_game_sensor[1] = y;\n\t\t\t\t\tv9_game_sensor[2] = z;\n\t\t\t\t}\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"V21 R Sideways V15 block: expected exactly one match, found {count}")
provider.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Applied V21 R Sideways accelerometer/KPAD Z-sign correction; V16 otherwise unchanged")
