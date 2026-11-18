import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Systemd/environment values take precedence over the local development file.
load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=False)


@dataclass
class Settings:
    database: Path = field(default_factory=lambda: Path(os.getenv('FIIRBOTS_DB', 'data/factory_sec.db')))
    network: str = field(default_factory=lambda: os.getenv('FIIRBOTS_SCAN_NETWORK', ''))
    interface: str = field(default_factory=lambda: os.getenv('FIIRBOTS_SCAN_INTERFACE', 'eth0'))
    serial_port: str = field(default_factory=lambda: os.getenv('FIIRBOTS_SERIAL_PORT', ''))
    gpio_enabled: bool = field(default_factory=lambda: os.getenv('FIIRBOTS_GPIO_ENABLED') == '1')
    reboot_enabled: bool = field(default_factory=lambda: os.getenv('FIIRBOTS_REBOOT_ENABLED') == '1')
    api_key: str = field(default_factory=lambda: os.getenv('GEMINI_API_KEY', ''))
    model: str = field(default_factory=lambda: os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))
