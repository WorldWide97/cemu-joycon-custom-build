#include "input/api/SDL/SDLController.h"

#include "input/api/SDL/SDLControllerProvider.h"
#include "Cafe/CafeSystem.h"
#include "Cafe/HW/Latte/Core/LatteOverlay.h"

#include <pugixml.hpp>
#include <sstream>
#include <cmath>

SDLController::SDLController(const SDL_GUID& guid, size_t guid_index)
	: base_type(fmt::format("{}_", guid_index), fmt::format("Controller {}", guid_index + 1)), m_guid_index(guid_index),
	  m_guid(guid)
{
	char tmp[64];
	SDL_GUIDToString(m_guid, tmp, std::size(tmp));
	m_uuid += tmp;
}

SDLController::SDLController(const SDL_GUID& guid, size_t guid_index, std::string_view display_name)
	: base_type(fmt::format("{}_", guid_index), display_name), m_guid_index(guid_index), m_guid(guid)
{
	char tmp[64];
	SDL_GUIDToString(m_guid, tmp, std::size(tmp));
	m_uuid += tmp;
}

SDLController::~SDLController()
{
	if (m_diid >= 0)
		m_provider->clear_joycon_orientation(m_diid);

	if (m_controller)
	{
		SDL_CloseGamepad(m_controller);
		m_controller = nullptr;
	}
}

namespace
{
std::string SerializeJoyConHotkey(const std::vector<uint32>& hotkey)
{
	std::string value;
	for (size_t i = 0; i < hotkey.size(); ++i)
	{
		if (i)
			value.push_back(',');
		value += fmt::format("{}", hotkey[i]);
	}
	return value;
}

std::vector<uint32> ParseJoyConHotkey(std::string_view value)
{
	std::vector<uint32> result;
	std::stringstream stream(std::string{ value });
	std::string token;
	while (std::getline(stream, token, ','))
	{
		if (token.empty())
			continue;
		try
		{
			const auto id = ConvertString<uint32>(token);
			if (id < SDL_GAMEPAD_BUTTON_COUNT)
				result.emplace_back(id);
		}
		catch (...)
		{
		}
	}
	return result;
}
}

bool SDLController::is_left_joycon() const
{
	std::scoped_lock lock(m_controller_mutex);

	// Primary source of truth: SDL3 explicitly distinguishes Joy-Con L and R.
	if (m_controller)
	{
		const auto type = SDL_GetGamepadType(m_controller);
		if (type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT)
			return true;
		if (type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT)
			return false;
	}

	// Robust fallback for saved/unopened SDL controller objects.
	if (m_display_name.find("Joy-Con (L)") != std::string::npos ||
		m_display_name.find("Joy-Con L") != std::string::npos ||
		m_display_name.find("JoyCon (L)") != std::string::npos ||
		m_display_name.find("JoyCon L") != std::string::npos)
		return true;
	if (m_display_name.find("Joy-Con (R)") != std::string::npos ||
		m_display_name.find("Joy-Con R") != std::string::npos ||
		m_display_name.find("JoyCon (R)") != std::string::npos ||
		m_display_name.find("JoyCon R") != std::string::npos)
		return false;

	// Last fallback keeps compatibility with Cemu's historical Nintendo GUIDs.
	return m_guid == kLeftJoyCon;
}

bool SDLController::is_right_joycon() const
{
	std::scoped_lock lock(m_controller_mutex);

	if (m_controller)
	{
		const auto type = SDL_GetGamepadType(m_controller);
		if (type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT)
			return true;
		if (type == SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT)
			return false;
	}

	if (m_display_name.find("Joy-Con (R)") != std::string::npos ||
		m_display_name.find("Joy-Con R") != std::string::npos ||
		m_display_name.find("JoyCon (R)") != std::string::npos ||
		m_display_name.find("JoyCon R") != std::string::npos)
		return true;
	if (m_display_name.find("Joy-Con (L)") != std::string::npos ||
		m_display_name.find("Joy-Con L") != std::string::npos ||
		m_display_name.find("JoyCon (L)") != std::string::npos ||
		m_display_name.find("JoyCon L") != std::string::npos)
		return false;

	return m_guid == kRightJoyCon;
}

void SDLController::normalize_hotkey(std::vector<uint32>& buttons) const
{
	std::erase_if(buttons, [](uint32 id) { return id >= SDL_GAMEPAD_BUTTON_COUNT; });
	std::sort(buttons.begin(), buttons.end());
	buttons.erase(std::unique(buttons.begin(), buttons.end()), buttons.end());
	if (buttons.size() < 2)
		buttons.clear();
}

