-- Legacy captures can contain the same source/external ID more than once.
-- Preserve all captures and use this pair as a lookup aid, not identity.
DROP INDEX IF EXISTS jobs_source_external_id;

CREATE INDEX jobs_source_external_id
ON jobs(source, external_job_id)
WHERE source IS NOT NULL AND external_job_id IS NOT NULL;
