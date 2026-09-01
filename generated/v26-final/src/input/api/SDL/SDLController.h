#pragma once

#include "input/api/Controller.h"
#include "input/api/SDL/SDLControllerProvider.h"

#include <SDL3/SDL_gamepad.h>
#include <chrono>

class SDLController : public Controller<SDLControllerProvider>
{
public:
	enum class JoyConOrientation : uint8
	{
		Sideways = 0,
		Vertical = 1,
	};

	SDLController(const SDL_GUID& guid, size_t guid_index);
	SDLController(const SDL_GUID& guid, size_t guid_index, std::string_view display_name);
	
	~SDLController() override;
	
	std::string_view api_name() const override
	{
		static_assert(to_string(InputAPI::SDLController) == "SDLController");
		return to_string(InputAPI::SDLController);
	}
	InputAPI::Type api() const override { return InputAPI::SDLController; }

	bool is_connected() override;
	bool connect() override;
	
	bool has_motion() override { return m_has_gyro && m_has_accel; }
	bool has_rumble() override { return m_has_rumble; }
	
	void start_rumble() override;
	void stop_rumble() override;

	MotionSample get_motion_sample() override;

	std::string get_button_name(uint64 button) const override;
	const SDL_GUID& get_guid() const { return m_guid; }

	bool is_left_joycon() const;
	bool is_right_joycon() const;
	bool is_joycon() const { return is_left_joycon() || is_right_joycon(); }

	JoyConOrientation get_joycon_orientation() const { return m_joycon_orientation.load(std::memory_order_relaxed); }
	void set_joycon_orientation(JoyConOrientation orientation, bool notify = true);
	std::vector<uint32> get_vertical_hotkey() const;
	std::vector<uint32> get_sideways_hotkey() const;
	std::vector<uint32> get_pointer_hotkey() const;
	void set_vertical_hotkey(std::vector<uint32> buttons);
	void set_sideways_hotkey(std::vector<uint32> buttons);
	void set_pointer_hotkey(std::vector<uint32> buttons);
	bool is_pointer_enabled() const { return m_pointer_enabled.load(std::memory_order_relaxed); }
	void set_pointer_enabled(bool enabled, bool notify = true);
	void recenter_joycon_pointer(bool notify = true);
	bool update_joycon_pointer(glm::vec2& position, glm::vec2& previous);
	bool get_joycon_pointer_debug(glm::vec2& sensor_target, glm::vec2& deadzone_target, glm::vec2& output) const;
	bool get_dolphin_motion_debug(SDLControllerProvider::DolphinMotionDebug& debug) const;
	std::vector<uint32> get_pointer_recenter_hotkey() const;
	void set_pointer_recenter_hotkey(std::vector<uint32> buttons);

	float get_pointer_yaw_degrees() const { return m_pointer_yaw_degrees.load(std::memory_order_relaxed); }
	float get_pointer_pitch_degrees() const { return m_pointer_pitch_degrees.load(std::memory_order_relaxed); }
	float get_pointer_deadzone_degrees() const { return m_pointer_deadzone_degrees.load(std::memory_order_relaxed); }
	float get_pointer_smoothing() const { return m_pointer_smoothing.load(std::memory_order_relaxed); }
	bool get_pointer_invert_x() const { return m_pointer_invert_x.load(std::memory_order_relaxed); }
	bool get_pointer_invert_y() const { return m_pointer_invert_y.load(std::memory_order_relaxed); }
	void set_pointer_calibration(float horizontal_fov_degrees, float vertical_fov_degrees, float deadzone_degrees, float smoothing, bool invert_x, bool invert_y);
	float get_dolphin_total_yaw_degrees() const { return m_dolphin_total_yaw_degrees.load(std::memory_order_relaxed); }
	float get_dolphin_accel_influence() const { return m_dolphin_accel_influence.load(std::memory_order_relaxed); }
	float get_dolphin_gyro_deadzone_degrees() const { return m_dolphin_gyro_deadzone_degrees.load(std::memory_order_relaxed); }
	float get_dolphin_calibration_period_seconds() const { return m_dolphin_calibration_period_seconds.load(std::memory_order_relaxed); }
	float get_pointer_calibration_period_seconds() const { return m_pointer_calibration_period_seconds.load(std::memory_order_relaxed); }
	void set_dolphin_motion_settings(float total_yaw_degrees, float accel_influence, float gyro_deadzone_degrees, float calibration_period_seconds);
	void set_pointer_calibration_period_seconds(float calibration_period_seconds);

	void get_motion_scale(float& x, float& y, float& z) const;
	void set_motion_scale(float x, float y, float z);
	std::vector<uint32> get_pressed_buttons_for_hotkey();

	void save(pugi::xml_node& node) override;
	void load(const pugi::xml_node& node) override;

