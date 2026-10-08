"""نقطهٔ ورود سرویس API (R131). اجرا: uvicorn peecha_api.main:app --reload

این سرویس یک برنامهٔ کاملاً جدا از اپ دسکتاپ PySide6 است — اپ
دسکتاپ هم‌چنان مستقیم به دیتابیس وصل می‌ماند و هیچ تغییری نکرده؛ این
سرویس فقط برای کلاینت‌های بیرونی (برنامهٔ موبایل ویزیتور/راننده، R132)
لازم است."""

from __future__ import annotations

from fastapi import FastAPI

from peecha_api.routers import (
    approvals,
    auth,
    collection,
    crm,
    customers,
    dashboard,
    delivery,
    fixed_assets,
    inventory,
    locations,
    manager_dashboard,
    notifications,
    orders,
    payments,
    pricing,
    products,
    routes,
    smart_sales,
    sync,
    vehicle_settlement,
    visits,
)

app = FastAPI(title="Peecha Field Sales API", version="R186")

# R295: اتصال ماژول‌ها به گردش کار (رویدادهای خودکار و قفل تایید، مثل دسکتاپ)
from peecha.services.workflow import registry as _wf_registry  # noqa: E402

_wf_registry.ensure_loaded()

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
app.include_router(smart_sales.router)
app.include_router(manager_dashboard.router)
app.include_router(collection.router)
app.include_router(vehicle_settlement.router)
app.include_router(locations.router)  # R248: محلِ انبار (اسکن/محتوا/جانمایی/برداشت)
app.include_router(fixed_assets.router)  # R265: اسکنِ دارایی و شمارشِ فیزیکی
app.include_router(crm.router)  # R281: CRM


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