std::vector<uint32> SDLController::get_vertical_hotkey() const
{
	std::scoped_lock lock(m_controller_mutex);
	return m_vertical_hotkey;
}

std::vector<uint32> SDLController::get_sideways_hotkey() const
{
	std::scoped_lock lock(m_controller_mutex);
	return m_sideways_hotkey;
}

std::vector<uint32> SDLController::get_pointer_hotkey() const
{
	std::scoped_lock lock(m_controller_mutex);
	return m_pointer_hotkey;
}

std::vector<uint32> SDLController::get_pointer_recenter_hotkey() const
{
	std::scoped_lock lock(m_controller_mutex);
	return m_pointer_recenter_hotkey;
}

void SDLController::set_vertical_hotkey(std::vector<uint32> buttons)
{
	normalize_hotkey(buttons);
	std::scoped_lock lock(m_controller_mutex);
	m_vertical_hotkey = std::move(buttons);
	m_vertical_hotkey_latched = false;
}

void SDLController::set_sideways_hotkey(std::vector<uint32> buttons)
{
	normalize_hotkey(buttons);
	std::scoped_lock lock(m_controller_mutex);
	m_sideways_hotkey = std::move(buttons);
	m_sideways_hotkey_latched = false;
}

void SDLController::set_pointer_hotkey(std::vector<uint32> buttons)
{
	normalize_hotkey(buttons);
	std::scoped_lock lock(m_controller_mutex);
	m_pointer_hotkey = std::move(buttons);
	m_pointer_hotkey_latched = false;
}

void SDLController::set_pointer_recenter_hotkey(std::vector<uint32> buttons)
{
	std::erase_if(buttons, [](uint32 id) { return id >= SDL_GAMEPAD_BUTTON_COUNT; });
	std::sort(buttons.begin(), buttons.end());
	buttons.erase(std::unique(buttons.begin(), buttons.end()), buttons.end());
	std::scoped_lock lock(m_controller_mutex);
	m_pointer_recenter_hotkey = std::move(buttons);
	m_pointer_recenter_hotkey_latched = false;
}

void SDLController::set_pointer_enabled(bool enabled, bool notify)
{
	if (!is_joycon())
		return;

	const bool previous = m_pointer_enabled.exchange(enabled, std::memory_order_relaxed);
	if (enabled && previous != enabled)
		recenter_joycon_pointer(false);
	if (notify && previous != enabled)
	{
		const char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";
		LatteOverlay_pushNotification(fmt::format("{} Pointer {}", side, enabled ? "ON" : "OFF"), 2200);
	}
}

void SDLController::set_pointer_calibration(float horizontal_fov_degrees, float vertical_fov_degrees, float deadzone_degrees, float smoothing, bool invert_x, bool invert_y)
{
	horizontal_fov_degrees = std::clamp(horizontal_fov_degrees, 0.01f, 180.0f);
	vertical_fov_degrees = std::clamp(vertical_fov_degrees, 0.01f, 180.0f);
	deadzone_degrees = std::clamp(deadzone_degrees, 0.0f, 5.0f);
	smoothing = std::clamp(smoothing, 0.0f, 0.95f);

	m_pointer_yaw_degrees.store(horizontal_fov_degrees, std::memory_order_relaxed);
	m_pointer_pitch_degrees.store(vertical_fov_degrees, std::memory_order_relaxed);
	m_pointer_deadzone_degrees.store(deadzone_degrees, std::memory_order_relaxed);
	m_pointer_smoothing.store(smoothing, std::memory_order_relaxed);
	m_pointer_invert_x.store(invert_x, std::memory_order_relaxed);
	m_pointer_invert_y.store(invert_y, std::memory_order_relaxed);
}

void SDLController::set_dolphin_motion_settings(float total_yaw_degrees, float accel_influence, float gyro_deadzone_degrees, float calibration_period_seconds)
{
	total_yaw_degrees = std::clamp(total_yaw_degrees, 0.0f, 360.0f);
	accel_influence = std::clamp(accel_influence, 0.0f, 1.0f);
	gyro_deadzone_degrees = std::clamp(gyro_deadzone_degrees, 0.0f, 180.0f);
	calibration_period_seconds = std::clamp(calibration_period_seconds, 0.0f, 30.0f);
	m_dolphin_total_yaw_degrees.store(total_yaw_degrees, std::memory_order_relaxed);
	m_dolphin_accel_influence.store(accel_influence, std::memory_order_relaxed);
	m_dolphin_gyro_deadzone_degrees.store(gyro_deadzone_degrees, std::memory_order_relaxed);
	m_dolphin_calibration_period_seconds.store(calibration_period_seconds, std::memory_order_relaxed);
	if (m_diid >= 0)
		m_provider->set_joycon_dolphin_motion_settings(m_diid, gyro_deadzone_degrees, calibration_period_seconds);
}

