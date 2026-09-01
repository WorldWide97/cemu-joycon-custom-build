#pragma once
#include <SDL3/SDL_joystick.h>
#include "input/motion/MotionHandler.h"
#include "input/api/ControllerProvider.h"

static bool operator==(const SDL_GUID& g1, const SDL_GUID& g2)
{
	return memcmp(&g1, &g2, sizeof(SDL_GUID)) == 0;
}

class SDLControllerProvider : public ControllerProviderBase
{
	friend class SDLController;
public:
	struct DolphinMotionDebug
	{
		glm::vec3 gyro{};
		glm::vec3 accel{};
		glm::vec3 bias{};
		float calibration_progress{};
		float sample_rate_hz{};
		float gyro_deadzone_degrees{ 2.0f };
		// Existing fields below describe POINTER calibration in V21.
		float calibration_period_seconds{ 3.0f };
		glm::vec3 game_bias{};
		float game_calibration_progress{};
		float game_sample_rate_hz{};
		float game_calibration_period_seconds{ 3.0f };
		bool game_stable{};
		bool game_calibrated{};
		bool stable{};
		bool calibrated{};
		uint64 timestamp{};
	};

	SDLControllerProvider();
	~SDLControllerProvider();

	inline static InputAPI::Type kAPIType = InputAPI::SDLController;
	InputAPI::Type api() const override { return kAPIType; }

	std::vector<std::shared_ptr<ControllerBase>> get_controllers() override;
	
	int get_index(size_t guid_index, const SDL_GUID& guid) const;

	MotionSample motion_sample(SDL_JoystickID diid);
	bool dolphin_pointer_motion(SDL_JoystickID diid, glm::vec3& gyro, glm::vec3& accel, uint64& timestamp);
	bool dolphin_motion_debug(SDL_JoystickID diid, DolphinMotionDebug& debug);
	void set_joycon_orientation(SDL_JoystickID diid, bool is_left, bool vertical);
	void set_joycon_motion_scale(SDL_JoystickID diid, float x, float y, float z);
	void set_joycon_dolphin_motion_settings(SDL_JoystickID diid, float gyro_deadzone_degrees, float calibration_period_seconds);
	void set_joycon_pointer_calibration_period(SDL_JoystickID diid, float calibration_period_seconds);
	void clear_joycon_orientation(SDL_JoystickID diid);

	// exposed for manual event handling on macOS
#if BOOST_OS_MACOS
	static void InitSDL();
	static void ShutdownSDL();
	static void PumpSDLEvents();
#endif

private:
	void event_thread();
	static void HandleSDLEvent(union SDL_Event& event);
#if !BOOST_OS_MACOS
	static void InitSDL();
	static void ShutdownSDL();
#endif

	// there is only one SDL instance, for this reason all of our state can be static
	inline static std::atomic_int s_initCount{0};
	inline static std::shared_mutex s_mutex;
	inline static std::atomic_bool s_running = false;
	inline static std::thread s_thread;

	struct MotionInfoTracking
	{
		uint64 lastTimestampGyro{};
		uint64 lastTimestampAccel{};
		uint64 lastTimestampIntegrate{};
		bool hasGyro{};
		bool hasAcc{};
		glm::vec3 gyro{};
		glm::vec3 acc{};
	};

	struct MotionState
	{
		WiiUMotionHandler handler;
		MotionSample data;
		MotionInfoTracking tracking;

		// Dolphin 2606a-compatible IMU state. The pointer stream is captured
		// before emulated Wiimote orientation (including the R 180-degree fix).
		glm::vec3 dolphin_pointer_gyro{};
		glm::vec3 dolphin_pointer_acc{};
		uint64 dolphin_pointer_timestamp{};
		bool dolphin_pointer_has_gyro{};
		bool dolphin_pointer_has_acc{};

		// Dolphin IMUGyroscope stable-mean calibration state.
		glm::vec3 dolphin_gyro_bias{};
		glm::vec3 dolphin_calibration_sum{};
		uint64 dolphin_calibration_count{};
		uint64 dolphin_calibration_start{};
		bool dolphin_calibration_initialized{};
		bool dolphin_calibration_stable{};
		bool dolphin_calibration_complete{};
		float dolphin_sample_rate_hz{};
		glm::vec3 dolphin_motion_gyro{};
		glm::vec3 dolphin_motion_acc{};

		// V21 game-gyro calibration state. This is deliberately separate from
		// the Dolphin/pointer calibration state above.
		glm::vec3 game_gyro_bias{};
		glm::vec3 game_calibration_sum{};
		uint64 game_calibration_count{};
		uint64 game_calibration_start{};
		bool game_calibration_stable{};
		bool game_calibration_complete{};
		float game_sample_rate_hz{};

		MotionState() = default;
	};

	struct JoyConOrientationState
	{
		bool is_left{};
		bool vertical{};
		float motion_scale_x{ 1.0f };
		float motion_scale_y{ 1.0f };
		float motion_scale_z{ 1.0f };
		float gyro_deadzone_degrees{ 2.0f };
		// Game gyro and pointer use separate stable-window timers.
		float calibration_period_seconds{ 3.0f };
		float pointer_calibration_period_seconds{ 3.0f };
	};

	inline static std::unordered_map<SDL_JoystickID, MotionState> s_motion_states{};
	inline static std::unordered_map<SDL_JoystickID, JoyConOrientationState> s_joycon_orientation_states{};
};
