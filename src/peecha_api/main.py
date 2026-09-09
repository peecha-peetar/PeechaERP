"""نقطهٔ ورودِ سرویسِ API (R131). اجرا: uvicorn peecha_api.main:app --reload

این سرویس یک برنامهٔ کاملاً جدا از اپِ دسکتاپِ PySide6 است -- اپِ
دسکتاپ هم‌چنان مستقیم به دیتابیس وصل می‌ماند و هیچ تغییری نکرده؛ این
سرویس فقط برایِ کلاینت‌هایِ بیرونی (اپِ موبایلِ ویزیتور/راننده، R132)
لازم است."""

from __future__ import annotations

from fastapi import FastAPI

from peecha_api.routers import auth, delivery, orders, pricing, sync, visits

app = FastAPI(title="Peecha Field Sales API", version="R133")

app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(visits.router)
app.include_router(orders.router)
app.include_router(delivery.router)
app.include_router(pricing.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