void SDLController::set_pointer_calibration_period_seconds(float calibration_period_seconds)
{
	calibration_period_seconds = std::clamp(calibration_period_seconds, 0.0f, 30.0f);
	m_pointer_calibration_period_seconds.store(calibration_period_seconds, std::memory_order_relaxed);
	if (m_diid >= 0)
		m_provider->set_joycon_pointer_calibration_period(m_diid, calibration_period_seconds);
}

void SDLController::get_motion_scale(float& x, float& y, float& z) const
{
	x = m_motion_scale_x.load(std::memory_order_relaxed);
	y = m_motion_scale_y.load(std::memory_order_relaxed);
	z = m_motion_scale_z.load(std::memory_order_relaxed);
}

void SDLController::set_motion_scale(float x, float y, float z)
{
	auto clamp_scale = [](float value) {
		const float sign = value < 0.0f ? -1.0f : 1.0f;
		return sign * std::clamp(std::abs(value), 0.25f, 2.0f);
	};
	x = clamp_scale(x);
	y = clamp_scale(y);
	z = clamp_scale(z);
	m_motion_scale_x.store(x, std::memory_order_relaxed);
	m_motion_scale_y.store(y, std::memory_order_relaxed);
	m_motion_scale_z.store(z, std::memory_order_relaxed);
	if (m_diid >= 0)
		m_provider->set_joycon_motion_scale(m_diid, x, y, z);
	recenter_joycon_pointer(false);
}

void SDLController::recenter_joycon_pointer(bool notify)
{
	{
		std::scoped_lock lock(m_joycon_pointer_mutex);
		m_dolphin_recenter_requested = true;
		m_dolphin_pointer_target = m_joycon_pointer_position;
		m_dolphin_pointer_last_output_timestamp = 0;
		m_joycon_pointer_previous = m_joycon_pointer_position;
	}
	if (notify && is_joycon())
	{
		const char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";
		LatteOverlay_pushNotification(fmt::format("{} Pointer centered (Dolphin IMU)", side), 1800);
	}
}

bool SDLController::update_joycon_pointer(glm::vec2& position, glm::vec2& previous)
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
	const float kDolphinTotalYaw = get_dolphin_total_yaw_degrees() * kPi / 180.0f;
	const float kDolphinHorizontalFov = get_pointer_yaw_degrees() * kPi / 180.0f;
	const float kDolphinVerticalFov = get_pointer_pitch_degrees() * kPi / 180.0f;
	const float kDolphinAccelInfluence = get_dolphin_accel_influence();

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
		m_dolphin_pointer_target = {0.5f,0.5f};
		m_joycon_pointer_position = {0.5f,0.5f};
		m_joycon_pointer_previous = m_joycon_pointer_position;
		m_dolphin_pointer_last_output_timestamp = 0;
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

	// Preserve the proven V10 default geometry while giving Horizontal FOV the
	// same sensitivity direction as Dolphin: a wider camera FOV needs more yaw.
	const float max_yaw = std::max(0.0001f, kDolphinTotalYaw * 0.5f * (kDolphinHorizontalFov / (42.0f * kPi / 180.0f)));
	const float max_pitch = std::max(0.0001f, kDolphinVerticalFov * 0.5f);
	const glm::vec2 target{
		std::clamp(0.5f + 0.5f * (yaw / max_yaw), 0.0f, 1.0f),
		std::clamp(0.5f + 0.5f * (pitch / max_pitch), 0.0f, 1.0f)
	};
	m_dolphin_pointer_sensor_target = target;

	// V11 presentation layer. Keep Dolphin's quaternion/IMU result above untouched;
	// only suppress tiny hand tremor and interpolate the visible cursor between samples.
	const float pointer_deadzone = get_pointer_deadzone_degrees() * kPi / 180.0f;
	const glm::vec2 target_delta = target - m_dolphin_pointer_target;
	const glm::vec2 angular_delta{ target_delta.x * (2.0f * max_yaw), target_delta.y * (2.0f * max_pitch) };
	const float angular_distance = glm::length(angular_delta);

	glm::vec2 filtered_target = target;
	if (pointer_deadzone > 0.0f && angular_distance <= pointer_deadzone)
	{
		filtered_target = m_dolphin_pointer_target;
	}
	else if (pointer_deadzone > 0.0f && angular_distance > 0.000001f)
	{
		// Subtract the threshold rather than jumping across it. Slow intentional
		// movement accumulates naturally until it exits the tremor radius.
		const float active_fraction = (angular_distance - pointer_deadzone) / angular_distance;
		filtered_target = m_dolphin_pointer_target + target_delta * std::clamp(active_fraction, 0.0f, 1.0f);
	}
	m_dolphin_pointer_target = filtered_target;

	const uint64 output_now = static_cast<uint64>(std::chrono::duration_cast<std::chrono::nanoseconds>(
		std::chrono::steady_clock::now().time_since_epoch()).count());
	float output_dt = 1.0f / 120.0f;
	if (m_dolphin_pointer_last_output_timestamp != 0 && output_now > m_dolphin_pointer_last_output_timestamp)
		output_dt = static_cast<float>(output_now - m_dolphin_pointer_last_output_timestamp) / 1000000000.0f;
	m_dolphin_pointer_last_output_timestamp = output_now;
	output_dt = std::clamp(output_dt, 0.001f, 0.05f);

	const float smoothing = get_pointer_smoothing();
	float follow = 1.0f;
	if (smoothing > 0.0001f)
	{
		// 0.10 ~= very light smoothing. Higher values deliberately trade latency
		// for steadiness; zero keeps the exact V10 direct response.
		const float time_constant = 0.0025f + smoothing * 0.10f;
		follow = 1.0f - std::exp(-output_dt / time_constant);
	}

	m_joycon_pointer_previous = m_joycon_pointer_position;
	m_joycon_pointer_position += (m_dolphin_pointer_target - m_joycon_pointer_position) * std::clamp(follow, 0.0f, 1.0f);
	position = m_joycon_pointer_position;
	previous = m_joycon_pointer_previous;
	return true;
}

