from aether.config import AetherConfig, MixerConfig, VoxConfig, GestureConfig


def test_mixer_config_defaults():
    cfg = MixerConfig()
    assert cfg.manual_ttl_sec == 600
    assert cfg.tick_interval_sec == 1


def test_vox_config_defaults():
    cfg = VoxConfig()
    assert cfg.enabled is True
    assert cfg.wake_word == "aether"
    assert cfg.command_timeout_sec == 5
    assert cfg.silence_timeout_sec == 1.5
    assert cfg.whisper_model == "small"
    assert cfg.ollama_model == "qwen3.5:4b"
    assert cfg.feedback_flash is True
    assert "UM02" in cfg.mic_source


def test_gesture_config_defaults():
    cfg = GestureConfig()
    assert cfg.enabled is True
    assert cfg.detection_confidence == 0.5
    assert cfg.consecutive_frames == 3
    assert cfg.fist_hold_frames == 9
    assert cfg.cooldown_sec == 5
    assert cfg.feedback_flash is True


def test_aether_config_includes_phase3():
    cfg = AetherConfig()
    assert isinstance(cfg.mixer, MixerConfig)
    assert isinstance(cfg.vox, VoxConfig)
    assert isinstance(cfg.gestures, GestureConfig)
