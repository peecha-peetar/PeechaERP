"""R319: اقدام عمومی «ارسال پیام» (پیامک، واتس‌اپ، بله، تلگرام، ایتا، روبیکا یا اعلان داخلی) برای «پیام پس از فرایند».

ارسال از همان مرکز ارتباطات (crm.communication) و ثبت در دفتر پیام‌ها؛ با کلید خاموش هیچ پیامی فرستاده نمی‌شود."""

from __future__ import annotations

from peecha.services.workflow import registry
from peecha.services.workflow.registry import ActionContext, ActionSpec, ParamSpec


def _send(ctx: ActionContext) -> dict:
    from peecha.services.crm import messengers

    return messengers.send_action(ctx)


def _register() -> None:
    from peecha.services.crm import communication as comm
    from peecha.services.crm import messengers

    registry.register_action(ActionSpec(
        "send_message", "ارسال پیام (پیامک، واتس‌اپ یا پیام‌رسان)", _send,
        params=(ParamSpec("channel", "کانال", "choice", "SMS", {k: v for k, v in comm.CHANNELS.items() if k != "INTERNAL"}),
                ParamSpec("template_id", "الگوی پیام", "template"), ParamSpec("body", "متن (اگر الگو نیست)"),
                ParamSpec("recipient", "گیرنده", "choice", "COUNTERPARTY", dict(messengers.RECIPIENTS)),
                ParamSpec("target", "شماره یا شناسهٔ گیرندهٔ ثابت"), ParamSpec("notify_user_id", "کاربر گیرنده", "user")),
        description="پس از رویداد سند، الگوی پیام را برای طرف حساب، گیرندهٔ ثابت یا کاربر می‌فرستد."))


_register()
