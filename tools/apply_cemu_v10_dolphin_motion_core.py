from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_cemu_v10_dolphin_motion_core.py <cemu-source-root>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {label}")


def regex_replace_once(path: Path, pattern: str, repl: str, label: str):
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    path.write_text(new_text, encoding="utf-8")
    print(f"Patched {path}: {label}")


def replace_function(path: Path, signature: str, replacement: str, label: str):
    text = path.read_text(encoding="utf-8")
    start = text.find(signature)
    if start < 0:
        raise RuntimeError(f"{label}: signature not found")
    brace = text.find("{", start + len(signature))
    if brace < 0:
        raise RuntimeError(f"{label}: opening brace not found")
    depth = 0
    end = None
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise RuntimeError(f"{label}: closing brace not found")
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
    print(f"Patched {path}: {label}")


# =============================================================================
# Cemu Joy-Con V10: Dolphin 2606a motion core compatibility layer
# Reference behavior:
#   Dolphin c77bbaa0f372c3f72281602a8b087206706542cb (2606a)
#   User-tested Joy-Con patch WorldWide97/dolphin-joycon-fix fb80816...
#
# Important architecture:
#   1) SDL mini-gamepad sensors are normalized back to the Joy-Con native frame.
#   2) A pre-orientation Dolphin semantic IMU stream feeds the pointer.
#   3) General Wii Remote motion receives the user's proven R Sideways 180-degree
#      Z rotation only AFTER the pointer stream has been captured.
#   4) Gyro bias calibration matches Dolphin: 2 deg/s deadzone, 3 s stable mean,
#      and a >=25 Hz calibration update requirement.
# =============================================================================

provider_h = root / "src/input/api/SDL/SDLControllerProvider.h"
provider_cpp = root / "src/input/api/SDL/SDLControllerProvider.cpp"
controller_h = root / "src/input/api/SDL/SDLController.h"
controller_cpp = root / "src/input/api/SDL/SDLController.cpp"

# -----------------------------------------------------------------------------
# Provider API/state: expose the exact pre-orientation Dolphin IMU stream used by
# the IMU cursor. General Cemu motion remains a separate output stream.
# -----------------------------------------------------------------------------
replace_once(
    provider_h,
    '''\tMotionSample motion_sample(SDL_JoystickID diid);\n''',
    '''\tMotionSample motion_sample(SDL_JoystickID diid);\n\tbool dolphin_pointer_motion(SDL_JoystickID diid, glm::vec3& gyro, glm::vec3& accel, uint64& timestamp);\n''',
    "Dolphin pointer motion provider API",
)

replace_once(
    provider_h,
    '''\t\tMotionInfoTracking tracking;\n\n\t\tMotionState() = default;\n''',
    '''\t\tMotionInfoTracking tracking;\n\n\t\t// Dolphin 2606a-compatible IMU state. The pointer stream is captured\n\t\t// before emulated Wiimote orientation (including the R 180-degree fix).\n\t\tglm::vec3 dolphin_pointer_gyro{};\n\t\tglm::vec3 dolphin_pointer_acc{};\n\t\tuint64 dolphin_pointer_timestamp{};\n\t\tbool dolphin_pointer_has_gyro{};\n\t\tbool dolphin_pointer_has_acc{};\n\n\t\t// Dolphin IMUGyroscope stable-mean calibration state.\n\t\tglm::vec3 dolphin_gyro_bias{};\n\t\tglm::vec3 dolphin_calibration_sum{};\n\t\tuint64 dolphin_calibration_count{};\n\t\tuint64 dolphin_calibration_start{};\n\t\tbool dolphin_calibration_initialized{};\n\n\t\tMotionState() = default;\n''',
    "Dolphin gyro calibration and pointer state",
)

