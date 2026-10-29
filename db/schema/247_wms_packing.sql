-- پیچا | R361: بسته‌بندی و کنترل ارسال سند فروش (بسته‌ها و اقلام هر بسته)؛ ارسال در comm.shipments ثبت می‌شود
CREATE TABLE IF NOT EXISTS inv.pack_packages (
    package_id         BIGSERIAL      PRIMARY KEY,
    company_id         INT            NOT NULL REFERENCES core.companies(company_id),
    document_id        BIGINT         NOT NULL REFERENCES comm.commercial_documents(document_id),
    package_no         INT            NOT NULL,
    status_code        VARCHAR(10)    NOT NULL DEFAULT 'OPEN',
    weight_kg          NUMERIC(12, 3),
    length_cm          NUMERIC(10, 1),
    width_cm           NUMERIC(10, 1),
    height_cm          NUMERIC(10, 1),
    shipment_id        BIGINT         REFERENCES comm.shipments(shipment_id),
    packed_by_user_id  INT            REFERENCES sec.users(user_id),
    created_at         TIMESTAMPTZ    NOT NULL DEFAULT now(),
    closed_at          TIMESTAMPTZ,
    notes              VARCHAR(300),
    CONSTRAINT uq_pack_packages UNIQUE (document_id, package_no),
    CONSTRAINT ck_pack_packages_status CHECK (status_code IN ('OPEN', 'CLOSED', 'SHIPPED'))
);

CREATE TABLE IF NOT EXISTS inv.pack_package_lines (
    package_line_id    BIGSERIAL      PRIMARY KEY,
    package_id         BIGINT         NOT NULL REFERENCES inv.pack_packages(package_id) ON DELETE CASCADE,
    document_line_id   BIGINT         NOT NULL REFERENCES comm.commercial_document_lines(line_id),
    item_id            INT            NOT NULL REFERENCES inv.items(item_id),
    quantity_base      NUMERIC(18, 6) NOT NULL CHECK (quantity_base > 0),
    packed_by_user_id  INT            REFERENCES sec.users(user_id),
    packed_at          TIMESTAMPTZ    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_pack_package_lines_line ON inv.pack_package_lines(document_line_id);