bool SDLController::get_joycon_pointer_debug(glm::vec2& sensor_target, glm::vec2& deadzone_target, glm::vec2& output) const
{
	std::scoped_lock lock(m_joycon_pointer_mutex);
	if (!m_joycon_pointer_initialized)
		return false;
	sensor_target = m_dolphin_pointer_sensor_target;
	deadzone_target = m_dolphin_pointer_target;
	output = m_joycon_pointer_position;
	return true;
}

bool SDLController::get_dolphin_motion_debug(SDLControllerProvider::DolphinMotionDebug& debug) const
{
	return m_diid >= 0 && m_provider->dolphin_motion_debug(m_diid, debug);
}

std::vector<uint32> SDLController::get_pressed_buttons_for_hotkey()
{
	std::vector<uint32> result;
	std::scoped_lock lock(m_controller_mutex);
	if (!m_controller || !SDL_GamepadConnected(m_controller))
		return result;

	for (uint32 i = 0; i < SDL_GAMEPAD_BUTTON_COUNT; ++i)
	{
		if (m_buttons[i] && SDL_GetGamepadButton(m_controller, (SDL_GamepadButton)i))
			result.emplace_back(i);
	}
	return result;
}

void SDLController::set_joycon_orientation(JoyConOrientation orientation, bool notify)
{
	if (!is_joycon())
		return;

	std::scoped_lock lock(m_controller_mutex);
	const auto previous = m_joycon_orientation.load(std::memory_order_relaxed);
	m_joycon_orientation.store(orientation, std::memory_order_relaxed);
	{
		std::scoped_lock pointer_lock(m_joycon_pointer_mutex);
		m_joycon_pointer_initialized = false;
		m_dolphin_pointer_rotation = {1.0f,0.0f,0.0f,0.0f};
		m_dolphin_recentered_pitch = 0.0f;
		m_dolphin_pointer_last_sensor_timestamp = 0;
		m_dolphin_pointer_last_output_timestamp = 0;
		m_dolphin_pointer_target = {0.5f, 0.5f};
		m_dolphin_recenter_requested = true;
	}
	if (m_diid >= 0)
	{
		// V5 user semantics: internal Sideways == physical Vertical.
		const bool physical_vertical = orientation == JoyConOrientation::Sideways;
		m_provider->set_joycon_orientation(m_diid, is_left_joycon(), physical_vertical);
	}

	if (notify && previous != orientation)
	{
		const char* side = is_left_joycon() ? "Joy-Con L" : "Joy-Con R";
		// V26: Mario Kart's shortcut semantics are now 1:1. Other titles retain
		// the V5 legacy presentation so their hardware-approved behavior is untouched.
		const TitleId foreground_base_title = TitleIdParser::MakeBaseTitleId(CafeSystem::GetForegroundTitleId());
		const bool v26_mario_kart_8 =
			foreground_base_title == 0x000500001010EB00ULL ||
			foreground_base_title == 0x000500001010EC00ULL ||
			foreground_base_title == 0x000500001010ED00ULL;
		const char* mode = v26_mario_kart_8
			? (orientation == JoyConOrientation::Vertical ? "Vertical" : "Sideways")
			: (orientation == JoyConOrientation::Vertical ? "Sideways" : "Vertical");
		LatteOverlay_pushNotification(fmt::format("{} -> {}", side, mode), 2200);
	}
}

