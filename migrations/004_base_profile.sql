CREATE TABLE base_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    profile_json TEXT,
    provenance_json TEXT,
    sources_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'stale' CHECK (status IN ('ready', 'stale')),
    model TEXT,
    merged_at TEXT,
    error TEXT
);
INSERT INTO base_profile (id) VALUES (1);

CREATE TRIGGER base_profile_after_insert AFTER INSERT ON profiles
BEGIN
    UPDATE base_profile SET status = 'stale', error = NULL WHERE id = 1;
END;
CREATE TRIGGER base_profile_after_update AFTER UPDATE ON profiles
WHEN OLD.profile_name IS NOT NEW.profile_name OR OLD.profile_json IS NOT NEW.profile_json
BEGIN
    UPDATE base_profile SET status = 'stale', error = NULL WHERE id = 1;
END;
CREATE TRIGGER base_profile_after_delete AFTER DELETE ON profiles
BEGIN
    UPDATE base_profile SET status = 'stale', error = NULL WHERE id = 1;
END;
