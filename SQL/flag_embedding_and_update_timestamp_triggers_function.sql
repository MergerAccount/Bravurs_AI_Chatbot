
-- Timestamp auto-updater trigger

CREATE OR REPLACE FUNCTION update_content_timestamp()

RETURNS trigger AS $$

BEGIN

    NEW.last_updated_content := NOW();

RETURN NEW;

END;

$$ LANGUAGE plpgsql;



DROP TRIGGER IF EXISTS trigger_content_updated ON bravur_data;

CREATE TRIGGER trigger_content_updated

    BEFORE INSERT OR UPDATE OF content, title

                     ON bravur_data

                         FOR EACH ROW

                         EXECUTE FUNCTION update_content_timestamp();



-- Ensure your table exists with correct naming

-- If not, adjust the table name accordingly

ALTER TABLE "Bravur_information"

    ADD COLUMN IF NOT EXISTS needs_embedding BOOLEAN DEFAULT TRUE;



-- Optional safety: Initialize existing rows to TRUE if needed

UPDATE "Bravur_information"

SET needs_embedding = TRUE

WHERE needs_embedding IS NULL;



-- Drop old trigger if it exists to avoid duplicates

DROP TRIGGER IF EXISTS bravur_flag_embedding ON "Bravur_information";



-- Create trigger function to auto-flag on content changes

CREATE OR REPLACE FUNCTION flag_for_embedding()

RETURNS trigger AS $$

BEGIN

    -- If content is newly inserted or updated and changes

    IF NEW.content IS DISTINCT FROM COALESCE(OLD.content, '') THEN

        NEW.needs_embedding := TRUE;

END IF;

RETURN NEW;

END;

$$ LANGUAGE plpgsql;



-- Create the trigger that fires before insert or update of content

CREATE TRIGGER bravur_flag_embedding

    BEFORE INSERT OR UPDATE OF content ON "Bravur_information"

    FOR EACH ROW

    EXECUTE FUNCTION flag_for_embedding();



-- Optional: Check structure afterward

-- \d+ "Bravur_information"







CREATE OR REPLACE FUNCTION flag_for_embedding()

RETURNS trigger AS $$

BEGIN

    -- Always set needs_embedding to true if content is part of the update

    NEW.needs_embedding := TRUE;

RETURN NEW;

END;

$$ LANGUAGE plpgsql;


DROP TRIGGER IF EXISTS bravur_flag_embedding ON bravur_data;

CREATE TRIGGER bravur_flag_embedding

    BEFORE UPDATE OF content ON bravur_data

    FOR EACH ROW

    EXECUTE FUNCTION flag_for_embedding();


-- FUNCTION: public.update_content_timestamp()

-- DROP FUNCTION IF EXISTS public.update_content_timestamp();

CREATE OR REPLACE FUNCTION public.update_content_timestamp()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$
BEGIN
    NEW.last_updated_content := NOW();
RETURN NEW;
END;
$BODY$;

ALTER FUNCTION public.update_content_timestamp()
    OWNER TO postgres;
