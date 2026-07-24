from __future__ import annotations

import socket

from zeroconf import ServiceInfo, Zeroconf

from app.core.logging import get_logger
from app.discovery.config import MdnsConfig
from app.discovery.interface_selector import select_advertise_ip

logger = get_logger(__name__)


class ZeroconfAdvertiser:
    def __init__(self, config: MdnsConfig) -> None:
        self._config = config
        self._zeroconf: Zeroconf | None = None
        self._service_info: ServiceInfo | None = None
        self._advertised_ip: str | None = None

    @property
    def advertised_ip(self) -> str | None:
        return self._advertised_ip

    def register(self) -> None:
        advertised_ip = select_advertise_ip(self._config.advertise_ip)
        service_type = self._config.zeroconf_service_type
        info = ServiceInfo(
            type_=service_type,
            name=self._config.service_instance_name,
            addresses=[socket.inet_aton(advertised_ip)],
            port=self._config.port,
            properties=self._config.txt_records,
            server="labinventory.local.",
        )
        zeroconf = Zeroconf()
        try:
            zeroconf.register_service(info)
        except Exception:
            zeroconf.close()
            logger.exception(
                "mDNS registration failed",
                extra={"event": "mdns.registration.failure"},
            )
            raise
        self._zeroconf = zeroconf
        self._service_info = info
        self._advertised_ip = advertised_ip
        logger.info(
            "mDNS service registered",
            extra={
                "event": "mdns.registration",
                "mdns_service_type": service_type,
                "mdns_service_name": self._config.service_instance_name,
                "mdns_advertise_ip": advertised_ip,
                "mdns_port": self._config.port,
            },
        )

    def unregister(self) -> None:
        if self._zeroconf is None or self._service_info is None:
            return
        try:
            self._zeroconf.unregister_service(self._service_info)
            logger.info(
                "mDNS service unregistered",
                extra={"event": "mdns.unregistration"},
            )
        finally:
            self._zeroconf.close()
            self._zeroconf = None
            self._service_info = None