bool SDLController::is_hotkey_pressed(const ControllerButtonState& buttons, const std::vector<uint32>& hotkey, size_t minimum_buttons) const
{
	if (hotkey.size() < minimum_buttons)
		return false;
	return std::all_of(hotkey.cbegin(), hotkey.cend(), [&buttons](uint32 id) {
		return buttons.GetButtonState(id);
	});
}

void SDLController::consume_hotkey(ControllerButtonState& buttons, const std::vector<uint32>& hotkey) const
{
	for (const auto id : hotkey)
		buttons.SetButtonState(id, false);
}

void SDLController::apply_vertical_transform(ControllerState& state) const
{
	const auto old_axis = state.axis;
	const bool south = state.buttons.GetButtonState(SDL_GAMEPAD_BUTTON_SOUTH);
	const bool east = state.buttons.GetButtonState(SDL_GAMEPAD_BUTTON_EAST);
	const bool west = state.buttons.GetButtonState(SDL_GAMEPAD_BUTTON_WEST);
	const bool north = state.buttons.GetButtonState(SDL_GAMEPAD_BUTTON_NORTH);

	if (is_left_joycon())
	{
		state.axis.x = -old_axis.y;
		state.axis.y = old_axis.x;
		state.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_NORTH, west);
		state.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_EAST, north);
		state.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_SOUTH, east);
		state.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_WEST, south);
	}
	else if (is_right_joycon())
	{
		state.axis.x = old_axis.y;
		state.axis.y = -old_axis.x;
		state.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_NORTH, east);
		state.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_EAST, south);
		state.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_SOUTH, west);
		state.buttons.SetButtonState(SDL_GAMEPAD_BUTTON_WEST, north);
	}
}

void SDLController::save(pugi::xml_node& node)
{
	base_type::save(node);
	if (!is_joycon())
		return;
	node.append_child("joycon_orientation").append_child(pugi::node_pcdata).set_value(fmt::format("{}", (int)get_joycon_orientation()).c_str());
	node.append_child("joycon_vertical_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_vertical_hotkey()).c_str());
	node.append_child("joycon_sideways_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_sideways_hotkey()).c_str());
	node.append_child("joycon_pointer_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_pointer_hotkey()).c_str());
	node.append_child("joycon_pointer_recenter_hotkey").append_child(pugi::node_pcdata).set_value(SerializeJoyConHotkey(get_pointer_recenter_hotkey()).c_str());
	node.append_child("joycon_pointer_enabled").append_child(pugi::node_pcdata).set_value(is_pointer_enabled() ? "1" : "0");
	node.append_child("joycon_pointer_yaw_deg").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_yaw_degrees()).c_str());
	node.append_child("joycon_pointer_pitch_deg").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_pitch_degrees()).c_str());
	node.append_child("joycon_pointer_deadzone_deg").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_deadzone_degrees()).c_str());
	node.append_child("joycon_pointer_smoothing").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_smoothing()).c_str());
	node.append_child("joycon_pointer_invert_x").append_child(pugi::node_pcdata).set_value(get_pointer_invert_x() ? "1" : "0");
	node.append_child("joycon_pointer_invert_y").append_child(pugi::node_pcdata).set_value(get_pointer_invert_y() ? "1" : "0");
	node.append_child("joycon_dolphin_total_yaw_deg").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_dolphin_total_yaw_degrees()).c_str());
	node.append_child("joycon_dolphin_accel_influence").append_child(pugi::node_pcdata).set_value(fmt::format("{:.4f}", get_dolphin_accel_influence()).c_str());
	node.append_child("joycon_dolphin_gyro_deadzone_deg_s").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_dolphin_gyro_deadzone_degrees()).c_str());
	node.append_child("joycon_dolphin_calibration_period_s").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_dolphin_calibration_period_seconds()).c_str());
	node.append_child("joycon_pointer_calibration_period_s").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", get_pointer_calibration_period_seconds()).c_str());
	float motion_x, motion_y, motion_z;
	get_motion_scale(motion_x, motion_y, motion_z);
	node.append_child("joycon_motion_scale_x").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", motion_x).c_str());
	node.append_child("joycon_motion_scale_y").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", motion_y).c_str());
	node.append_child("joycon_motion_scale_z").append_child(pugi::node_pcdata).set_value(fmt::format("{:.3f}", motion_z).c_str());
}

