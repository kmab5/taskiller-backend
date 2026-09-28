from fastapi import APIRouter

from taskiller.analytics.routes import router as analytics_router
from taskiller.auth.routes import router as auth_router
from taskiller.execution.routes import router as execution_router
from taskiller.focus.routes import router as focus_router
from taskiller.users.routes import router as users_router
from taskiller.work.routes import router as work_router

api_router = APIRouter()
api_router.include_router(analytics_router)
api_router.include_router(auth_router)
api_router.include_router(execution_router)
api_router.include_router(focus_router)
api_router.include_router(users_router)
api_router.include_router(work_router)
