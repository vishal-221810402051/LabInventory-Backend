from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import (
    application_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.api.v1.capture_sessions import router as capture_sessions_router
from app.api.v1.health import router as health_router
from app.api.v1.system import router as system_router
from app.core.config import Settings, get_settings
from app.core.correlation import correlation_id_middleware
from app.core.errors import ApplicationError
from app.core.logging import configure_logging, get_logger
from app.discovery.advertiser import ZeroconfAdvertiser
from app.discovery.config import MdnsConfig
from app.services.system_info import InstanceIdStore, SystemInfoService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("Application startup", extra={"event": "application.startup"})
        advertiser: ZeroconfAdvertiser | None = None
        if resolved_settings.mdns_enabled:
            advertiser = ZeroconfAdvertiser(
                MdnsConfig(
                    service_name=resolved_settings.mdns_service_name,
                    service_type=resolved_settings.mdns_service_type,
                    port=resolved_settings.api_port,
                    advertise_ip=resolved_settings.mdns_advertise_ip,
                )
            )
            try:
                advertiser.register()
            except Exception:
                if resolved_settings.mdns_fail_fast:
                    raise
                logger.warning(
                    "mDNS registration failed; API will continue without advertisement.",
                    extra={"event": "mdns.registration.failure"},
                )
        app.state.mdns_advertiser = advertiser
        try:
            yield
        finally:
            if advertiser is not None:
                advertiser.unregister()
            logger.info("Application shutdown", extra={"event": "application.shutdown"})

    app = FastAPI(
        title="LabInventory Backend",
        version="0.1.0",
        description="Phase 1 API contract for the LabInventory laptop backend.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.system_info_service = SystemInfoService(
        resolved_settings,
        InstanceIdStore(resolved_settings.instance_data_root),
    )

    if resolved_settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Idempotency-Key", "X-Correlation-ID"],
            expose_headers=["X-Correlation-ID"],
        )

    app.middleware("http")(correlation_id_middleware)
    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    app.include_router(health_router)
    app.include_router(system_router)
    app.include_router(capture_sessions_router)
    return app


app = create_app()