void SDLController::load(const pugi::xml_node& node)
{
	base_type::load(node);
	if (!is_joycon())
		return;
	if (const auto value = node.child("joycon_vertical_hotkey"))
		set_vertical_hotkey(ParseJoyConHotkey(value.child_value()));
	if (const auto value = node.child("joycon_sideways_hotkey"))
		set_sideways_hotkey(ParseJoyConHotkey(value.child_value()));
	if (const auto value = node.child("joycon_pointer_hotkey"))
		set_pointer_hotkey(ParseJoyConHotkey(value.child_value()));
	if (const auto value = node.child("joycon_pointer_recenter_hotkey"))
		set_pointer_recenter_hotkey(ParseJoyConHotkey(value.child_value()));
	bool pointer_enabled = true;
	if (const auto value = node.child("joycon_pointer_enabled"))
		pointer_enabled = ConvertString<int>(value.child_value()) != 0;
	set_pointer_enabled(pointer_enabled, false);
	float pointer_yaw = 42.0f;
	float pointer_pitch = 31.5f;
	float pointer_deadzone = 0.35f;
	float pointer_smoothing = 0.10f;
	bool pointer_invert_x = false;
	bool pointer_invert_y = false;
	if (const auto value = node.child("joycon_pointer_yaw_deg")) pointer_yaw = ConvertString<float>(value.child_value());
	if (const auto value = node.child("joycon_pointer_pitch_deg")) pointer_pitch = ConvertString<float>(value.child_value());
	if (const auto value = node.child("joycon_pointer_deadzone_deg")) pointer_deadzone = ConvertString<float>(value.child_value());
	if (const auto value = node.child("joycon_pointer_smoothing")) pointer_smoothing = ConvertString<float>(value.child_value());
	// V8-V12 called these fields yaw/pitch although V10's actual geometry was
	// fixed at Dolphin 25/31.5. Migrate only the untouched legacy defaults.
	if (std::abs(pointer_yaw - 25.0f) < 0.001f && std::abs(pointer_pitch - 20.0f) < 0.001f)
	{
		pointer_yaw = 42.0f;
		pointer_pitch = 31.5f;
	}
	// V10 displayed 2.00 / 0.01 but did not actually use those fields. Migrate only
	// that exact pair to V11's practical anti-tremor defaults.
	if (std::abs(pointer_deadzone - 2.0f) < 0.001f && std::abs(pointer_smoothing - 0.01f) < 0.001f)
	{
		pointer_deadzone = 0.35f;
		pointer_smoothing = 0.10f;
	}
	if (const auto value = node.child("joycon_pointer_invert_x")) pointer_invert_x = ConvertString<int>(value.child_value()) != 0;
	if (const auto value = node.child("joycon_pointer_invert_y")) pointer_invert_y = ConvertString<int>(value.child_value()) != 0;
	set_pointer_calibration(pointer_yaw, pointer_pitch, pointer_deadzone, pointer_smoothing, pointer_invert_x, pointer_invert_y);
	float total_yaw = 25.0f;
	float accel_influence = 0.01f;
	float gyro_deadzone = 2.0f;
	float calibration_period = 3.0f;
	float pointer_calibration_period = 3.0f;
	if (const auto value = node.child("joycon_dolphin_total_yaw_deg")) total_yaw = ConvertString<float>(value.child_value());
	if (const auto value = node.child("joycon_dolphin_accel_influence")) accel_influence = ConvertString<float>(value.child_value());
	if (const auto value = node.child("joycon_dolphin_gyro_deadzone_deg_s")) gyro_deadzone = ConvertString<float>(value.child_value());
	if (const auto value = node.child("joycon_dolphin_calibration_period_s")) calibration_period = ConvertString<float>(value.child_value());
	if (const auto value = node.child("joycon_pointer_calibration_period_s")) pointer_calibration_period = ConvertString<float>(value.child_value());
	set_dolphin_motion_settings(total_yaw, accel_influence, gyro_deadzone, calibration_period);
	set_pointer_calibration_period_seconds(pointer_calibration_period);
	// V13 migration: these legacy controls were inert through V11 and distorted
	// physical units when V12 began consuming them. Dolphin direct input is 1:1.
	set_motion_scale(1.0f, 1.0f, 1.0f);
	JoyConOrientation orientation = JoyConOrientation::Sideways;
	if (const auto value = node.child("joycon_orientation"))
	{
		if (ConvertString<int>(value.child_value()) == (int)JoyConOrientation::Vertical)
			orientation = JoyConOrientation::Vertical;
	}
	set_joycon_orientation(orientation, false);
}

