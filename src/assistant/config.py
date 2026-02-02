# Configuration Centralisee

import os
import json
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum



class RunMode(Enum):
    # Modes d'execution.
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    SIMULATION = "simulation"
    TEST = "test"



@dataclass
class OpenAIConfig:
    # Configuration OpenAI Realtime API.
    api_key: str = ""
    model: str = "gpt-4o-realtime-preview-2024-12-17"
    voice: str = "shimmer"
    temperature: float = 0.8
    max_response_tokens: int = 4096

    # VAD
    vad_threshold: float = 0.5
    vad_prefix_padding_ms: int = 300
    vad_silence_duration_ms: int = 500

    # Audio
    input_sample_rate: int = 24000
    output_sample_rate: int = 24000

    def __post_init__(self):
        # Gere init.
        if not self.api_key:
            self.api_key = os.getenv("OPENAI_API_KEY", "")


@dataclass
class AudioConfig:
    # Configuration audio.
    # Microphone
    input_device_index: Optional[int] = None
    input_sample_rate: int = 24000
    input_channels: int = 1
    input_chunk_size: int = 1024

    # Sortie audio
    output_device_index: Optional[int] = None
    output_sample_rate: int = 24000
    output_channels: int = 1

    # Half-duplex
    cooldown_duration_ms: int = 500
    min_speech_duration_ms: int = 100

    # Volumes
    input_gain: float = 1.0
    output_volume: float = 0.8

    # Processing preset
    processing_preset: str = "noisy_room"


@dataclass
class VisionConfig:
    # Configuration module vision.
    # Camera
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30

    # Capture multi-images
    num_frames: int = 3
    capture_interval_ms: int = 200

    # VLM
    vlm_model: str = "mlx-community/Qwen2-VL-2B-Instruct-4bit"
    vlm_max_tokens: int = 100

    # Seuils de confiance
    confidence_high: float = 0.85
    confidence_medium: float = 0.60
    confidence_low: float = 0.40

    # Barcode
    barcode_min_detections: int = 2


@dataclass
class DatabaseConfig:
    # Configuration base de donnees.
    db_path: str = "data/products.db"
    blacklist_path: str = "data/blacklist.json"

    # Performance
    cache_size: int = 1000
    fuzzy_threshold: float = 0.6
    max_search_results: int = 20


@dataclass
class SecurityConfig:
    # Configuration module securite.
    filter_latency_target_ms: float = 1.0
    audio_directory: str = "data/security_audio"
    block_on_high_severity: bool = True
    log_all_alerts: bool = True
    strict_mode: bool = True


@dataclass
class OrchestratorConfig:
    # Configuration orchestrateur.
    # Timeouts (secondes)
    idle_timeout: float = 60.0
    greeting_timeout: float = 10.0
    intent_timeout: float = 30.0
    scan_timeout: float = 15.0
    confirm_timeout: float = 20.0
    conversation_timeout: float = 45.0

    # LEDs
    led_fade_duration_ms: int = 300

    # Queues
    max_queue_size: int = 100

    # Logging
    log_transitions: bool = True


@dataclass
class TabletConfig:
    # Configuration interface tablette.
    ws_host: str = "0.0.0.0"
    ws_port: int = 8765
    ping_interval: float = 30.0
    ping_timeout: float = 10.0
    reconnect_delay: float = 5.0


@dataclass
class PepperConfig:
    # Configuration robot Pepper.
    ip: str = ""
    port: int = 9559

    # Comportement
    autonomous_life: bool = False
    breathing: bool = True
    speaking_movement: bool = True

    # LEDs
    led_intensity: float = 1.0
    gesture_speed: float = 1.0


@dataclass
class LoggingConfig:
    # Configuration logging.
    log_directory: str = "logs"
    log_file_prefix: str = "pepper_assistant"
    format_jsonl: bool = True
    include_timestamps: bool = True
    console_level: str = "INFO"
    file_level: str = "DEBUG"
    max_file_size_mb: int = 10
    backup_count: int = 5



