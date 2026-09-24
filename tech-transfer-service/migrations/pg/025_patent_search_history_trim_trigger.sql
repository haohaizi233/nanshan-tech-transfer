-- 025: 专利检索历史按用户+模式只保留最近 10 条（数据库触发器兜底）

BEGIN;

CREATE OR REPLACE FUNCTION public.trim_patent_search_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM public.patent_search_history
    WHERE id IN (
        SELECT id
        FROM public.patent_search_history
        WHERE user_id = NEW.user_id
          AND search_mode = NEW.search_mode
        ORDER BY updated_at DESC, id DESC
        OFFSET 10
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_patent_search_history_trim ON public.patent_search_history;

CREATE TRIGGER trg_patent_search_history_trim
AFTER INSERT OR UPDATE OF updated_at ON public.patent_search_history
FOR EACH ROW
EXECUTE FUNCTION public.trim_patent_search_history();

-- 存量超 10 条的先收一遍
DELETE FROM public.patent_search_history
WHERE id IN (
    SELECT id
    FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY user_id, search_mode
                   ORDER BY updated_at DESC, id DESC
               ) AS rn
        FROM public.patent_search_history
    ) ranked
    WHERE ranked.rn > 10
);

COMMIT;