bool SDLController::is_connected()
{
	std::scoped_lock lock(m_controller_mutex);
	if (!m_controller)
	{
		return false;
	}

	if (!SDL_GamepadConnected(m_controller))
	{
		SDL_CloseGamepad(m_controller);
		m_controller = nullptr;
		return false;
	}

	return true;
}

bool SDLController::connect()
{
	if (is_connected())
		return true;

	m_has_rumble = false;
	const auto index = m_provider->get_index(m_guid_index, m_guid);
	std::scoped_lock lock(m_controller_mutex);

	int gamepad_count = 0;

	SDL_JoystickID *gamepad_ids = SDL_GetGamepads(&gamepad_count);

	if (!gamepad_ids || index < 0 || index >= gamepad_count)
		return false;

	m_diid = gamepad_ids[index];
	SDL_free(gamepad_ids);

	m_controller = SDL_OpenGamepad(m_diid);

	if (!m_controller)
		return false;

	if (const char* name = SDL_GetGamepadName(m_controller))
		m_display_name = name;

	for (size_t i = 0; i < SDL_GAMEPAD_BUTTON_COUNT; ++i)
		m_buttons[i] = SDL_GamepadHasButton(m_controller, (SDL_GamepadButton)i);
	for (size_t i = 0; i < SDL_GAMEPAD_AXIS_COUNT; ++i)
		m_axis[i] = SDL_GamepadHasAxis(m_controller, (SDL_GamepadAxis)i);
	if (SDL_GamepadHasSensor(m_controller, SDL_SENSOR_ACCEL))
		m_has_accel = SDL_SetGamepadSensorEnabled(m_controller, SDL_SENSOR_ACCEL, true);
	if (SDL_GamepadHasSensor(m_controller, SDL_SENSOR_GYRO))
		m_has_gyro = SDL_SetGamepadSensorEnabled(m_controller, SDL_SENSOR_GYRO, true);
	m_has_rumble = SDL_RumbleGamepad(m_controller, 0, 0, 0);
	if (is_joycon())
	{
		// V5 user semantics: internal Sideways == physical Vertical.
		const bool physical_vertical = get_joycon_orientation() == JoyConOrientation::Sideways;
		m_provider->set_joycon_orientation(m_diid, is_left_joycon(), physical_vertical);
		m_provider->set_joycon_motion_scale(m_diid, 1.0f, 1.0f, 1.0f);
		m_provider->set_joycon_dolphin_motion_settings(m_diid,
			m_dolphin_gyro_deadzone_degrees.load(std::memory_order_relaxed),
			m_dolphin_calibration_period_seconds.load(std::memory_order_relaxed));
		m_provider->set_joycon_pointer_calibration_period(m_diid,
			m_pointer_calibration_period_seconds.load(std::memory_order_relaxed));
	}
	return true;
}

void SDLController::start_rumble()
{
	std::scoped_lock lock(m_controller_mutex);
	if (is_connected() && !m_has_rumble)
		return;
	if (m_settings.rumble <= 0)
		return;
	SDL_RumbleGamepad(m_controller, (Uint16)(m_settings.rumble * 0xFFFF), (Uint16)(m_settings.rumble * 0xFFFF), 5 * 1000);
}

void SDLController::stop_rumble()
{
	std::scoped_lock lock(m_controller_mutex);
	if (is_connected() && !m_has_rumble)
		return;
	SDL_RumbleGamepad(m_controller, 0, 0, 0);
}

MotionSample SDLController::get_motion_sample()
{
	if (is_connected() && has_motion())
		return m_provider->motion_sample(m_diid);
	return {};
}

std::string SDLController::get_button_name(uint64 button) const
{
	if (const char* name = SDL_GetGamepadStringForButton((SDL_GamepadButton)button))
		return name;
	return base_type::get_button_name(button);
}

