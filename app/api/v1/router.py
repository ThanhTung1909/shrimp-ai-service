"""
Router tổng hợp các endpoints API v1 của AquaSense AI Microservice
"""

from fastapi import APIRouter

from app.api.v1.feeding import router as feeding_router
from app.api.v1.predictions import router as predictions_router
from app.api.v1.soft_sensor import router as soft_sensor_router

api_v1_router = APIRouter()

# Đăng ký các module router con
api_v1_router.include_router(feeding_router)
api_v1_router.include_router(predictions_router)
api_v1_router.include_router(soft_sensor_router)
