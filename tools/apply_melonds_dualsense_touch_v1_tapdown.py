from pathlib import Path
import sys


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched: {label}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_melonds_dualsense_touch_v1_tapdown.py <melonDS-source-root>")

    root = Path(sys.argv[1]).resolve()
    header = root / "src/frontend/qt_sdl/EmuInstance.h"
    input_cpp = root / "src/frontend/qt_sdl/EmuInstanceInput.cpp"

    replace_once(
        header,
        """    std::atomic<int> touchpadEventX;\n    std::atomic<int> touchpadEventY;\n""",
        """    std::atomic<int> touchpadEventX;\n    std::atomic<int> touchpadEventY;\n    std::atomic<int> touchpadTapX;\n    std::atomic<int> touchpadTapY;\n""",
        "dedicated fast-tap DOWN coordinates",
    )

    replace_once(
        input_cpp,
        """    if (event->type == SDL_CONTROLLERTOUCHPADDOWN)\n    {\n        inst->touchpadEventDown.store(true, std::memory_order_release);\n        // Keep a one-input-step tap latched until inputProcess consumes it.\n        inst->touchpadTapPending.store(true, std::memory_order_release);\n""",
        """    if (event->type == SDL_CONTROLLERTOUCHPADDOWN)\n    {\n        // Preserve the exact physical contact point independently from later\n        // MOTION/UP reports. If the whole tap occurs between two emulator polls,\n        // the DS receives the DOWN point, exactly as a stylus contact sample.\n        inst->touchpadTapX.store(x, std::memory_order_relaxed);\n        inst->touchpadTapY.store(y, std::memory_order_relaxed);\n        inst->touchpadEventDown.store(true, std::memory_order_release);\n        // Keep a one-input-step tap latched until inputProcess consumes it.\n        inst->touchpadTapPending.store(true, std::memory_order_release);\n""",
        "latch exact DOWN point before motion/up",
    )

    replace_once(
        input_cpp,
        """    touchpadEventX.store(0, std::memory_order_relaxed);\n    touchpadEventY.store(0, std::memory_order_relaxed);\n\n    joystick = nullptr;\n""",
        """    touchpadEventX.store(0, std::memory_order_relaxed);\n    touchpadEventY.store(0, std::memory_order_relaxed);\n    touchpadTapX.store(0, std::memory_order_relaxed);\n    touchpadTapY.store(0, std::memory_order_relaxed);\n\n    joystick = nullptr;\n""",
        "initialize exact fast-tap coordinates",
    )

    replace_once(
        input_cpp,
        """            touchpadX = static_cast<melonDS::u16>(touchpadEventX.load(std::memory_order_relaxed));\n            touchpadY = static_cast<melonDS::u16>(touchpadEventY.load(std::memory_order_relaxed));\n            touchpadTouching = true;\n        }\n""",
        """            touchpadX = static_cast<melonDS::u16>(touchpadTapX.load(std::memory_order_relaxed));\n            touchpadY = static_cast<melonDS::u16>(touchpadTapY.load(std::memory_order_relaxed));\n            touchpadTouching = true;\n        }\n""",
        "use exact DOWN coordinate for sub-poll tap",
    )

    print("strict fast-tap DOWN-coordinate refinement applied successfully")


if __name__ == "__main__":
    main()
