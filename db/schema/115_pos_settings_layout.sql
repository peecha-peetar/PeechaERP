ALTER TABLE comm.pos_settings
    ADD COLUMN quick_access_position VARCHAR(10) NOT NULL DEFAULT 'LEFT',
    ADD COLUMN quick_access_orientation VARCHAR(10) NOT NULL DEFAULT 'HORIZONTAL';