replace_once(
    provider_cpp,
    '''MotionSample SDLControllerProvider::motion_sample(SDL_JoystickID diid)\n{\n\tstd::shared_lock lock(s_mutex);\n\tauto it = s_motion_states.find(diid);\n\treturn (it != s_motion_states.end()) ? it->second.data : MotionSample{};\n}\n''',
    '''MotionSample SDLControllerProvider::motion_sample(SDL_JoystickID diid)\n{\n\tstd::shared_lock lock(s_mutex);\n\tauto it = s_motion_states.find(diid);\n\treturn (it != s_motion_states.end()) ? it->second.data : MotionSample{};\n}\n\nbool SDLControllerProvider::dolphin_pointer_motion(SDL_JoystickID diid, glm::vec3& gyro, glm::vec3& accel, uint64& timestamp)\n{\n\tstd::shared_lock lock(s_mutex);\n\tconst auto it = s_motion_states.find(diid);\n\tif (it == s_motion_states.end() || !it->second.dolphin_pointer_has_gyro || !it->second.dolphin_pointer_has_acc)\n\t\treturn false;\n\tgyro = it->second.dolphin_pointer_gyro;\n\taccel = it->second.dolphin_pointer_acc;\n\ttimestamp = it->second.dolphin_pointer_timestamp;\n\treturn timestamp != 0;\n}\n''',
    "Dolphin pointer motion provider implementation",
)

# Remove all V6/V8/V9 sensor-coordinate experimentation in one shot. Normalize
# every standalone Joy-Con back to the same native/vertical SDL frame, exactly as
# the user's Dolphin build does with SDL_JOYSTICK_HIDAPI_VERTICAL_JOY_CONS=1.
# The Cemu Vertical/Sideways selector remains for button layout and for deciding
# whether the proven R 180-degree Wiimote orientation fix is active.
pattern = r'''\t\t\t// SDL reports each standalone Joy-Con in horizontal mini-gamepad coordinates\..*?\n\t\t\tif \(event\.gsensor\.sensor == SDL_SENSOR_ACCEL\)'''
replacement = '''\t\t\t// V10 Dolphin 2606a sensor basis. SDL is intentionally kept in Cemu's\n\t\t\t// independent mini-gamepad mode, then converted here back to the same native\n\t\t\t// Joy-Con frame seen by the user's Dolphin build (VERTICAL_JOY_CONS=1).\n\t\t\tbool v10_is_joycon = false;\n\t\t\tbool v10_right_sideways = false;\n\t\t\tfloat v10_native[3] = { sensor_data[0], sensor_data[1], sensor_data[2] };\n\t\t\tif (const auto config = s_joycon_orientation_states.find(id);\n\t\t\t\tconfig != s_joycon_orientation_states.end())\n\t\t\t{\n\t\t\t\tv10_is_joycon = true;\n\t\t\t\tv10_right_sideways = !config->second.is_left && !config->second.vertical;\n\t\t\t\tconst float x = sensor_data[0];\n\t\t\t\tconst float y = sensor_data[1];\n\t\t\t\tconst float z = sensor_data[2];\n\t\t\t\tif (config->second.is_left)\n\t\t\t\t{\n\t\t\t\t\t// Inverse of SDL L mini mapping: native -> (z,y,-x).\n\t\t\t\t\tv10_native[0] = -z;\n\t\t\t\t\tv10_native[1] = y;\n\t\t\t\t\tv10_native[2] = x;\n\t\t\t\t}\n\t\t\t\telse\n\t\t\t\t{\n\t\t\t\t\t// Inverse of SDL R mini mapping: native -> (-z,y,x).\n\t\t\t\t\tv10_native[0] = z;\n\t\t\t\t\tv10_native[1] = y;\n\t\t\t\t\tv10_native[2] = -x;\n\t\t\t\t}\n\t\t\t}\n\n\t\t\tif (event.gsensor.sensor == SDL_SENSOR_ACCEL)'''
regex_replace_once(provider_cpp, pattern, replacement, "replace V6-V9 sensor transforms with Dolphin native Joy-Con basis")