	constexpr static SDL_GUID kLeftJoyCon{ 0x03, 0x00, 0x00, 0x00, 0x7e, 0x05, 0x00, 0x00, 0x06, 0x20, 0x00, 0x00, 0x00, 0x00,0x68 ,0x00 };
	constexpr static SDL_GUID kRightJoyCon{ 0x03, 0x00, 0x00, 0x00, 0x7e, 0x05, 0x00, 0x00, 0x07, 0x20, 0x00, 0x00, 0x00, 0x00, 0x68, 0x00 };
	constexpr static SDL_GUID kSwitchProController{ 0x03, 0x00, 0x00, 0x00, 0x7e, 0x05, 0x00, 0x00, 0x09, 0x20, 0x00, 0x00, 0x00, 0x00, 0x68, 0x00 };

protected:
	ControllerState raw_state() override;

private:
	inline static SDL_GUID kEmptyGUID{};

	size_t m_guid_index;
	SDL_GUID m_guid;
	mutable std::recursive_mutex m_controller_mutex;
	SDL_Gamepad* m_controller = nullptr;
	SDL_JoystickID m_diid = -1;

	bool m_has_gyro = false;
	bool m_has_accel = false;
	bool m_has_rumble = false;
	
	std::array<bool, SDL_GAMEPAD_BUTTON_COUNT> m_buttons{};
	std::array<bool, SDL_GAMEPAD_AXIS_COUNT> m_axis{};

	std::atomic<JoyConOrientation> m_joycon_orientation{ JoyConOrientation::Sideways };
	std::vector<uint32> m_vertical_hotkey{};
	std::vector<uint32> m_sideways_hotkey{};
	std::vector<uint32> m_pointer_hotkey{};
	std::vector<uint32> m_pointer_recenter_hotkey{};
	std::atomic_bool m_pointer_enabled{ true };
	// V13: these legacy profile fields now carry Dolphin Horizontal/Vertical FOV.
	std::atomic<float> m_pointer_yaw_degrees{ 42.0f };
	std::atomic<float> m_pointer_pitch_degrees{ 31.5f };
	std::atomic<float> m_dolphin_total_yaw_degrees{ 25.0f };
	std::atomic<float> m_dolphin_accel_influence{ 0.01f };
	std::atomic<float> m_dolphin_gyro_deadzone_degrees{ 2.0f };
	// Game gyro period remains the existing Dolphin-labelled profile field.
	std::atomic<float> m_dolphin_calibration_period_seconds{ 3.0f };
	std::atomic<float> m_pointer_calibration_period_seconds{ 3.0f };
	// V11 defaults: small angular tremor rejection + light temporal interpolation.
	std::atomic<float> m_pointer_deadzone_degrees{ 0.35f };
	std::atomic<float> m_pointer_smoothing{ 0.10f };
	std::atomic_bool m_pointer_invert_x{ false };
	std::atomic_bool m_pointer_invert_y{ false };

	std::atomic<float> m_motion_scale_x{ 1.0f };
	std::atomic<float> m_motion_scale_y{ 1.0f };
	std::atomic<float> m_motion_scale_z{ 1.0f };

	mutable std::mutex m_joycon_pointer_mutex;
	bool m_joycon_pointer_initialized = false;
	// Dolphin IMUCursorState: rotation of world around device + recentered pitch.
	std::array<float, 4> m_dolphin_pointer_rotation{ 1.0f, 0.0f, 0.0f, 0.0f }; // w,x,y,z
	float m_dolphin_recentered_pitch = 0.0f;
	uint64 m_dolphin_pointer_last_sensor_timestamp = 0;
	uint64 m_dolphin_pointer_last_output_timestamp = 0;
	bool m_dolphin_recenter_requested = true;
	glm::vec2 m_dolphin_pointer_sensor_target{ 0.5f, 0.5f };
	glm::vec2 m_dolphin_pointer_target{ 0.5f, 0.5f };
	glm::vec2 m_joycon_pointer_position{ 0.5f, 0.5f };
	glm::vec2 m_joycon_pointer_previous{ 0.5f, 0.5f };

	bool m_vertical_hotkey_latched = false;
	bool m_sideways_hotkey_latched = false;
	bool m_pointer_hotkey_latched = false;
	bool m_pointer_recenter_hotkey_latched = false;

	bool is_hotkey_pressed(const ControllerButtonState& buttons, const std::vector<uint32>& hotkey, size_t minimum_buttons = 2) const;
	void consume_hotkey(ControllerButtonState& buttons, const std::vector<uint32>& hotkey) const;
	void apply_vertical_transform(ControllerState& state) const;
	void normalize_hotkey(std::vector<uint32>& buttons) const;
};

