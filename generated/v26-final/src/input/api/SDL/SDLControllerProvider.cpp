#include "input/api/SDL/SDLControllerProvider.h"

#include "input/api/SDL/SDLController.h"
#include "util/helpers/TempState.h"

#include <SDL3/SDL.h>
#include <boost/functional/hash.hpp>

struct SDL_JoystickGUIDHash
{
	std::size_t operator()(const SDL_GUID& guid) const
	{
		return boost::hash_value(guid.data);
	}
};

SDLControllerProvider::SDLControllerProvider()
{
#if !BOOST_OS_MACOS
	std::scoped_lock _l(s_mutex);
	if (s_initCount.fetch_add(1) == 0)
	{
		s_running = true;
		s_thread = std::thread(&SDLControllerProvider::event_thread, this);
	}
#endif
}

SDLControllerProvider::~SDLControllerProvider()
{
#if !BOOST_OS_MACOS
	bool shutdownSDL = false;
	{
		std::scoped_lock _l(s_mutex);
		if (s_initCount.fetch_sub(1) == 1)
		{
			cemu_assert_debug(s_running);
			s_running = false;
			shutdownSDL = true;
		}
	}

	if (shutdownSDL)
	{
		// wake the thread with a quit event if it's currently waiting for events
		SDL_Event evt;
		SDL_zero(evt);
		evt.type = SDL_EVENT_QUIT;
		SDL_PushEvent(&evt);
		if (s_thread.joinable())
		{
			s_thread.join();
		}
	}
#endif
}

std::vector<std::shared_ptr<ControllerBase>> SDLControllerProvider::get_controllers()
{
	std::vector<std::shared_ptr<ControllerBase>> result;

	std::unordered_map<SDL_GUID, size_t, SDL_JoystickGUIDHash> guid_counter;

	TempState lock(SDL_LockJoysticks, SDL_UnlockJoysticks);
	int gamepad_count = 0;
	SDL_JoystickID *gamepad_ids = SDL_GetGamepads(&gamepad_count);
	if (gamepad_ids)
	{
		for (size_t i = 0; i < gamepad_count; ++i)
		{
			const auto guid = SDL_GetGamepadGUIDForID(gamepad_ids[i]);
			const auto it = guid_counter.try_emplace(guid, 0);
			if (const char* name = SDL_GetGamepadNameForID(gamepad_ids[i]))
				result.emplace_back(std::make_shared<SDLController>(guid, it.first->second, name));
			else
				result.emplace_back(std::make_shared<SDLController>(guid, it.first->second));
			++it.first->second;
		}
		SDL_free(gamepad_ids);
	}
	return result;
}

int SDLControllerProvider::get_index(size_t guid_index, const SDL_GUID& guid) const
{
	size_t index = 0;
	int gamepad_count = 0;
	TempState lock(SDL_LockJoysticks, SDL_UnlockJoysticks);
	SDL_JoystickID *gamepad_ids = SDL_GetGamepads(&gamepad_count);
	if (gamepad_ids)
	{
		for (size_t i = 0; i < gamepad_count; ++i)
		{
			if (guid == SDL_GetGamepadGUIDForID(gamepad_ids[i]))
			{
				if (index == guid_index)
				{
					SDL_free(gamepad_ids);
					return i;
				}
				++index;
			}
		}
		SDL_free(gamepad_ids);
	}
	return -1;
}

MotionSample SDLControllerProvider::motion_sample(SDL_JoystickID diid)
{
	std::shared_lock lock(s_mutex);
	auto it = s_motion_states.find(diid);
	return (it != s_motion_states.end()) ? it->second.data : MotionSample{};
}

bool SDLControllerProvider::dolphin_pointer_motion(SDL_JoystickID diid, glm::vec3& gyro, glm::vec3& accel, uint64& timestamp)
{
	std::shared_lock lock(s_mutex);
	const auto it = s_motion_states.find(diid);
	if (it == s_motion_states.end() || !it->second.dolphin_pointer_has_gyro || !it->second.dolphin_pointer_has_acc)
		return false;
	gyro = it->second.dolphin_pointer_gyro;
	accel = it->second.dolphin_pointer_acc;
	timestamp = it->second.dolphin_pointer_timestamp;
	return timestamp != 0;
}

