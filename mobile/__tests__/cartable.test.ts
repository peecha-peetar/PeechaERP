import { WorkInboxItem } from "../src/api/workflowTypes";
import { cardAction, dueLabel, filterInbox, toneColor, URGENCY_COLOR, urgencyOf } from "../src/workflow";

function item(over: Partial<WorkInboxItem>): WorkInboxItem {
  return {
    key: "WF:1", source: "WF", source_label: "گردش کار", kind: "APPROVAL", kind_label: "تایید", ref_id: 1, title: "سفارش",
    subtitle: "", due_at: null, is_overdue: false, priority_code: "NORMAL", priority_label: "عادی", created_at: null,
    can_decide: true, status_note: "", definition: null, ...over,
  };
}

describe("کارتابل یکپارچه", () => {
  const now = new Date(2026, 9, 8, 10, 0);

  it("فوریت: عقب‌افتاده، امروز، فوری، عادی", () => {
    expect(urgencyOf(item({ is_overdue: true }), now)).toBe("overdue");
    expect(urgencyOf(item({ due_at: new Date(2026, 9, 8, 18, 0).toISOString() }), now)).toBe("today");
    expect(urgencyOf(item({ priority_code: "CRITICAL" }), now)).toBe("high");
    expect(urgencyOf(item({}), now)).toBe("normal");
    expect(URGENCY_COLOR.overdue).toBe("danger");
  });

  it("برچسب مهلت روی کارت", () => {
    expect(dueLabel(item({ is_overdue: true, due_at: new Date(2026, 9, 5, 10, 0).toISOString() }), now)).toBe("3 روز گذشته");
    expect(dueLabel(item({ due_at: new Date(2026, 9, 8, 18, 0).toISOString() }), now)).toBe("موعد امروز");
    expect(dueLabel(item({ due_at: new Date(2026, 9, 20).toISOString() }), now)).toBeNull();
    expect(dueLabel(item({}), now)).toBeNull();
  });

  it("رنگ نوع کار و دکمهٔ هر کارت", () => {
    expect(toneColor("approve")).toBe("info");
    expect(toneColor("customer")).toBe("success");
    expect(toneColor("followup")).toBe("warning");
    expect(cardAction(item({ source: "CARTABLE" }))).toBe("DECIDE_INLINE");
    expect(cardAction(item({ source: "WF" }))).toBe("OPEN_TASK");
    expect(cardAction(item({ source: "CUSTOMER" }))).toBe("OPEN_CUSTOMER");
    expect(cardAction(item({ source: "CRM" }))).toBe("OPEN_FOLLOWUPS");
    expect(cardAction(item({ source: "DOC" }))).toBe("DESKTOP_ONLY");
    expect(cardAction(item({ source: "MINE" }))).toBe("WAITING");
  });

  it("درخواست‌های من در همان کارتابل", () => {
    const mine = [item({ key: "MINE:5", source: "MINE", kind: "REQUEST" })];
    const work = [item({}), item({ key: "CRM:1", source: "CRM", kind: "FOLLOWUP" })];
    expect(filterInbox(work, "MINE", mine)).toEqual(mine);
    expect(filterInbox(work, "APPROVAL", mine).map((i) => i.key)).toEqual(["WF:1"]);
    expect(filterInbox(work, "ALL", mine)).toHaveLength(2);
  });
});