# Accelerometer: Dolphin IMUAccelerometer semantic axes are
#   X = Left-Right = -SDL X, Y = Backward-Forward = SDL Z, Z = Up-Down = SDL Y.
# Cemu stores g units, so divide by gravity. Capture pointer data before R fix;
# then apply the exact high-level R Sideways 180-degree Z rotation to general motion.
replace_once(
    provider_cpp,
    '''\t\t\t\ttracking.acc[0] = -sensor_data[0] / 9.81f;\n\t\t\t\ttracking.acc[1] = -sensor_data[1] / 9.81f;\n\t\t\t\ttracking.acc[2] = -sensor_data[2] / 9.81f;\n\t\t\t\ttracking.hasAcc = true;\n''',
    '''\t\t\t\tif (v10_is_joycon)\n\t\t\t\t{\n\t\t\t\t\tglm::vec3 dolphin_acc{ -v10_native[0] / 9.81f, v10_native[2] / 9.81f, v10_native[1] / 9.81f };\n\t\t\t\t\tstate.dolphin_pointer_acc = dolphin_acc;\n\t\t\t\t\tstate.dolphin_pointer_has_acc = true;\n\t\t\t\t\t// User-tested Dolphin patch: a standalone 180-degree Z turn for R\n\t\t\t\t\t// in natural Sideways orientation. Pointer stream intentionally bypasses it.\n\t\t\t\t\tif (v10_right_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tdolphin_acc.x = -dolphin_acc.x;\n\t\t\t\t\t\tdolphin_acc.y = -dolphin_acc.y;\n\t\t\t\t\t}\n\t\t\t\t\ttracking.acc = dolphin_acc;\n\t\t\t\t}\n\t\t\t\telse\n\t\t\t\t{\n\t\t\t\t\ttracking.acc[0] = -sensor_data[0] / 9.81f;\n\t\t\t\t\ttracking.acc[1] = -sensor_data[1] / 9.81f;\n\t\t\t\t\ttracking.acc[2] = -sensor_data[2] / 9.81f;\n\t\t\t\t}\n\t\t\t\ttracking.hasAcc = true;\n''',
    "Dolphin accelerometer semantic mapping and R 180 output fix",
)

