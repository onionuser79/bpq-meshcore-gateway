import yaml
from dataclasses import dataclass


@dataclass
class GatewayConfig:
    callsign: str
    idle_timeout: int


@dataclass
class BpqConfig:
    host: str
    port: int


@dataclass
class MeshcoreConfig:
    connection: str
    device: str
    baud: int
    channel_idx: int


@dataclass
class Config:
    gateway: GatewayConfig
    bpq: BpqConfig
    meshcore: MeshcoreConfig


def load_config(path: str = "config.yaml") -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    return Config(
        gateway=GatewayConfig(
            callsign=raw["gateway"]["callsign"].upper(),
            idle_timeout=raw["gateway"]["idle_timeout"],
        ),
        bpq=BpqConfig(
            host=raw["bpq"]["host"],
            port=raw["bpq"]["port"],
        ),
        meshcore=MeshcoreConfig(
            connection=raw["meshcore"]["connection"],
            device=raw["meshcore"]["device"],
            baud=raw["meshcore"]["baud"],
            channel_idx=raw["meshcore"]["channel_idx"],
        ),
    )
