from fastapi import APIRouter

from taskiller.auth.routes import router as auth_router
from taskiller.users.routes import router as users_router
from taskiller.work.routes import router as work_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(work_router)