@dataclass
class Config:
    # Configuration principale du systeme.

    mode: RunMode = RunMode.DEVELOPMENT
    PRODUCTION_MODE: bool = False

    # Sous-configurations
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    tablet: TabletConfig = field(default_factory=TabletConfig)
    pepper: PepperConfig = field(default_factory=PepperConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # Chemins
    project_root: str = ""

    def __post_init__(self):
        # Gere init.
        self.PRODUCTION_MODE = (self.mode == RunMode.PRODUCTION)

        if not self.project_root:
            # Remonter depuis src/assistant/ jusqu'a la racine du projet
            self.project_root = str(Path(__file__).parent.parent.parent)

        self._resolve_paths()

    def _resolve_paths(self):
        # Resout les chemins relatifs en chemins absolus.
        root = Path(self.project_root)

        # Database
        if not Path(self.database.db_path).is_absolute():
            self.database.db_path = str(root / self.database.db_path)

        if not Path(self.database.blacklist_path).is_absolute():
            self.database.blacklist_path = str(root / self.database.blacklist_path)

        # Logging
        if not Path(self.logging.log_directory).is_absolute():
            self.logging.log_directory = str(root / self.logging.log_directory)

        # Security audio
        if not Path(self.security.audio_directory).is_absolute():
            self.security.audio_directory = str(root / self.security.audio_directory)

    def to_dict(self) -> Dict[str, Any]:
        # Convertit la configuration en dictionnaire.
        result = {}
        for key, value in asdict(self).items():
            if isinstance(value, Enum):
                result[key] = value.value
            else:
                result[key] = value
        return result

    def save(self, path: str):
        # Sauvegarde la configuration dans un fichier JSON.
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> 'Config':
        # Charge la configuration depuis un fichier JSON ou YAML.
        with open(path, 'r', encoding='utf-8') as f:
            if path.endswith('.yaml') or path.endswith('.yml'):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)

        config = cls()

        if 'mode' in data:
            config.mode = RunMode(data['mode'])
            config.PRODUCTION_MODE = (config.mode == RunMode.PRODUCTION)

        # Charger les sous-configurations
        if 'openai' in data:
            config.openai = OpenAIConfig(**data['openai'])
        if 'audio' in data:
            config.audio = AudioConfig(**data['audio'])
        if 'vision' in data:
            config.vision = VisionConfig(**data['vision'])
        if 'database' in data:
            config.database = DatabaseConfig(**data['database'])
        if 'security' in data:
            config.security = SecurityConfig(**data['security'])
        if 'orchestrator' in data:
            config.orchestrator = OrchestratorConfig(**data['orchestrator'])
        if 'tablet' in data:
            config.tablet = TabletConfig(**data['tablet'])
        if 'pepper' in data:
            config.pepper = PepperConfig(**data['pepper'])
        if 'logging' in data:
            config.logging = LoggingConfig(**data['logging'])

        if 'project_root' in data:
            config.project_root = data['project_root']

        config._resolve_paths()
        return config



def get_development_config() -> Config:
    # Configuration pour le developpement.
    return Config(
        mode=RunMode.DEVELOPMENT,
        openai=OpenAIConfig(temperature=0.8),
        orchestrator=OrchestratorConfig(log_transitions=True),
        logging=LoggingConfig(console_level="DEBUG", file_level="DEBUG"),
    )


def get_production_config() -> Config:
    # Configuration pour la production.
    return Config(
        mode=RunMode.PRODUCTION,
        openai=OpenAIConfig(temperature=0.6),
        orchestrator=OrchestratorConfig(log_transitions=False),
        logging=LoggingConfig(console_level="WARNING", file_level="INFO"),
        pepper=PepperConfig(autonomous_life=False),
    )


def get_simulation_config() -> Config:
    # Configuration pour la simulation (sans materiel).
    return Config(
        mode=RunMode.SIMULATION,
        vision=VisionConfig(camera_index=-1),
        audio=AudioConfig(input_device_index=-1, output_device_index=-1),
        pepper=PepperConfig(ip=""),
        logging=LoggingConfig(console_level="DEBUG"),
    )


def get_test_config() -> Config:
    # Configuration pour les tests.
    return Config(
        mode=RunMode.TEST,
        orchestrator=OrchestratorConfig(
            idle_timeout=5.0,
            greeting_timeout=2.0,
            intent_timeout=5.0,
            scan_timeout=3.0,
            confirm_timeout=5.0,
            conversation_timeout=10.0,
        ),
        logging=LoggingConfig(console_level="WARNING", file_level="DEBUG"),
    )



_config_instance: Optional[Config] = None


def get_config(mode: Optional[RunMode] = None) -> Config:
    # Recupere l'instance de configuration (singleton).
    global _config_instance

    if _config_instance is None:
        if mode is None:
            env_mode = os.getenv("RUN_MODE", "development").lower()
            mode = RunMode(env_mode) if env_mode in [m.value for m in RunMode] else RunMode.DEVELOPMENT

        if mode == RunMode.PRODUCTION:
            _config_instance = get_production_config()
        elif mode == RunMode.SIMULATION:
            _config_instance = get_simulation_config()
        elif mode == RunMode.TEST:
            _config_instance = get_test_config()
        else:
            _config_instance = get_development_config()

    return _config_instance


def reset_config():
    # Reinitialise la configuration (pour les tests).
    global _config_instance
    _config_instance = None