# Gyroscope: same semantic mapping as Dolphin IMUGyroscope, then reproduce its
# 3-second stable mean calibration and 2 deg/s per-component deadzone.
replace_once(
    provider_cpp,
    '''\t\t\t\ttracking.gyro[0] = sensor_data[0];\n\t\t\t\ttracking.gyro[1] = -sensor_data[1];\n\t\t\t\ttracking.gyro[2] = -sensor_data[2];\n\t\t\t\ttracking.hasGyro = true;\n''',
    '''\t\t\t\tif (v10_is_joycon)\n\t\t\t\t{\n\t\t\t\t\tconstexpr float kDolphinGyroDeadzone = 2.0f * 3.14159265358979323846f / 180.0f;\n\t\t\t\t\tconstexpr uint64 kDolphinCalibrationPeriodNs = 3000000000ULL;\n\t\t\t\t\tconstexpr double kDolphinMinCalibrationHz = 25.0;\n\t\t\t\t\tglm::vec3 raw_gyro{ -v10_native[0], v10_native[2], v10_native[1] };\n\n\t\t\t\t\tauto restart_calibration = [&]() {\n\t\t\t\t\t\tstate.dolphin_calibration_start = ts;\n\t\t\t\t\t\tstate.dolphin_calibration_sum = raw_gyro;\n\t\t\t\t\t\tstate.dolphin_calibration_count = 1;\n\t\t\t\t\t};\n\n\t\t\t\t\tif (state.dolphin_calibration_count == 0)\n\t\t\t\t\t{\n\t\t\t\t\t\t// Dolphin immediately uses the first observed value as a useful bias\n\t\t\t\t\t\t// until a full stable calibration period is available.\n\t\t\t\t\t\tif (!state.dolphin_calibration_initialized)\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\tstate.dolphin_gyro_bias = raw_gyro;\n\t\t\t\t\t\t\tstate.dolphin_calibration_initialized = true;\n\t\t\t\t\t\t}\n\t\t\t\t\t\trestart_calibration();\n\t\t\t\t\t}\n\t\t\t\t\telse\n\t\t\t\t\t{\n\t\t\t\t\t\tconst uint64 elapsed_ns = ts - state.dolphin_calibration_start;\n\t\t\t\t\t\tconst double elapsed_s = static_cast<double>(elapsed_ns) / 1000000000.0;\n\t\t\t\t\t\tconst glm::vec3 mean = state.dolphin_calibration_sum / static_cast<float>(state.dolphin_calibration_count);\n\t\t\t\t\t\tconst glm::vec3 difference = raw_gyro - mean;\n\t\t\t\t\t\tconst double frequency = elapsed_s > 0.0 ? static_cast<double>(state.dolphin_calibration_count) / elapsed_s : kDolphinMinCalibrationHz;\n\t\t\t\t\t\tconst bool unstable = std::abs(difference.x) > kDolphinGyroDeadzone ||\n\t\t\t\t\t\t\tstd::abs(difference.y) > kDolphinGyroDeadzone ||\n\t\t\t\t\t\t\tstd::abs(difference.z) > kDolphinGyroDeadzone ||\n\t\t\t\t\t\t\tfrequency < kDolphinMinCalibrationHz;\n\t\t\t\t\t\tif (unstable)\n\t\t\t\t\t\t\trestart_calibration();\n\t\t\t\t\t\telse\n\t\t\t\t\t\t{\n\t\t\t\t\t\t\tstate.dolphin_calibration_sum += raw_gyro;\n\t\t\t\t\t\t\t++state.dolphin_calibration_count;\n\t\t\t\t\t\t\tif (elapsed_ns >= kDolphinCalibrationPeriodNs)\n\t\t\t\t\t\t\t\tstate.dolphin_gyro_bias = state.dolphin_calibration_sum / static_cast<float>(state.dolphin_calibration_count);\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\n\t\t\t\t\tglm::vec3 dolphin_gyro = raw_gyro - state.dolphin_gyro_bias;\n\t\t\t\t\tif (std::abs(dolphin_gyro.x) <= kDolphinGyroDeadzone) dolphin_gyro.x = 0.0f;\n\t\t\t\t\tif (std::abs(dolphin_gyro.y) <= kDolphinGyroDeadzone) dolphin_gyro.y = 0.0f;\n\t\t\t\t\tif (std::abs(dolphin_gyro.z) <= kDolphinGyroDeadzone) dolphin_gyro.z = 0.0f;\n\n\t\t\t\t\tstate.dolphin_pointer_gyro = dolphin_gyro;\n\t\t\t\t\tstate.dolphin_pointer_timestamp = ts;\n\t\t\t\t\tstate.dolphin_pointer_has_gyro = true;\n\t\t\t\t\tif (v10_right_sideways)\n\t\t\t\t\t{\n\t\t\t\t\t\tdolphin_gyro.x = -dolphin_gyro.x;\n\t\t\t\t\t\tdolphin_gyro.y = -dolphin_gyro.y;\n\t\t\t\t\t}\n\t\t\t\t\ttracking.gyro = dolphin_gyro;\n\t\t\t\t}\n\t\t\t\telse\n\t\t\t\t{\n\t\t\t\t\ttracking.gyro[0] = sensor_data[0];\n\t\t\t\t\ttracking.gyro[1] = -sensor_data[1];\n\t\t\t\t\ttracking.gyro[2] = -sensor_data[2];\n\t\t\t\t}\n\t\t\t\ttracking.hasGyro = true;\n''',
    "Dolphin gyroscope semantic mapping calibration deadzone and R 180 output fix",
)

# The Joy-Con tracking vectors are already in the final Dolphin semantic basis.
# Preserve upstream Cemu behavior for every non-Joy-Con controller.
replace_once(
    provider_cpp,
    '''\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n\t\t\t\t\tstate.data = state.handler.getMotionSample();\n''',
    '''\t\t\t\t\tif (s_joycon_orientation_states.contains(id))\n\t\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, tracking.acc.y, tracking.acc.z);\n\t\t\t\t\telse\n\t\t\t\t\t\tstate.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);\n\t\t\t\t\tstate.data = state.handler.getMotionSample();\n''',
    "feed Dolphin semantic Joy-Con vectors directly into Cemu motion adapter",
)

