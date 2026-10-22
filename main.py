from fastapi import FastAPI, Depends, HTTPException, Cookie, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from sqlmodel import select, Session, SQLModel
from typing import Annotated
from contextlib import asynccontextmanager
from utils.logging import logger, cleanup_old_logs
from db import dispose_all_tenant_engines
from slowapi.errors import RateLimitExceeded
import asyncio
from fastapi.openapi.utils import get_openapi


# Router imports
from router.appearance import appearance_router
from router.attendance_value import attendancevalue_router
from router.attendance_time import attendance_time_router
from router.teacher_names import teachernames_router
from router.class_names import classnames_router
from router.class_subjects import class_subjects_router
from router.students import students_router
from router.deleted_students import deleted_students_router
from router.mark_attendance import mark_attendance_router
from router.adm_del import adm_del_router
from router.fee import fee_router
from router.income import income_router
from router.income_cat_names import income_cat_names_router
from router.expense_cat_names import expense_cat_names_router
from router.expense import expense_router
from router.dashboard import dashboard_router
from router.admin_create_user import admin_create_user_router
from router.salary import salary_router
from router.debit import debit_router
from router.attendance_review import attendance_review_router
from router.attendance_policy import attendance_policy_router
from router.exam_marks import exam_marks_router
from router.student_profile import student_profile_router
from router.student_portal_auth import student_portal_auth_router
from router.staff import staff_router
from router.staff_profile import staff_profile_router
from router.deleted_staff import deleted_staff_router
from router.permissions import permissions_router
from router.self_attendance import self_attendance_router
from control_plane_client.tenant_branding import tenant_branding_router

# User related imports
from user.user_router import public_router, user_router, admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    try:
        cleanup_old_logs()
        logger.info("Log cleanup process completed")
    except Exception as e:
        logger.error(f"Failed to clean up logs: {str(e)}")

    yield

    logger.info("Application shutting down...")
    try:
        disposed = dispose_all_tenant_engines()
        logger.info(f"Disposed {len(disposed)} tenant engine(s) on shutdown: {disposed}")

        for task in asyncio.all_tasks():
            if not task.done():
                task.cancel()

        logger.info("Shutdown completed successfully")
    except Exception as e:
        logger.error(f"Shutdown error: {str(e)}")

origins = [
    "http://localhost:3000",  # Next.js development server
    "http://127.0.0.1:3000",  # Localhost access with 127.0.0.1
    # "https://mzbs.vercel.app",  # Production frontend
    "https://mzbs.netlify.app",  # Netlify production frontend
    "https://ktns.netlify.app",  # KTNS production frontend
    "https://greenwood-khanschool.netlify.app",  # Greenwood production frontend
    "https://brown-wood-high-school.netlify.app",  # BWH School production frontend
    "https://mzbs-staging-school.netlify.app",  # Staging frontend
    "https://mzbs-temp.vercel.app",  # temporary deployment
]

app = FastAPI(
    title="MMS-GENERAL", 
    description="Manages all API for MMS-GENERAL",
    version="0.1.0",
    openapi_url="/docs/json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

logger.info("Starting application...")

# Security: Exception handler for rate limiting
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(f"Rate limit exceeded for IP: {request.client.host}")
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."}
    )
    
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"UNHANDLED EXCEPTION on {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
# Security: Add HTTPS redirect middleware for production
# This forces all HTTP requests to redirect to HTTPS
# Only active when HTTPS is available (production)
# Disabled for development - enable only in production with SSL certificates
# try:
#     app.add_middleware(HTTPSRedirectMiddleware)
# except Exception:
#     logger.warning("HTTPSRedirectMiddleware not available, skipping")

# Security: Add trusted hosts middleware to prevent Host header attacks
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "localhost",
        "127.0.0.1",
        "mzbs-temp.vercel.app",
        "mzbs.netlify.app",
        "ktns.netlify.app",
        "greenwood-khanschool.netlify.app",
        "brown-wood-high-school.netlify.app",
        "mzbs-staging-school.netlify.app",
        "*.vercel.app",
        "site--mzbs--lvqlqxbx7xgh.code.run",
        "web-production-3b441.up.railway.app",
    ]
)

# Security: Restrict CORS to specific methods and headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],  # Specific methods only
    allow_headers=["Content-Type", "Authorization"],  # Specific headers only
    expose_headers=["Content-Type"],  # Only expose necessary headers
    max_age=3600  # Cache preflight requests for 1 hour
)

# Include routers
app.include_router(appearance_router)
app.include_router(public_router)  # No prefix - routes will be at /login and /signup
app.include_router(user_router)    # Routes will be at /auth/*
app.include_router(admin_router)   # Routes will be at /admin/users/*
app.include_router(admin_create_user_router)
app.include_router(income_cat_names_router)
app.include_router(expense_cat_names_router)
app.include_router(attendancevalue_router)
app.include_router(attendance_time_router)
app.include_router(teachernames_router)
app.include_router(classnames_router)
app.include_router(class_subjects_router)
app.include_router(dashboard_router, tags=["Dashboard"])
app.include_router(expense_router)
app.include_router(fee_router)
app.include_router(income_router)
app.include_router(salary_router)
app.include_router(debit_router)
app.include_router(attendance_review_router)
app.include_router(attendance_policy_router)
app.include_router(students_router)
app.include_router(deleted_students_router)
app.include_router(mark_attendance_router)
app.include_router(exam_marks_router)
app.include_router(student_profile_router)
app.include_router(student_portal_auth_router)
app.include_router(staff_router)
app.include_router(staff_profile_router)
app.include_router(deleted_staff_router)
app.include_router(self_attendance_router)
app.include_router(permissions_router)
app.include_router(adm_del_router)
app.include_router(tenant_branding_router)

@app.get("/", tags=["MMS Backend"])
async def root():
    return {"Message": "MMS Backend is running :-}"}