ControllerState SDLController::raw_state()
{
	ControllerState result{};
	std::scoped_lock lock(m_controller_mutex);
	if (!is_connected())
		return result;
	for (size_t i = 0; i < SDL_GAMEPAD_BUTTON_COUNT; ++i)
	{
		if (m_buttons[i] && SDL_GetGamepadButton(m_controller, (SDL_GamepadButton)i))
			result.buttons.SetButtonState(i, true);
	}

	if (m_axis[SDL_GAMEPAD_AXIS_LEFTX])
		result.axis.x = (float)SDL_GetGamepadAxis(m_controller, SDL_GAMEPAD_AXIS_LEFTX) / 32767.0f;
	if (m_axis[SDL_GAMEPAD_AXIS_LEFTY])
		result.axis.y = (float)SDL_GetGamepadAxis(m_controller, SDL_GAMEPAD_AXIS_LEFTY) / 32767.0f;
	if (m_axis[SDL_GAMEPAD_AXIS_RIGHTX])
		result.rotation.x = (float)SDL_GetGamepadAxis(m_controller, SDL_GAMEPAD_AXIS_RIGHTX) / 32767.0f;
	if (m_axis[SDL_GAMEPAD_AXIS_RIGHTY])
		result.rotation.y = (float)SDL_GetGamepadAxis(m_controller, SDL_GAMEPAD_AXIS_RIGHTY) / 32767.0f;
	if (m_axis[SDL_GAMEPAD_AXIS_LEFT_TRIGGER])
		result.trigger.x = (float)SDL_GetGamepadAxis(m_controller, SDL_GAMEPAD_AXIS_LEFT_TRIGGER) / 32767.0f;
	if (m_axis[SDL_GAMEPAD_AXIS_RIGHT_TRIGGER])
		result.trigger.y = (float)SDL_GetGamepadAxis(m_controller, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) / 32767.0f;

	if (is_joycon())
	{
		const bool vertical_pressed = is_hotkey_pressed(result.buttons, m_vertical_hotkey);
		const bool sideways_pressed = is_hotkey_pressed(result.buttons, m_sideways_hotkey);
		const bool pointer_pressed = is_hotkey_pressed(result.buttons, m_pointer_hotkey);
		const bool recenter_pressed = is_hotkey_pressed(result.buttons, m_pointer_recenter_hotkey, 1);
		// V26: V5's legacy hotkey swap is still required by older custom-build
		// behavior outside Mario Kart. Mario Kart 8 alone uses the now-correct
		// 1:1 shortcut semantics, so Sideways selects the exact internal Sideways
		// state that hardware-validated V25-Z at 100%. No motion math changes here.
		const TitleId foreground_base_title = TitleIdParser::MakeBaseTitleId(CafeSystem::GetForegroundTitleId());
		const bool v26_mario_kart_8 =
			foreground_base_title == 0x000500001010EB00ULL ||
			foreground_base_title == 0x000500001010EC00ULL ||
			foreground_base_title == 0x000500001010ED00ULL;
		if (vertical_pressed && !m_vertical_hotkey_latched)
			set_joycon_orientation(v26_mario_kart_8 ? JoyConOrientation::Vertical : JoyConOrientation::Sideways);
		if (sideways_pressed && !m_sideways_hotkey_latched)
			set_joycon_orientation(v26_mario_kart_8 ? JoyConOrientation::Sideways : JoyConOrientation::Vertical);
		if (pointer_pressed && !m_pointer_hotkey_latched)
			set_pointer_enabled(!is_pointer_enabled());
		if (recenter_pressed && !m_pointer_recenter_hotkey_latched)
			recenter_joycon_pointer();
		m_vertical_hotkey_latched = vertical_pressed;
		m_sideways_hotkey_latched = sideways_pressed;
		m_pointer_hotkey_latched = pointer_pressed;
		m_pointer_recenter_hotkey_latched = recenter_pressed;
		if (vertical_pressed)
			consume_hotkey(result.buttons, m_vertical_hotkey);
		if (sideways_pressed)
			consume_hotkey(result.buttons, m_sideways_hotkey);
		if (pointer_pressed)
			consume_hotkey(result.buttons, m_pointer_hotkey);
		if (recenter_pressed)
			consume_hotkey(result.buttons, m_pointer_recenter_hotkey);
		// SDL already exposes a separate Joy-Con as a horizontal mini-gamepad.
		// Rotate controls only when the USER is physically holding it Vertical.
		if (get_joycon_orientation() == JoyConOrientation::Sideways)
			apply_vertical_transform(result);
	}

	return result;
}