# -----------------------------------------------------------------------------
# SDLController pointer state. This replaces V9's attitude-ray reference with the
# state Dolphin's EmulateIMUCursor actually keeps: a quaternion plus recentered pitch.
# -----------------------------------------------------------------------------
replace_once(
    controller_h,
    '''#include <SDL3/SDL_gamepad.h>\n''',
    '''#include <SDL3/SDL_gamepad.h>\n#include <chrono>\n''',
    "chrono for Dolphin pointer integration",
)
replace_once(
    controller_h,
    '''\tstd::array<float, 9> m_joycon_pointer_reference_attitude{};\n\tglm::vec2 m_joycon_pointer_position{ 0.5f, 0.5f };\n\tglm::vec2 m_joycon_pointer_previous{ 0.5f, 0.5f };\n''',
    '''\t// Dolphin IMUCursorState: rotation of world around device + recentered pitch.\n\tstd::array<float, 4> m_dolphin_pointer_rotation{ 1.0f, 0.0f, 0.0f, 0.0f }; // w,x,y,z\n\tfloat m_dolphin_recentered_pitch = 0.0f;\n\tuint64 m_dolphin_pointer_last_sensor_timestamp = 0;\n\tbool m_dolphin_recenter_requested = true;\n\tglm::vec2 m_joycon_pointer_position{ 0.5f, 0.5f };\n\tglm::vec2 m_joycon_pointer_previous{ 0.5f, 0.5f };\n''',
    "replace V9 attitude ray state with Dolphin IMU cursor state",
)

# Match the user-tested Dolphin settings in fresh Cemu profiles. Existing V9 UI
# fields remain for compatibility, but V10's core constants below are authoritative.
replace_once(
    controller_h,
    '''\tstd::atomic<float> m_pointer_deadzone_degrees{ 0.05f };\n\tstd::atomic<float> m_pointer_smoothing{ 0.0f };\n''',
    '''\tstd::atomic<float> m_pointer_deadzone_degrees{ 2.0f };\n\tstd::atomic<float> m_pointer_smoothing{ 0.01f };\n''',
    "show Dolphin 2 deg/s deadzone and 1 percent accel influence defaults",
)

# Manual Recenter in Dolphin does NOT throw away the integrated pose. It records
# pitch and forces yaw to zero on the next IMU update.
replace_function(
    controller_cpp,
    "void SDLController::recenter_joycon_pointer(bool notify)",
    '''void SDLController::recenter_joycon_pointer(bool notify)\n{\n\t{\n\t\tstd::scoped_lock lock(m_joycon_pointer_mutex);\n\t\tm_dolphin_recenter_requested = true;\n\t\tm_joycon_pointer_previous = m_joycon_pointer_position;\n\t}\n\tif (notify && is_joycon())\n\t{\n\t\tconst char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";\n\t\tLatteOverlay_pushNotification(fmt::format("{} Pointer centered (Dolphin IMU)", side), 1800);\n\t}\n}''',
    "Dolphin-style recenter semantics",
)

