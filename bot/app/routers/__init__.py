"""路由包 — 导出所有 API 路由模块。"""
from app.routers.v1 import router as v1_router

__all__ = ["v1_router"]
