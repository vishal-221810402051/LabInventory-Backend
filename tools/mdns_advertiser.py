from __future__ import annotations

import argparse
import signal
import sys
import threading

import httpx

from app.core.config import Settings
from app.core.logging import configure_logging, get_logger
from app.discovery.advertiser import ZeroconfAdvertiser
from app.discovery.config import MdnsConfig

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Advertise LabInventory on the Windows LAN.")
    parser.add_argument(
        "--backend-url",
        default=None,
        help="Backend base URL, default from API_PORT.",
    )
    return parser.parse_args()


def verify_backend(base_url: str) -> dict[str, object]:
    with httpx.Client(timeout=5.0) as client:
        ready = client.get(f"{base_url}/health/ready")
        ready.raise_for_status()
        info = client.get(f"{base_url}/api/v1/system/info")
        info.raise_for_status()
        data = info.json()

    expected = {
        "application": "LabInventory",
        "api_version": "v1",
        "protocol_version": 1,
        "service_type": "_labinventory._tcp.",
        "service_name": "LabInventory Backend",
    }
    for key, expected_value in expected.items():
        if data.get(key) != expected_value:
            msg = f"Incompatible backend system info field {key!r}."
            raise RuntimeError(msg)
    capabilities = data.get("capabilities")
    if capabilities != ["health", "discovery"]:
        msg = "Incompatible backend capabilities."
        raise RuntimeError(msg)
    return data


def main() -> int:
    settings = Settings()
    configure_logging(settings.log_level)
    args = parse_args()
    base_url = args.backend_url or f"http://127.0.0.1:{settings.api_port}"

    logger.info("Verifying backend before mDNS advertisement", extra={"event": "mdns.host.verify"})
    verify_backend(base_url)

    advertiser = ZeroconfAdvertiser(
        MdnsConfig(
            service_name=settings.mdns_service_name,
            service_type=settings.mdns_service_type,
            port=settings.api_port,
            advertise_ip=settings.mdns_advertise_ip,
        )
    )
    stop_event = threading.Event()

    def stop(_: int, __: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    advertiser.register()
    logger.info(
        "Windows host mDNS companion is advertising",
        extra={
            "event": "mdns.host.running",
            "mdns_advertise_ip": advertiser.advertised_ip,
            "mdns_port": settings.api_port,
        },
    )
    try:
        stop_event.wait()
    finally:
        advertiser.unregister()
    return 0


if __name__ == "__main__":
    sys.exit(main())
