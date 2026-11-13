-- materialize: view
-- One row per click id: a redirect logged twice is one click.
select *
from (
    select s.*, row_number() over (partition by s.click_id order by s.ts, s.path, s.rid) as copy_no
    from stg_clicks s
    where s.market is not null and s.device is not null
) t
where copy_no = 1 or not ${dedupe_click_ids}
