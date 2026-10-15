"""اجراکنندهٔ مستقل زمان‌بند گردش کار برای سرور (وقتی هیچ برنامهٔ دسکتاپی باز نیست).

    python -m peecha.services.workflow.worker            # هر ۳۰ ثانیه
    python -m peecha.services.workflow.worker --once     # یک دور

چند اجراکنندهٔ هم‌زمان (چند سرور یا دسکتاپ) امن‌اند؛ هر کار فقط یک‌بار برداشته می‌شود.
"""

from __future__ import annotations

import argparse
import time

from peecha.services.workflow import scheduler


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="زمان‌بند گردش کار پیچا")
    parser.add_argument("--once", action="store_true", help="فقط یک دور اجرا شود")
    parser.add_argument("--interval", type=int, default=30, help="فاصلهٔ دورها (ثانیه)")
    args = parser.parse_args(argv)
    while True:
        counts = scheduler.tick(None)
        if args.once:
            print(counts)
            return
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()