# Full Dolphin EmulateIMUCursor reimplementation. We intentionally use the raw
# pre-orientation pointer stream from the provider, not Cemu's Mahony attitude.
replace_function(
    controller_cpp,
    "bool SDLController::update_joycon_pointer(glm::vec2& position, glm::vec2& previous)",
    r'''bool SDLController::update_joycon_pointer(glm::vec2& position, glm::vec2& previous)
{
	if (!is_joycon() || !is_pointer_enabled() || !is_connected() || !has_motion())
		return false;

	glm::vec3 gyro{}, accel{};
	uint64 sensor_timestamp = 0;
	if (!m_provider->dolphin_pointer_motion(m_diid, gyro, accel, sensor_timestamp))
		return false;

	std::scoped_lock lock(m_joycon_pointer_mutex);

	using Q = std::array<float, 4>; // w,x,y,z
	constexpr float kPi = 3.14159265358979323846f;
	constexpr float kDolphinTotalYaw = 25.0f * kPi / 180.0f;
	constexpr float kDolphinVerticalFov = 31.5f * kPi / 180.0f;
	constexpr float kDolphinAccelInfluence = 0.01f; // user's working WiimoteNew.ini

	auto q_normalize = [](Q q) {
		const float length = std::sqrt(q[0]*q[0] + q[1]*q[1] + q[2]*q[2] + q[3]*q[3]);
		if (length <= 0.000001f || !std::isfinite(length)) return Q{1.0f,0.0f,0.0f,0.0f};
		for (float& c : q) c /= length;
		return q;
	};
	auto q_mul = [](const Q& a, const Q& b) {
		return Q{
			a[0]*b[0] - a[1]*b[1] - a[2]*b[2] - a[3]*b[3],
			a[0]*b[1] + a[1]*b[0] + a[2]*b[3] - a[3]*b[2],
			a[0]*b[2] - a[1]*b[3] + a[2]*b[0] + a[3]*b[1],
			a[0]*b[3] + a[1]*b[2] - a[2]*b[1] + a[3]*b[0]
		};
	};
	auto q_axis_angle = [q_normalize](const glm::vec3& rotation_vector) {
		const float angle = glm::length(rotation_vector);
		if (angle <= 0.0000001f || !std::isfinite(angle)) return Q{1.0f,0.0f,0.0f,0.0f};
		const glm::vec3 axis = rotation_vector / angle;
		const float half = angle * 0.5f;
		const float s = std::sin(half);
		return q_normalize(Q{std::cos(half), axis.x*s, axis.y*s, axis.z*s});
	};
	auto q_rotate = [q_mul](const Q& q, const glm::vec3& v) {
		const Q p{0.0f, v.x, v.y, v.z};
		const Q inv{q[0], -q[1], -q[2], -q[3]};
		const Q r = q_mul(q_mul(q, p), inv);
		return glm::vec3{r[1], r[2], r[3]};
	};
	auto q_inverse_rotate = [q_mul](const Q& q, const glm::vec3& v) {
		const Q inv{q[0], -q[1], -q[2], -q[3]};
		const Q p{0.0f, v.x, v.y, v.z};
		const Q r = q_mul(q_mul(inv, p), q);
		return glm::vec3{r[1], r[2], r[3]};
	};
	auto rotate_x = [q_axis_angle](float angle) { return q_axis_angle(glm::vec3{angle,0.0f,0.0f}); };
	auto rotate_z = [q_axis_angle](float angle) { return q_axis_angle(glm::vec3{0.0f,0.0f,angle}); };
	auto get_pitch = [q_rotate](const Q& q) {
		const glm::vec3 v = q_rotate(q, glm::vec3{0.0f,0.0f,1.0f});
		return std::atan2(v.y, std::sqrt(v.x*v.x + v.z*v.z));
	};
	auto get_yaw = [q_inverse_rotate](const Q& q) {
		const glm::vec3 v = q_inverse_rotate(q, glm::vec3{0.0f,1.0f,0.0f});
		return std::atan2(v.x, v.y);
	};

	Q q = m_dolphin_pointer_rotation;
	if (!m_joycon_pointer_initialized)
	{
		q = {1.0f,0.0f,0.0f,0.0f};
		m_dolphin_recentered_pitch = 0.0f;
		m_dolphin_pointer_last_sensor_timestamp = sensor_timestamp;
		m_dolphin_recenter_requested = true;
		m_joycon_pointer_position = {0.5f,0.5f};
		m_joycon_pointer_previous = m_joycon_pointer_position;
		m_joycon_pointer_initialized = true;
	}
	else if (sensor_timestamp > m_dolphin_pointer_last_sensor_timestamp)
	{
		float dt = static_cast<float>(sensor_timestamp - m_dolphin_pointer_last_sensor_timestamp) / 1000000000.0f;
		dt = std::clamp(dt, 0.0005f, 0.05f);
		m_dolphin_pointer_last_sensor_timestamp = sensor_timestamp;

		// Dolphin: GetRotationFromGyroscope(ang_vel * -1 * dt) * rotation.
		const Q gyro_rotation = q_axis_angle(gyro * -dt);
		q = q_mul(gyro_rotation, q);

		// Dolphin complementary filter with the user's 1% accelerometer influence.
		const float accel_len = glm::length(accel);
		if (accel_len > 0.000001f && std::isfinite(accel_len))
		{
			const glm::vec3 normalized_accel = accel / accel_len;
			const glm::vec3 gyro_vec = q_rotate(q, glm::vec3{0.0f,0.0f,1.0f});
			const float cos_angle = std::clamp(glm::dot(normalized_accel, gyro_vec), -1.0f, 1.0f);
			const float abs_cos = std::abs(cos_angle);
			if (abs_cos > 0.0f && abs_cos < 1.0f)
			{
				glm::vec3 axis = glm::cross(gyro_vec, normalized_accel);
				const float axis_len = glm::length(axis);
				if (axis_len > 0.000001f)
				{
					axis /= axis_len;
					const Q correction = q_axis_angle(axis * (std::acos(cos_angle) * kDolphinAccelInfluence));
					q = q_mul(correction, q);
				}
			}
		}

		// Dolphin clamps yaw to half of Total Yaw (25 degrees total).
		const float yaw = get_yaw(q);
		const float max_yaw = kDolphinTotalYaw * 0.5f;
		float target_yaw = std::clamp(yaw, -max_yaw, max_yaw);
		if (m_dolphin_recenter_requested)
		{
			m_dolphin_recentered_pitch = get_pitch(q);
			target_yaw = 0.0f;
			m_dolphin_recenter_requested = false;
		}
		if (yaw != target_yaw)
			q = q_mul(q, rotate_z(target_yaw - yaw));
		q = q_normalize(q);
		m_dolphin_pointer_rotation = q;
	}

	// Dolphin applies recentered pitch when producing the final camera transformation.
	const Q effective = q_normalize(q_mul(q, rotate_x(m_dolphin_recentered_pitch)));
	float yaw = get_yaw(effective);
	float pitch = get_pitch(effective);
	if (get_pointer_invert_x()) yaw = -yaw;
	if (get_pointer_invert_y()) pitch = -pitch;

	const float max_yaw = kDolphinTotalYaw * 0.5f;
	const float max_pitch = kDolphinVerticalFov * 0.5f;
	const glm::vec2 target{
		std::clamp(0.5f + 0.5f * (yaw / max_yaw), 0.0f, 1.0f),
		std::clamp(0.5f + 0.5f * (pitch / max_pitch), 0.0f, 1.0f)
	};

	m_joycon_pointer_previous = m_joycon_pointer_position;
	m_joycon_pointer_position = target; // Dolphin-style direct response: no V9 smoothing.
	position = m_joycon_pointer_position;
	previous = m_joycon_pointer_previous;
	return true;
}''',
    "replace V9 attitude ray with Dolphin EmulateIMUCursor core",
)

