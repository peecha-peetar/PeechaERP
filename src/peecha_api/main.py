"""نقطهٔ ورودِ سرویسِ API (R131). اجرا: uvicorn peecha_api.main:app --reload

این سرویس یک برنامهٔ کاملاً جدا از اپِ دسکتاپِ PySide6 است -- اپِ
دسکتاپ هم‌چنان مستقیم به دیتابیس وصل می‌ماند و هیچ تغییری نکرده؛ این
سرویس فقط برایِ کلاینت‌هایِ بیرونی (اپِ موبایلِ ویزیتور/راننده، R132)
لازم است."""

from __future__ import annotations

from fastapi import FastAPI

from peecha_api.routers import (
    approvals,
    auth,
    customers,
    dashboard,
    delivery,
    inventory,
    notifications,
    orders,
    payments,
    pricing,
    products,
    routes,
    sync,
    visits,
)

app = FastAPI(title="Peecha Field Sales API", version="R182")

app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(visits.router)
app.include_router(orders.router)
app.include_router(delivery.router)
app.include_router(pricing.router)
app.include_router(payments.router)
app.include_router(customers.router)
app.include_router(routes.router)
app.include_router(products.router)
app.include_router(inventory.router)
app.include_router(approvals.router)
app.include_router(notifications.router)
app.include_router(dashboard.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
