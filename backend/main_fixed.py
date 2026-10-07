import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import engine, Base, SessionLocal
from middleware.auth import require_admin, get_current_user

from routes.auth import router as auth_router, create_default_users
from routes.menu import router as menu_router
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

import models

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI Restaurant Management System",
    description="AI-powered restaurant management backend",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
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
