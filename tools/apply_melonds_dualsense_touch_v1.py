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

    # Strict-stylus design:
    # - the selected DualSense/DS4 touchpad is the DS touchscreen surface
    # - finger down/move/up is the DS stylus down/move/up
    # - absolute 1:1 normalized mapping; no mouse-like relative motion
    # - each emulator instance owns its selected controller
    # - SDL touchpad DOWN/MOTION/UP events are latched so a very fast tap cannot
    #   disappear simply because it began and ended between two input polls.

    replace_once(
        header,
        "#include <SDL2/SDL.h>\n",
        "#include <SDL2/SDL.h>\n#include <atomic>\n",
        "atomic support for strict touch events",
    )

    replace_once(
        header,
        """    void openJoystick();\n    void closeJoystick();\n    bool joystickButtonDown(int val);\n\n    void inputProcess();\n""",
        """    void openJoystick();\n    void closeJoystick();\n    bool joystickButtonDown(int val);\n\n    static int SDLCALL controllerTouchpadEventWatch(void* userdata, SDL_Event* event);\n    void inputProcess();\n""",
        "declare controller touchpad event watcher",
    )

    replace_once(
        header,
        """    bool isTouching;\n    melonDS::u16 touchX, touchY;\n""",
        """    bool isTouching;\n    melonDS::u16 touchX, touchY;\n\n    // WW97 strict stylus: the selected PlayStation controller touchpad becomes\n    // the complete native DS touchscreen surface. These are the values consumed\n    // by the NDS::TouchScreen path on every emulation input step.\n    bool touchpadAvailable;\n    bool touchpadTouching;\n    melonDS::u16 touchpadX, touchpadY;\n\n    // SDL event-side state is atomic because event-watch callbacks may run while\n    // the emulator thread is between input polls. It also preserves ultra-short\n    // DOWN->UP taps for at least one DS input step instead of silently losing them.\n    std::atomic<int> touchpadJoystickInstanceID;\n    std::atomic<bool> touchpadEventDown;\n    std::atomic<bool> touchpadTapPending;\n    std::atomic<int> touchpadEventX;\n    std::atomic<int> touchpadEventY;\n""",
        "EmuInstance strict touchpad state",
    )

    replace_once(
        input_cpp,
        """std::shared_ptr<SDL_mutex> EmuInstance::joyMutexGlobal = nullptr;\n\n\nvoid EmuInstance::inputInit()\n""",
        """std::shared_ptr<SDL_mutex> EmuInstance::joyMutexGlobal = nullptr;\n\n\nstatic inline int ww97MapTouchAxis(float value, int maximum)\n{\n    // SDL exposes a normalized absolute position. Mapping each axis independently\n    // makes the entire physical touchpad equal the entire 256x192 DS touchscreen.\n    if (value < 0.0f) value = 0.0f;\n    if (value > 1.0f) value = 1.0f;\n    int out = static_cast<int>(value * static_cast<float>(maximum) + 0.5f);\n    if (out < 0) out = 0;\n    if (out > maximum) out = maximum;\n    return out;\n}\n\nint SDLCALL EmuInstance::controllerTouchpadEventWatch(void* userdata, SDL_Event* event)\n{\n    if (!userdata || !event) return 0;\n    if (event->type != SDL_CONTROLLERTOUCHPADDOWN &&\n        event->type != SDL_CONTROLLERTOUCHPADMOTION &&\n        event->type != SDL_CONTROLLERTOUCHPADUP)\n        return 0;\n\n    EmuInstance* inst = static_cast<EmuInstance*>(userdata);\n    const int wanted = inst->touchpadJoystickInstanceID.load(std::memory_order_relaxed);\n    if (wanted < 0 || static_cast<int>(event->ctouchpad.which) != wanted) return 0;\n    if (event->ctouchpad.touchpad != 0 || event->ctouchpad.finger != 0) return 0;\n\n    const int x = ww97MapTouchAxis(event->ctouchpad.x, 255);\n    const int y = ww97MapTouchAxis(event->ctouchpad.y, 191);\n    inst->touchpadEventX.store(x, std::memory_order_relaxed);\n    inst->touchpadEventY.store(y, std::memory_order_relaxed);\n\n    if (event->type == SDL_CONTROLLERTOUCHPADDOWN)\n    {\n        inst->touchpadEventDown.store(true, std::memory_order_release);\n        // Keep a one-input-step tap latched until inputProcess consumes it.\n        inst->touchpadTapPending.store(true, std::memory_order_release);\n    }\n    else if (event->type == SDL_CONTROLLERTOUCHPADMOTION)\n    {\n        inst->touchpadEventDown.store(true, std::memory_order_release);\n    }\n    else\n    {\n        inst->touchpadEventDown.store(false, std::memory_order_release);\n    }\n\n    return 0;\n}\n\n\nvoid EmuInstance::inputInit()\n""",
        "strict absolute touch mapper and event latch",
    )

    replace_once(
        input_cpp,
        """    isTouching = false;\n    touchX = 0;\n    touchY = 0;\n\n    joystick = nullptr;\n""",
        """    isTouching = false;\n    touchX = 0;\n    touchY = 0;\n\n    touchpadAvailable = false;\n    touchpadTouching = false;\n    touchpadX = 0;\n    touchpadY = 0;\n    touchpadJoystickInstanceID.store(-1, std::memory_order_relaxed);\n    touchpadEventDown.store(false, std::memory_order_relaxed);\n    touchpadTapPending.store(false, std::memory_order_relaxed);\n    touchpadEventX.store(0, std::memory_order_relaxed);\n    touchpadEventY.store(0, std::memory_order_relaxed);\n\n    joystick = nullptr;\n""",
        "initialize strict touchpad state",
    )

    replace_once(
        input_cpp,
        """    inputLoadConfig();\n}\n\nvoid EmuInstance::inputDeInit()\n{\n    SDL_LockMutex(joyMutex.get());\n""",
        """    inputLoadConfig();\n    SDL_AddEventWatch(&EmuInstance::controllerTouchpadEventWatch, this);\n}\n\nvoid EmuInstance::inputDeInit()\n{\n    SDL_DelEventWatch(&EmuInstance::controllerTouchpadEventWatch, this);\n    touchpadJoystickInstanceID.store(-1, std::memory_order_release);\n    touchpadEventDown.store(false, std::memory_order_release);\n    touchpadTapPending.store(false, std::memory_order_release);\n    SDL_LockMutex(joyMutex.get());\n""",
        "install and remove per-instance SDL touchpad watcher",
    )

    replace_once(
        input_cpp,
        """    if (num < 1)\n    {\n        controller = nullptr;\n        joystick = nullptr;\n        hasRumble = false;\n""",
        """    if (num < 1)\n    {\n        controller = nullptr;\n        joystick = nullptr;\n        touchpadJoystickInstanceID.store(-1, std::memory_order_release);\n        touchpadEventDown.store(false, std::memory_order_release);\n        touchpadTapPending.store(false, std::memory_order_release);\n        hasRumble = false;\n""",
        "clear strict touch identity with no joystick",
    )

    replace_once(
        input_cpp,
        """    joystick = SDL_JoystickOpen(joystickID);\n\n    if (SDL_IsGameController(joystickID))\n""",
        """    joystick = SDL_JoystickOpen(joystickID);\n    touchpadJoystickInstanceID.store(joystick ? static_cast<int>(SDL_JoystickInstanceID(joystick)) : -1,\n                                     std::memory_order_release);\n    touchpadEventDown.store(false, std::memory_order_release);\n    touchpadTapPending.store(false, std::memory_order_release);\n\n    if (SDL_IsGameController(joystickID))\n""",
        "bind touch events to selected controller instance",
    )

    replace_once(
        input_cpp,
        """void EmuInstance::closeJoystick()\n{\n    if (controller)\n""",
        """void EmuInstance::closeJoystick()\n{\n    touchpadJoystickInstanceID.store(-1, std::memory_order_release);\n    touchpadEventDown.store(false, std::memory_order_release);\n    touchpadTapPending.store(false, std::memory_order_release);\n    touchpadAvailable = false;\n    touchpadTouching = false;\n\n    if (controller)\n""",
        "release strict touch state on controller close",
    )

    replace_once(
        input_cpp,
        """    SDL_LockMutex(joyMutex.get());\n    SDL_JoystickUpdate();\n\n    if (joystick)\n""",
        """    SDL_LockMutex(joyMutex.get());\n    // Preserve melonDS joystick behavior and explicitly refresh SDL controller\n    // state so absolute PlayStation touchpad coordinates are current.\n    SDL_JoystickUpdate();\n    SDL_GameControllerUpdate();\n\n    if (joystick)\n""",
        "refresh SDL controller state",
    )

    replace_once(
        input_cpp,
        """    if (!joystick && (SDL_NumJoysticks() > 0))\n    {\n        openJoystick();\n    }\n\n    joyInputMask = 0xFFF;\n""",
        """    if (!joystick && (SDL_NumJoysticks() > 0))\n    {\n        openJoystick();\n    }\n\n    // WW97 STRICT DS STYLUS MODE\n    // If this instance's selected controller has a touchpad, that touchpad is the\n    // DS touchscreen. No click is required. There is no cursor, acceleration,\n    // dead-zone or relative movement. Full pad X/Y maps directly to 0..255/0..191.\n    touchpadAvailable = (controller && SDL_GameControllerGetNumTouchpads(controller) > 0);\n    touchpadTouching = false;\n\n    if (touchpadAvailable)\n    {\n        Uint8 state = 0;\n        float x = 0.0f;\n        float y = 0.0f;\n        float pressure = 0.0f;\n        const bool polledDown =\n            (SDL_GameControllerGetTouchpadFinger(controller, 0, 0,\n                                                 &state, &x, &y, &pressure) == 0 && state);\n\n        if (polledDown)\n        {\n            touchpadX = static_cast<melonDS::u16>(ww97MapTouchAxis(x, 255));\n            touchpadY = static_cast<melonDS::u16>(ww97MapTouchAxis(y, 191));\n            touchpadTouching = true;\n            // A normal held touch has now been observed; its DOWN latch is no\n            // longer needed. Movement remains continuous through live polling.\n            touchpadTapPending.store(false, std::memory_order_release);\n        }\n        else if (touchpadEventDown.load(std::memory_order_acquire))\n        {\n            // Event-state fallback keeps drag/hold semantics intact even if a\n            // particular SDL HID backend momentarily fails its direct state query.\n            touchpadX = static_cast<melonDS::u16>(touchpadEventX.load(std::memory_order_relaxed));\n            touchpadY = static_cast<melonDS::u16>(touchpadEventY.load(std::memory_order_relaxed));\n            touchpadTouching = true;\n            touchpadTapPending.store(false, std::memory_order_release);\n        }\n        else if (touchpadTapPending.exchange(false, std::memory_order_acq_rel))\n        {\n            // DOWN and UP both happened between two emulator polls. Emit exactly\n            // one DS input step at the DOWN coordinate so a real quick tap is not\n            // lost merely because of host-side scheduling. Next poll releases it.\n            touchpadX = static_cast<melonDS::u16>(touchpadEventX.load(std::memory_order_relaxed));\n            touchpadY = static_cast<melonDS::u16>(touchpadEventY.load(std::memory_order_relaxed));\n            touchpadTouching = true;\n        }\n    }\n    else\n    {\n        touchpadEventDown.store(false, std::memory_order_release);\n        touchpadTapPending.store(false, std::memory_order_release);\n    }\n\n    joyInputMask = 0xFFF;\n""",
        "strict per-instance absolute controller touchpad polling and tap latch",
    )

    # The controller touchpad is exclusive whenever available. This means the
    # physical touchpad itself is the DS touchscreen surface; mouse input cannot
    # accidentally inject a second stylus source into the same DS instance.
    replace_once(
        thread_cpp,
        """            if (emuInstance->isTouching)\n                emuInstance->nds->TouchScreen(emuInstance->touchX, emuInstance->touchY);\n            else\n                emuInstance->nds->ReleaseScreen();\n""",
        """            if (emuInstance->touchpadAvailable)\n            {\n                if (emuInstance->touchpadTouching)\n                    emuInstance->nds->TouchScreen(emuInstance->touchpadX, emuInstance->touchpadY);\n                else\n                    emuInstance->nds->ReleaseScreen();\n            }\n            else if (emuInstance->isTouching)\n            {\n                emuInstance->nds->TouchScreen(emuInstance->touchX, emuInstance->touchY);\n            }\n            else\n            {\n                emuInstance->nds->ReleaseScreen();\n            }\n""",
        "exclusive strict touchpad dispatch into native DS stylus path",
    )

    # Force SDL HIDAPI for PlayStation controllers so touchpad reports are exposed
    # over both USB and Bluetooth when the SDL backend supports the device.
    replace_once(
        main_cpp,
        """    // http://stackoverflow.com/questions/14543333/joystick-wont-work-using-sdl\n    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, \"1\");\n\n    SDL_SetHint(SDL_HINT_APP_NAME, \"melonDS\");\n""",
        """    // http://stackoverflow.com/questions/14543333/joystick-wont-work-using-sdl\n    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, \"1\");\n\n    // WW97 DualSense Touch V1 - strict DS stylus mode.\n    // Keep PlayStation HIDAPI enabled so SDL exposes touchpad absolute position\n    // and DOWN/MOTION/UP reports over supported USB/Bluetooth connections.\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI\", \"1\");\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI_PS4\", \"1\");\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI_PS5\", \"1\");\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI_PS4_RUMBLE\", \"1\");\n    SDL_SetHint(\"SDL_JOYSTICK_HIDAPI_PS5_RUMBLE\", \"1\");\n\n    SDL_SetHint(SDL_HINT_APP_NAME, \"melonDS\");\n""",
        "PlayStation HIDAPI hints",
    )

    replace_once(
        main_cpp,
        """    printf(\"melonDS \" MELONDS_VERSION \"\\n\");\n    printf(MELONDS_URL \"\\n\");\n""",
        """    printf(\"melonDS \" MELONDS_VERSION \"\\n\");\n    printf(MELONDS_URL \"\\n\");\n    printf(\"DualSense Touch Edition V1 - STRICT 1:1 DS stylus mapping\\n\");\n""",
        "custom build marker",
    )

    print("melonDS DualSense Touch Edition V1 STRICT stylus patch applied successfully")


if __name__ == "__main__":
    main()
