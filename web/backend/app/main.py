"""FastAPI app — KIDO OCR Web. Chạy: uvicorn app.main:app --host 0.0.0.0 --port 8000

  * Mọi route dưới tiền tố /api. GET /api/health ⇒ {"status": "ok"}.
  * Router auth + admin (Agent AUTH). Router groups/pages (Agent JOBS) import CÓ ĐIỀU KIỆN theo tên module cố
    định `app.api.groups`, `app.api.pages` (mỗi module export `router`). Thiếu module ⇒ log cảnh báo, bỏ qua.
    Router của JOBS có thể khai `APIRouter(prefix="/groups")` hoặc không prefix — main.py tự nhận biết.
  * Chống CSRF: dependency `require_csrf_header` gắn ở CẤP APP ⇒ áp cho mọi POST/PUT/PATCH/DELETE.
  * Lỗi luôn trả dạng {"detail": {"code": "...", "message": "tiếng Việt"}}.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, auth
from app.api.deps import require_csrf_header
from app.core import security

log = logging.getLogger("app.main")

API_PREFIX = "/api"
OPTIONAL_ROUTERS = (("app.api.groups", "groups"), ("app.api.pages", "pages"))

_DEFAULT_CODES = {
    400: ("BAD_REQUEST", "Yêu cầu không hợp lệ."),
    401: ("NOT_AUTHENTICATED", "Bạn chưa đăng nhập hoặc phiên đăng nhập đã hết hạn."),
    403: ("FORBIDDEN", "Bạn không có quyền thực hiện thao tác này."),
    404: ("NOT_FOUND", "Không tìm thấy tài nguyên."),
    405: ("METHOD_NOT_ALLOWED", "Phương thức không được hỗ trợ."),
    409: ("CONFLICT", "Xung đột dữ liệu."),
    413: ("PAYLOAD_TOO_LARGE", "Dữ liệu gửi lên quá lớn."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Định dạng dữ liệu không được hỗ trợ."),
    422: ("VALIDATION_ERROR", "Dữ liệu không hợp lệ."),
    429: ("TOO_MANY_REQUESTS", "Quá nhiều yêu cầu, vui lòng thử lại sau."),
}


def _error_body(status_code: int, detail: Any) -> dict:
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        return {"detail": detail}
    code, message = _DEFAULT_CODES.get(status_code, (f"HTTP_{status_code}", "Lỗi yêu cầu."))
    body: dict[str, Any] = {"code": code, "message": message}
    if isinstance(detail, str) and detail and detail not in ("Not Found", "Method Not Allowed"):
        body["raw"] = detail
    return {"detail": body}


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=_error_body(exc.status_code, exc.detail),
                        headers=getattr(exc, "headers", None))


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
              for e in exc.errors()]
    fields = [".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")) for e in errors]
    fields = [f for f in fields if f]
    message = "Dữ liệu không hợp lệ" + (f": {', '.join(sorted(set(fields)))}." if fields else ".")
    return JSONResponse(status_code=422, content=jsonable_encoder(
        {"detail": {"code": "VALIDATION_ERROR", "message": message, "errors": errors}}))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Lỗi không xử lý tại %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": {
        "code": "INTERNAL_ERROR", "message": "Lỗi hệ thống. Vui lòng thử lại hoặc liên hệ quản trị viên."}})


def _include_optional_router(app: FastAPI, module_name: str, resource: str) -> bool:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            log.warning("Chưa có module %s — bỏ qua router %s/%s", module_name, API_PREFIX, resource)
        else:
            log.error("Module %s thiếu phụ thuộc '%s' — bỏ qua router %s/%s", module_name, exc.name,
                      API_PREFIX, resource)
        return False
    router = getattr(module, "router", None)
    if router is None:
        log.error("Module %s không export biến `router` — bỏ qua", module_name)
        return False
    paths = [getattr(r, "path", "") for r in router.routes]
    already_prefixed = bool(paths) and all(p == f"/{resource}" or p.startswith(f"/{resource}/") for p in paths)
    prefix = API_PREFIX if already_prefixed else f"{API_PREFIX}/{resource}"
    app.include_router(router, prefix=prefix)
    log.info("Đã gắn router %s tại %s/%s", module_name, API_PREFIX, resource)
    return True


def create_app() -> FastAPI:
    app = FastAPI(title="KIDO OCR Web API", version="1.0.0", docs_url=f"{API_PREFIX}/docs",
                  openapi_url=f"{API_PREFIX}/openapi.json", redoc_url=None,
                  dependencies=[Depends(require_csrf_header)])
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get(f"{API_PREFIX}/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.state.optional_routers = {
        name: _include_optional_router(app, name, resource) for name, resource in OPTIONAL_ROUTERS
    }

    if security.secret_key_is_weak():
        log.warning("SECRET_KEY ngắn hơn %d byte — KHÔNG dùng cho môi trường thật.", security.MIN_SECRET_KEY_BYTES)
    return app


app = create_app()