# Changing Cemu orientation changes the adapter basis, so it is a hard motion-core
# reset. Manual Recenter remains soft (Dolphin semantics above).
replace_once(
    controller_cpp,
    '''\tm_joycon_orientation.store(orientation, std::memory_order_relaxed);\n\trecenter_joycon_pointer(false);\n''',
    '''\tm_joycon_orientation.store(orientation, std::memory_order_relaxed);\n\t{\n\t\tstd::scoped_lock pointer_lock(m_joycon_pointer_mutex);\n\t\tm_joycon_pointer_initialized = false;\n\t\tm_dolphin_pointer_rotation = {1.0f,0.0f,0.0f,0.0f};\n\t\tm_dolphin_recentered_pitch = 0.0f;\n\t\tm_dolphin_pointer_last_sensor_timestamp = 0;\n\t\tm_dolphin_recenter_requested = true;\n\t}\n''',
    "reset Dolphin motion cursor state on Cemu orientation change",
)

# Old Cemu V8 profile defaults should not silently restore the pre-Dolphin tuning
# when a profile did not explicitly contain these fields.
replace_once(
    controller_cpp,
    '''\tfloat pointer_deadzone = 0.15f;\n\tfloat pointer_smoothing = 0.08f;\n''',
    '''\tfloat pointer_deadzone = 2.0f;\n\tfloat pointer_smoothing = 0.01f;\n''',
    "Dolphin defaults when loading legacy Cemu profiles",
)

print("Cemu Joy-Con V10 Dolphin 2606a motion core compatibility patch applied successfully.")