bool SDLControllerProvider::dolphin_motion_debug(SDL_JoystickID diid, DolphinMotionDebug& debug)
{
	std::shared_lock lock(s_mutex);
	const auto it = s_motion_states.find(diid);
	if (it == s_motion_states.end() || !it->second.dolphin_pointer_has_gyro || !it->second.dolphin_pointer_has_acc)
		return false;
	const auto& state = it->second;
	debug.gyro = state.dolphin_motion_gyro;
	debug.accel = state.dolphin_motion_acc;
	debug.bias = state.dolphin_gyro_bias;
	debug.game_bias = state.game_gyro_bias;
	debug.sample_rate_hz = state.dolphin_sample_rate_hz;
	debug.game_sample_rate_hz = state.game_sample_rate_hz;
	if (const auto config = s_joycon_orientation_states.find(diid); config != s_joycon_orientation_states.end())
	{
		debug.gyro_deadzone_degrees = config->second.gyro_deadzone_degrees;
		debug.calibration_period_seconds = config->second.pointer_calibration_period_seconds;
		debug.game_calibration_period_seconds = config->second.calibration_period_seconds;
	}
	debug.stable = state.dolphin_calibration_stable;
	debug.calibrated = state.dolphin_calibration_complete;
	debug.game_stable = state.game_calibration_stable;
	debug.game_calibrated = state.game_calibration_complete;
	debug.timestamp = state.dolphin_pointer_timestamp;
	if (state.dolphin_calibration_start != 0 && debug.timestamp >= state.dolphin_calibration_start &&
		debug.calibration_period_seconds > 0.0f)
	{
		const float period_ns = debug.calibration_period_seconds * 1000000000.0f;
		const float elapsed = static_cast<float>(debug.timestamp - state.dolphin_calibration_start) / period_ns;
		debug.calibration_progress = std::clamp(elapsed, 0.0f, 1.0f);
	}
	if (state.game_calibration_start != 0 && debug.timestamp >= state.game_calibration_start &&
		debug.game_calibration_period_seconds > 0.0f)
	{
		const float period_ns = debug.game_calibration_period_seconds * 1000000000.0f;
		const float elapsed = static_cast<float>(debug.timestamp - state.game_calibration_start) / period_ns;
		debug.game_calibration_progress = std::clamp(elapsed, 0.0f, 1.0f);
	}
	return debug.timestamp != 0;
}

void SDLControllerProvider::set_joycon_orientation(SDL_JoystickID diid, bool is_left, bool vertical)
{
	if (diid < 0)
		return;

	std::scoped_lock lock(s_mutex);
	auto& state = s_joycon_orientation_states[diid];
	const bool changed = state.is_left != is_left || state.vertical != vertical;
	if (changed)
		s_motion_states.erase(diid);
	// Preserve V8 per-device motion calibration while changing orientation.
	state.is_left = is_left;
	state.vertical = vertical;
}

void SDLControllerProvider::set_joycon_motion_scale(SDL_JoystickID diid, float x, float y, float z)
{
	if (diid < 0)
		return;

	std::scoped_lock lock(s_mutex);
	auto& state = s_joycon_orientation_states[diid];
	if (state.motion_scale_x != x || state.motion_scale_y != y || state.motion_scale_z != z)
	{
		state.motion_scale_x = x;
		state.motion_scale_y = y;
		state.motion_scale_z = z;
		// A basis/calibration change must restart Mahony integration.
		s_motion_states.erase(diid);
	}
}

void SDLControllerProvider::set_joycon_dolphin_motion_settings(SDL_JoystickID diid, float gyro_deadzone_degrees, float calibration_period_seconds)
{
	if (diid < 0)
		return;

	gyro_deadzone_degrees = std::clamp(gyro_deadzone_degrees, 0.0f, 180.0f);
	calibration_period_seconds = std::clamp(calibration_period_seconds, 0.0f, 30.0f);
	std::scoped_lock lock(s_mutex);
	auto& state = s_joycon_orientation_states[diid];
	if (state.gyro_deadzone_degrees != gyro_deadzone_degrees ||
		state.calibration_period_seconds != calibration_period_seconds)
	{
		state.gyro_deadzone_degrees = gyro_deadzone_degrees;
		state.calibration_period_seconds = calibration_period_seconds;
		s_motion_states.erase(diid);
	}
}

