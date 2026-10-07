import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from database import engine, Base, SessionLocal
from middleware.auth import require_admin, get_current_user

from routes.auth import router as auth_router, create_default_users
from routes.menu import router as menu_router, MENU_IMAGE_DIR
from routes.orders import router as orders_router
from routes.reservation import router as reservation_router
from routes.customers import router as customers_router
from routes.inventory import router as inventory_router
from routes.kitchen import router as kitchen_router
from routes.analytics import router as analytics_router
from routes.ai import router as ai_router
from routes.settings import router as settings_router
from routes.dashboard import router as dashboard_router
from routes.users import router as users_router
from routes.reviews import router as reviews_router
from routes.suppliers import router as suppliers_router
from routes.staff import router as staff_router
from routes.waste import router as waste_router
from routes.tables import router as tables_router
from routes.customer_bill import router as customer_bill_router
from routes.payments import router as payments_router

import models

Base.metadata.create_all(bind=engine)

# create_all() never adds columns to an existing table, so any field
# added to models.py after the first run is applied here.
from migrations import apply_missing_columns

apply_missing_columns()

# Phase 7F. Validate the payment configuration BEFORE anything else is
# wired up, so a misconfigured deployment refuses to boot.
#
# The alternative - starting anyway and discovering the problem when a
# customer tries to pay - is much worse. It is also the safer
# direction: an incomplete Razorpay configuration raises here rather
# than falling back to the development provider, so nobody can end up
# running a "live" checkout that only ever simulates.
from services.payment_provider import (
    PaymentConfigurationError,
    validate_configuration,
)

try:
    payment_config = validate_configuration()
except PaymentConfigurationError as config_error:
    raise RuntimeError(
        "Payment configuration is not usable: "
        f"{config_error}"
    ) from config_error

print(
    "  payments: "
    f"mode={payment_config.get('mode')} "
    f"provider={payment_config.get('provider')} "
    f"enabled={payment_config.get('payments_enabled')}"
)

MENU_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

from routes.auth import create_default_users
create_default_users(db=SessionLocal())

app = FastAPI(
    title="AI Restaurant Management System",
    description="AI-powered restaurant management backend",
    version="1.0.0",
)

# Dish images uploaded from the admin menu management page.
app.mount(
    "/static",
    StaticFiles(directory=str(MENU_IMAGE_DIR.parent)),
    name="static",
)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

# Vite falls back to the next free port when 5173 is busy, so a fixed
# allowlist breaks the dev server on any other port. In development any
# localhost port is accepted; production is limited to CORS_ORIGINS.
DEV_ALLOW_ANY_LOCALHOST = (
    os.getenv("ENVIRONMENT", "development").strip().lower() != "production"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=(
        r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
        if DEV_ALLOW_ANY_LOCALHOST
        else None
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "AI Restaurant Management System API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    response = await call_next(request)
    return response

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

app.include_router(auth_router)

app.include_router(menu_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(reservation_router, prefix="/api")
app.include_router(customers_router, prefix="/api")
app.include_router(inventory_router, prefix="/api")
app.include_router(kitchen_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(reviews_router, prefix="/api")
app.include_router(suppliers_router, prefix="/api")
app.include_router(staff_router, prefix="/api")
app.include_router(waste_router, prefix="/api")
app.include_router(tables_router, prefix="/api")
app.include_router(customer_bill_router, prefix="/api")

# Phase 6D. Registered after the bill router because the payment endpoints
# read the same bills; both are independent and neither shadows the other.
app.include_router(payments_router, prefix="/api")
