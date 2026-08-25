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
        raise SystemExit("usage: apply_melonds_dualsense_touch_v1.py <melonDS-source-root>")

    root = Path(sys.argv[1]).resolve()
    header = root / "src/frontend/qt_sdl/EmuInstance.h"
    input_cpp = root / "src/frontend/qt_sdl/EmuInstanceInput.cpp"
    thread_cpp = root / "src/frontend/qt_sdl/EmuThread.cpp"
    main_cpp = root / "src/frontend/qt_sdl/main.cpp"

    for path in (header, input_cpp, thread_cpp, main_cpp):
        if not path.is_file():
            raise FileNotFoundError(path)

    # Keep mouse/stylus state independent from the controller touchpad state.
    replace_once(
        header,
        """    bool isTouching;\n    melonDS::u16 touchX, touchY;\n""",
        """    bool isTouching;\n    melonDS::u16 touchX, touchY;\n\n    // DualSense/DS4 absolute touchpad -> DS touchscreen.\n    // Kept separate from mouse touch so either source can be used.\n    bool touchpadTouching;\n    melonDS::u16 touchpadX, touchpadY;\n""",
        "EmuInstance touchpad state",
    )

    replace_once(
        input_cpp,
        """    isTouching = false;\n    touchX = 0;\n    touchY = 0;\n\n    joystick = nullptr;\n""",
        """    isTouching = false;\n    touchX = 0;\n    touchY = 0;\n    touchpadTouching = false;\n    touchpadX = 0;\n    touchpadY = 0;\n\n    joystick = nullptr;\n""",
        "initialize touchpad state",
    )

    # Poll the touchpad from the controller ALREADY selected for this emulator
    # instance. This is the critical difference from PR #2682, which always opens
    # controller index 0 and therefore cannot safely serve four players.
    replace_once(
        input_cpp,
        """    SDL_LockMutex(joyMutex.get());\n    SDL_JoystickUpdate();\n\n    if (joystick)\n""",
        """    SDL_LockMutex(joyMutex.get());\n    // Pump SDL HID state while holding melonDS' global joystick mutex.\n    // Each EmuInstance then reads its own selected SDL_GameController.\n    SDL_PumpEvents();\n    SDL_JoystickUpdate();\n\n    if (joystick)\n""",
        "pump SDL HID state",
    )

    replace_once(
        input_cpp,
        """    if (!joystick && (SDL_NumJoysticks() > 0))\n    {\n        openJoystick();\n    }\n\n    joyInputMask = 0xFFF;\n""",
        """    if (!joystick && (SDL_NumJoysticks() > 0))\n    {\n        openJoystick();\n    }\n\n    // WW97 DualSense Touch V1:\n    // Absolute 1:1 mapping from the selected controller's first touchpad/finger\n    // to the native Nintendo DS touchscreen coordinate space (256x192).\n    touchpadTouching = false;\n    if (controller && SDL_GameControllerGetNumTouchpads(controller) > 0)\n    {\n        Uint8 state = 0;\n        float x = 0.0f;\n        float y = 0.0f;\n        float pressure = 0.0f;\n\n        if (SDL_GameControllerGetTouchpadFinger(controller, 0, 0,\n                                                &state, &x, &y, &pressure) == 0 && state)\n        {\n            int dsX = static_cast<int>(x * 255.0f + 0.5f);\n            int dsY = static_cast<int>(y * 191.0f + 0.5f);\n\n            if (dsX < 0) dsX = 0;\n            if (dsX > 255) dsX = 255;\n            if (dsY < 0) dsY = 0;\n            if (dsY > 191) dsY = 191;\n\n            touchpadX = static_cast<melonDS::u16>(dsX);\n            touchpadY = static_cast<melonDS::u16>(dsY);\n            touchpadTouching = true;\n        }\n    }\n\n    joyInputMask = 0xFFF;\n""",
        "per-instance absolute controller touchpad polling",
    )

    # Prefer the player's touchpad while a finger is down, otherwise retain the
    # normal mouse/touch behavior. This also guarantees an immediate Stylus-Up.
    replace_once(
        thread_cpp,
        """            if (emuInstance->isTouching)\n                emuInstance->nds->TouchScreen(emuInstance->touchX, emuInstance->touchY);\n            else\n                emuInstance->nds->ReleaseScreen();\n""",
        """            if (emuInstance->touchpadTouching)\n                emuInstance->nds->TouchScreen(emuInstance->touchpadX, emuInstance->touchpadY);\n            else if (emuInstance->isTouching)\n                emuInstance->nds->TouchScreen(emuInstance->touchX, emuInstance->touchY);\n            else\n                emuInstance->nds->ReleaseScreen();\n""",
        "touchpad priority in DS stylus dispatch",
    )

    # Force SDL HIDAPI for PlayStation controllers so the extra HID features
    # (including touchpad data) are exposed over USB/Bluetooth when supported.
    replace_once(
        main_cpp,
        """    // http://stackoverflow.com/questions/14543333/joystick-wont-work-using-sdl\n    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, \"1\");\n\n    SDL_SetHint(SDL_HINT_APP_NAME, \"melonDS\");\n""",
        """    // http://stackoverflow.com/questions/14543333/joystick-wont-work-using-sdl\n    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, \"1\");\n\n    // WW97 DualSense Touch V1 - enable PlayStation HIDAPI feature reports.\n    // String keys are used intentionally to remain source-compatible with\n    // different SDL2 header revisions.\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI\", \"1\");\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI_PS4\", \"1\");\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI_PS5\", \"1\");\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI_PS4_RUMBLE\", \"1\");\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI_PS5_RUMBLE\", \"1\");\n\n    SDL_SetHint(SDL_HINT_APP_NAME, \"melonDS\");\n""",
        "PlayStation HIDAPI hints",
    )

    replace_once(
        main_cpp,
        """    printf(\"melonDS \" MELONDS_VERSION \"\\n\");\n    printf(MELONDS_URL \"\\n\");\n""",
        """    printf(\"melonDS \" MELONDS_VERSION \"\\n\");\n    printf(MELONDS_URL \"\\n\");\n    printf(\"DualSense Touch Edition V1 - per-instance absolute DS touchscreen mapping\\n\");\n""",
        "custom build marker",
    )

    print("melonDS DualSense Touch Edition V1 patch applied successfully")


if __name__ == "__main__":
    main()