void SDLControllerProvider::set_joycon_pointer_calibration_period(SDL_JoystickID diid, float calibration_period_seconds)
{
	if (diid < 0)
		return;

	calibration_period_seconds = std::clamp(calibration_period_seconds, 0.0f, 30.0f);
	std::scoped_lock lock(s_mutex);
	auto& config = s_joycon_orientation_states[diid];
	if (config.pointer_calibration_period_seconds != calibration_period_seconds)
	{
		config.pointer_calibration_period_seconds = calibration_period_seconds;
		// Reset both per-device filters so no old basis/bias survives a live setting change.
		s_motion_states.erase(diid);
	}
}

void SDLControllerProvider::clear_joycon_orientation(SDL_JoystickID diid)
{
	if (diid < 0)
		return;

	std::scoped_lock lock(s_mutex);
	s_joycon_orientation_states.erase(diid);
	s_motion_states.erase(diid);
}

void SDLControllerProvider::InitSDL()
{
	SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_ENHANCED_REPORTS, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS4, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS5, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_GAMECUBE, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH2, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_JOY_CONS, "1");
	// Keep each Joy-Con independent in SDL mini-gamepad mode. Cemu applies
	// per-device Vertical/Sideways transforms at runtime.
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_COMBINE_JOY_CONS, "0");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_VERTICAL_JOY_CONS, "0");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_STADIA, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_STEAM, "1");
	SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_LUNA, "1");

	if (!SDL_InitSubSystem(SDL_INIT_GAMEPAD | SDL_INIT_HAPTIC))
	{
		throw std::runtime_error(fmt::format("couldn't initialize SDL: {}", SDL_GetError()));
	}

	SDL_SetGamepadEventsEnabled(true);
	if (!SDL_GamepadEventsEnabled())
	{
		cemuLog_log(LogType::Force, "Couldn't enable SDL gamecontroller event polling: {}", SDL_GetError());
	}
}

void SDLControllerProvider::ShutdownSDL()
{
	SDL_QuitSubSystem(SDL_INIT_GAMEPAD | SDL_INIT_HAPTIC);
}

#if BOOST_OS_MACOS
void SDLControllerProvider::PumpSDLEvents()
{
	SDL_Event event;
	while (SDL_PollEvent(&event))
		HandleSDLEvent(event);
}
#endif

