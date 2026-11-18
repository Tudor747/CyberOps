from ipaddress import IPv4Address
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class BaselineDevice(StrictModel):
    device_ip: IPv4Address
    mac_address: str | None = None
    device_name: str = Field(min_length=1, max_length=80)
    role: str = Field(default='Device', max_length=60)
    authorized_ports: list[int] = Field(default_factory=list, max_length=64)

    @field_validator('authorized_ports')
    @classmethod
    def valid_ports(cls, ports):
        if any(not 1 <= p <= 65535 for p in ports):
            raise ValueError('Ports must be between 1 and 65535')
        return sorted(set(ports))

    @field_validator('mac_address')
    @classmethod
    def valid_mac(cls, value):
        if not value:
            return None
        import re
        if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
            raise ValueError('Use a colon-separated MAC address')
        return value.upper()


class RetestRequest(StrictModel):
    target_ip: IPv4Address
    target_port: int = Field(ge=1, le=65535)


class NetworkSelection(StrictModel):
    network: str = Field(max_length=32)
    interface: str = Field(min_length=1, max_length=256)


class DiagnosticRequest(StrictModel):
    component: Literal['nrf1', 'nrf2', 'rfid', 'cc1101', 'ir_rx', 'ir_tx', 'radar', 'ethernet']
    duration_s: int = Field(default=15, ge=3, le=30)
    frequency_mhz: float = Field(default=433.92, ge=433.05, le=434.79)
    modulation: Literal['OOK', '2FSK', 'GFSK'] = 'OOK'
    address: int = Field(default=4, ge=0, le=255)


class VulnerabilityFinding(StrictModel):
    target_ip: IPv4Address
    risk_level: Literal['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
    is_justified: bool
    description: str = Field(max_length=2000, description='Finding in English')
    recommended_remediation: str = Field(max_length=2000, description='Operator recommendation in English; never executable code')


class AIAnalysisReport(StrictModel):
    overall_threat_score: int = Field(ge=0, le=100)
    summary: str = Field(max_length=4000, description='Executive summary in English')
    findings: list[VulnerabilityFinding] = Field(max_length=256)
