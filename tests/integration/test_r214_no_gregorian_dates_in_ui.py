"""طبقِ درخواستِ صریحِ کاربر («همه‌جا فقط تاریخِ شمسی باشه»): این تست
دیتابیس لازم ندارد -- فقط یک نگهبانِ سبک است که کدِ src/peecha/ui/ را
برایِ الگوهایِ شناخته‌شده‌یِ نمایشِ تاریخِ میلادی به کاربر (که قبلاً
پیدا و رفع شدند) می‌گردد، تا این باگ در آینده به‌صورتِ خاموش برنگردد.
عمداً در همین پوشه‌یِ tests/integration/ است تا با run_all.sh یکجا اجرا
شود؛ گروهِ PEECHA_DB_NAME هم دارد (خالی) که اسکریپت به مشکل نخورد،
هرچند اصلاً به دیتابیس وصل نمی‌شود."""
import os, re, sys
# دیتابیس لازم ندارد، ولی run_all.sh بر اساسِ همین الگوی دقیق (نه
# setdefault) گروه‌بندیِ اسکریپت‌ها را تشخیص می‌دهد.
os.environ["PEECHA_DB_NAME"] = "peecha_test_r214_1"

FAIL = False
def check(cond, msg):
    global FAIL
    if not cond:
        FAIL = True
        print("FAIL:", msg)
    else:
        print("OK:", msg)

_UI_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "peecha", "ui")

# فقط ساعت (بدونِ تاریخ) گاهی هنوز strftime دارد -- تقویم‌ناپذیر است،
# مشکلی ندارد؛ این‌ها را نادیده می‌گیریم.
_TIME_ONLY_STRFTIME = re.compile(r"""\.strftime\((['"])%H[:\s]%M\1\)""")

_VIOLATION_PATTERNS = [
    ("isoformat()", re.compile(r"\.isoformat\(\)")),
    ("QDateEdit(", re.compile(r"\bQDateEdit\(")),
]


def _check_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    findings = []
    for line_no, line in enumerate(lines, start=1):
        for label, pattern in _VIOLATION_PATTERNS:
            if pattern.search(line):
                findings.append(f"{path}:{line_no}: {label} -- {line.strip()}")
        for m in re.finditer(r"\.strftime\(([^)]*)\)", line):
            if _TIME_ONLY_STRFTIME.search(f".strftime({m.group(1)})"):
                continue
            findings.append(f"{path}:{line_no}: strftime(...) با فرمتِ غیرِ-فقط-ساعت -- {line.strip()}")
    return findings


all_findings: list[str] = []
for dirpath, _dirnames, filenames in os.walk(_UI_ROOT):
    for filename in filenames:
        if filename.endswith(".py"):
            all_findings.extend(_check_file(os.path.join(dirpath, filename)))

detail = ("\n  " + "\n  ".join(all_findings)) if all_findings else ""
check(len(all_findings) == 0, f"بدونِ isoformat()/QDateEdit(/strftimeِ تاریخ‌دار در src/peecha/ui/{detail}")

print("RESULT:", "ALL PASS" if not FAIL else "SOME FAILED")
sys.exit(1 if FAIL else 0)