void SDLControllerProvider::HandleSDLEvent(SDL_Event& event)
{
	switch (event.type)
	{
		case SDL_EVENT_QUIT:
		{
			std::scoped_lock _l(s_mutex);
			s_running = false;
			break;
		}
		case SDL_EVENT_GAMEPAD_AXIS_MOTION: /**< Game controller axis motion */
		{
			break;
		}
		case SDL_EVENT_GAMEPAD_BUTTON_DOWN: /**< Game controller button pressed */
		{
			break;
		}
		case SDL_EVENT_GAMEPAD_BUTTON_UP: /**< Game controller button released */
		{
			break;
		}
		case SDL_EVENT_GAMEPAD_ADDED: /**< A new Game controller has been inserted into the system */
		{
			std::scoped_lock _l(s_mutex);
			InputManager::instance().on_device_changed();
			break;
		}
		case SDL_EVENT_GAMEPAD_REMOVED: /**< An opened Game controller has been removed */
		{
			std::scoped_lock _l(s_mutex);
			InputManager::instance().on_device_changed();
			s_motion_states.erase(event.gdevice.which);
			s_joycon_orientation_states.erase(event.gdevice.which);
			break;
		}
		case SDL_EVENT_GAMEPAD_REMAPPED: 			/**< The controller mapping was updated */
		{
			break;
		}
		case SDL_EVENT_GAMEPAD_TOUCHPAD_DOWN:		/**< Game controller touchpad was touched */
		{
			break;
		}
		case SDL_EVENT_GAMEPAD_TOUCHPAD_MOTION:		/**< Game controller touchpad finger was moved */
		{
			break;
		}
		case SDL_EVENT_GAMEPAD_TOUCHPAD_UP:			/**< Game controller touchpad finger was lifted */
		{
			break;
		}
		case SDL_EVENT_GAMEPAD_SENSOR_UPDATE:		/**< Game controller sensor was updated */
		{
			SDL_JoystickID id = event.gsensor.which;
			uint64_t ts = event.gsensor.timestamp;
			std::scoped_lock _l(s_mutex);
			auto& state = s_motion_states[id];
			auto& tracking = state.tracking;

			float sensor_data[3] = {
				event.gsensor.data[0],
				event.gsensor.data[1],
				event.gsensor.data[2]
			};

			// V10 Dolphin 2606a sensor basis. SDL is intentionally kept in Cemu's
			// independent mini-gamepad mode, then converted here back to the same native
			// Joy-Con frame seen by the user's Dolphin build (VERTICAL_JOY_CONS=1).
			bool v10_is_joycon = false;
			float v10_native[3] = { sensor_data[0], sensor_data[1], sensor_data[2] };
			// V14 split stream: V10 native/Dolphin semantics above are pointer-only.
			// The game stream below is the last known-good V9/V6/V7 Cemu basis.
			float v9_game_sensor[3] = { sensor_data[0], sensor_data[1], sensor_data[2] };
			if (const auto config = s_joycon_orientation_states.find(id);
				config != s_joycon_orientation_states.end())
			{
				v10_is_joycon = true;
				const float x = sensor_data[0];
				const float y = sensor_data[1];
				const float z = sensor_data[2];
				if (config->second.is_left)
				{
					// Inverse of SDL L mini mapping: native -> (z,y,-x).
					v10_native[0] = -z;
					v10_native[1] = y;
					v10_native[2] = x;
				}
				else
				{
					// Inverse of SDL R mini mapping: native -> (-z,y,x).
					v10_native[0] = z;
					v10_native[1] = y;
					v10_native[2] = -x;
				}

				// V15 game/KPAD physical basis: L Sideways stays in SDL mini-gamepad
				// coordinates, R Sideways gets the hardware-proven 180-degree X/Z
				// correction, and Vertical keeps V9's clean +/-90-degree Y rotation.
				// V22 hardware-driven motion basis. SDL is globally kept in mini-gamepad
				// mode, but the physical Wii Remote Sideways pose needs the inverse mini
				// sensor rotation. Vertical deliberately keeps the raw mini sensor basis.
				// Stick/buttons are handled separately and are not changed here.
				if (!config->second.vertical)
				{
					if (config->second.is_left)
					{
						v9_game_sensor[0] = -z;
						v9_game_sensor[1] = y;
						v9_game_sensor[2] = x;
					}
					else
					{
						v9_game_sensor[0] = z;
						v9_game_sensor[1] = y;
						v9_game_sensor[2] = -x;
					}
				}
			}

			if (event.gsensor.sensor == SDL_SENSOR_ACCEL)
			{
				const auto dif = ts - tracking.lastTimestampAccel;
				if (dif <= 0)
				{
					break;
				}

				if (dif >= 10000000000)
				{
					tracking.hasAcc = false;
					tracking.hasGyro = false;
					tracking.lastTimestampAccel = ts;
					break;
				}

				tracking.lastTimestampAccel = ts;
				if (v10_is_joycon)
				{
					glm::vec3 dolphin_acc{ -v10_native[0] / 9.81f, v10_native[2] / 9.81f, v10_native[1] / 9.81f };
					state.dolphin_pointer_acc = dolphin_acc;
					state.dolphin_pointer_has_acc = true;
					// Game motion is deliberately NOT Dolphin-oriented. Reproduce V9's
					// Cemu tracking vector; the adapter's historical Y/Z signs are applied
					// at processMotionSample below. Pointer remains pre-orientation.
					tracking.acc = glm::vec3{
						-v9_game_sensor[0] / 9.81f,
						-v9_game_sensor[1] / 9.81f,
						-v9_game_sensor[2] / 9.81f };
					if (const auto game_config = s_joycon_orientation_states.find(id);
						game_config != s_joycon_orientation_states.end() && !game_config->second.is_left)
					{
						// V22: final Joy-Con R accelerometer = requested physical 180-degree
						// correction relative to L. Apply here so later axis routing cannot
						// cancel or reinterpret the correction. Y remains unchanged.
						tracking.acc.x = -tracking.acc.x;
						tracking.acc.z = -tracking.acc.z;
					}
				}
				else
				{
					tracking.acc[0] = -sensor_data[0] / 9.81f;
					tracking.acc[1] = -sensor_data[1] / 9.81f;
					tracking.acc[2] = -sensor_data[2] / 9.81f;
				}
				tracking.hasAcc = true;
			}
			if (event.gsensor.sensor == SDL_SENSOR_GYRO)
			{
				const auto dif = ts - tracking.lastTimestampGyro;
				if (dif <= 0)
				{
					break;
				}

				if (dif >= 10000000000)
				{
					tracking.hasAcc = false;
					tracking.hasGyro = false;
					tracking.lastTimestampGyro = ts;
					break;
				}

				tracking.lastTimestampGyro = ts;
				if (v10_is_joycon)
				{
					constexpr double kDolphinMinCalibrationHz = 25.0;
					float kDolphinGyroDeadzone = 2.0f * 3.14159265358979323846f / 180.0f;
					uint64 kDolphinCalibrationPeriodNs = 3000000000ULL;
					if (const auto config = s_joycon_orientation_states.find(id); config != s_joycon_orientation_states.end())
					{
						kDolphinGyroDeadzone = config->second.gyro_deadzone_degrees * 3.14159265358979323846f / 180.0f;
						kDolphinCalibrationPeriodNs = static_cast<uint64>(config->second.pointer_calibration_period_seconds * 1000000000.0f);
					}
					glm::vec3 raw_gyro{ -v10_native[0], v10_native[2], v10_native[1] };

					auto restart_calibration = [&]() {
						state.dolphin_calibration_start = ts;
						state.dolphin_calibration_sum = raw_gyro;
						state.dolphin_calibration_count = 1;
					};

					if (kDolphinCalibrationPeriodNs == 0)
					{
						state.dolphin_gyro_bias = {};
						state.dolphin_calibration_count = 0;
						state.dolphin_calibration_stable = true;
						state.dolphin_calibration_complete = true;
					}
					else if (state.dolphin_calibration_count == 0)
					{
						// V21: learn pointer bias only from a completed stillness window.
						state.dolphin_calibration_initialized = true;
						restart_calibration();
					}
					else
					{
						const uint64 elapsed_ns = ts - state.dolphin_calibration_start;
						const double elapsed_s = static_cast<double>(elapsed_ns) / 1000000000.0;
						const glm::vec3 mean = state.dolphin_calibration_sum / static_cast<float>(state.dolphin_calibration_count);
						const glm::vec3 difference = raw_gyro - mean;
						const double frequency = elapsed_s > 0.0 ? static_cast<double>(state.dolphin_calibration_count) / elapsed_s : kDolphinMinCalibrationHz;
						state.dolphin_sample_rate_hz = static_cast<float>(frequency);
						const bool unstable = std::abs(difference.x) > kDolphinGyroDeadzone ||
							std::abs(difference.y) > kDolphinGyroDeadzone ||
							std::abs(difference.z) > kDolphinGyroDeadzone ||
							frequency < kDolphinMinCalibrationHz;
						state.dolphin_calibration_stable = !unstable;
						if (unstable)
						{
							state.dolphin_calibration_complete = false;
							restart_calibration();
						}
						else
						{
							state.dolphin_calibration_sum += raw_gyro;
							++state.dolphin_calibration_count;
							if (elapsed_ns >= kDolphinCalibrationPeriodNs)
							{
								state.dolphin_gyro_bias = state.dolphin_calibration_sum / static_cast<float>(state.dolphin_calibration_count);
								state.dolphin_calibration_complete = true;
							}
						}
					}

					glm::vec3 dolphin_gyro = raw_gyro - state.dolphin_gyro_bias;
					if (std::abs(dolphin_gyro.x) <= kDolphinGyroDeadzone) dolphin_gyro.x = 0.0f;
					if (std::abs(dolphin_gyro.y) <= kDolphinGyroDeadzone) dolphin_gyro.y = 0.0f;
					if (std::abs(dolphin_gyro.z) <= kDolphinGyroDeadzone) dolphin_gyro.z = 0.0f;

					state.dolphin_pointer_gyro = dolphin_gyro;
					state.dolphin_pointer_timestamp = ts;
					state.dolphin_pointer_has_gyro = true;
					// V21 game gyro: preserve V16's exact physical axes, then calibrate
					// a per-Joy-Con bias only after the configured stillness window.
					glm::vec3 game_gyro_raw{
						v9_game_sensor[0],
						-v9_game_sensor[1],
						-v9_game_sensor[2] };
					constexpr double kV21MinCalibrationHz = 25.0;
					float game_deadzone = 2.0f * 3.14159265358979323846f / 180.0f;
					uint64 game_period_ns = 3000000000ULL;
					if (const auto config = s_joycon_orientation_states.find(id); config != s_joycon_orientation_states.end())
					{
						game_deadzone = config->second.gyro_deadzone_degrees * 3.14159265358979323846f / 180.0f;
						game_period_ns = static_cast<uint64>(config->second.calibration_period_seconds * 1000000000.0f);
					}
					auto restart_game_calibration = [&]() {
						state.game_calibration_start = ts;
						state.game_calibration_sum = game_gyro_raw;
						state.game_calibration_count = 1;
					};
					if (game_period_ns == 0)
					{
						state.game_gyro_bias = {};
						state.game_calibration_count = 0;
						state.game_calibration_start = 0;
						state.game_calibration_stable = true;
						state.game_calibration_complete = true;
						state.game_sample_rate_hz = 0.0f;
					}
					else if (state.game_calibration_count == 0)
					{
						state.game_calibration_stable = false;
						restart_game_calibration();
					}
					else
					{
						const uint64 elapsed_ns = ts - state.game_calibration_start;
						const double elapsed_s = static_cast<double>(elapsed_ns) / 1000000000.0;
						const glm::vec3 mean = state.game_calibration_sum / static_cast<float>(state.game_calibration_count);
						const glm::vec3 difference = game_gyro_raw - mean;
						const double frequency = elapsed_s > 0.0 ? static_cast<double>(state.game_calibration_count) / elapsed_s : kV21MinCalibrationHz;
						state.game_sample_rate_hz = static_cast<float>(frequency);
						const bool unstable = std::abs(difference.x) > game_deadzone ||
							std::abs(difference.y) > game_deadzone ||
							std::abs(difference.z) > game_deadzone ||
							frequency < kV21MinCalibrationHz;
						state.game_calibration_stable = !unstable;
						if (unstable)
						{
							// Keep the last valid bias while moving; only restart the candidate window.
							restart_game_calibration();
						}
						else
						{
							state.game_calibration_sum += game_gyro_raw;
							++state.game_calibration_count;
							if (elapsed_ns >= game_period_ns)
							{
								state.game_gyro_bias = state.game_calibration_sum / static_cast<float>(state.game_calibration_count);
								state.game_calibration_complete = true;
							}
						}
					}
					glm::vec3 game_gyro = game_gyro_raw - state.game_gyro_bias;
					if (std::abs(game_gyro.x) <= game_deadzone) game_gyro.x = 0.0f;
					if (std::abs(game_gyro.y) <= game_deadzone) game_gyro.y = 0.0f;
					if (std::abs(game_gyro.z) <= game_deadzone) game_gyro.z = 0.0f;
					tracking.gyro = game_gyro;
				}
				else
				{
					tracking.gyro[0] = sensor_data[0];
					tracking.gyro[1] = -sensor_data[1];
					tracking.gyro[2] = -sensor_data[2];
				}
				tracking.hasGyro = true;
			}
			if (tracking.hasAcc && tracking.hasGyro)
			{
				// Live game-motion view shows the exact values delivered to Cemu/KPAD.
				// The pointer debug view remains the independent Dolphin stream.
				state.dolphin_motion_acc = glm::vec3{ tracking.acc.x, -tracking.acc.y, -tracking.acc.z };
				state.dolphin_motion_gyro = tracking.gyro;

				auto ts = std::max(tracking.lastTimestampGyro, tracking.lastTimestampAccel);

				if (ts > tracking.lastTimestampIntegrate)
				{
					const auto tsDif = ts - tracking.lastTimestampIntegrate;
					tracking.lastTimestampIntegrate = ts;
					float tsDifD = (float)tsDif / 1000000000.0f;

					if (tsDifD >= 1.0f)
					{
						tsDifD = 1.0f;
					}

					// V14: all game motion uses Cemu's proven V9 adapter contract. Never
					// feed Dolphin binding-semantic axes directly into WiiUMotionHandler.
					if (s_joycon_orientation_states.contains(id))
						state.handler.processCalibratedMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);
					else
						state.handler.processMotionSample(tsDifD, tracking.gyro.x, tracking.gyro.y, tracking.gyro.z, tracking.acc.x, -tracking.acc.y, -tracking.acc.z);
					state.data = state.handler.getMotionSample();
				}

				tracking.hasAcc = false;
				tracking.hasGyro = false;
			}
			break;
		}
	}
}

void SDLControllerProvider::event_thread()
{
#if BOOST_OS_MACOS
	cemu_assert(false);
#endif
	SetThreadName("SDL_events");
	InitSDL();
	while (s_running.load(std::memory_order_relaxed))
	{
		SDL_Event event{};
		SDL_WaitEvent(&event);
		HandleSDLEvent(event);
	}
	ShutdownSDL();
}
