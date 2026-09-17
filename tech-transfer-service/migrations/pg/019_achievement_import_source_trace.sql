-- 019: 正式成果可反向追溯到人工确认过的导入暂存项。
ALTER TABLE public.achievement
    ADD COLUMN IF NOT EXISTS source_import_item_id BIGINT DEFAULT NULL
        REFERENCES public.achievement_import_item(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_achievement_source_import_item
    ON public.achievement(source_import_item_id)
    WHERE source_import_item_id IS NOT NULL;
