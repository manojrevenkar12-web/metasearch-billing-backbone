-- materialize: view
-- The rate card as known at the run: for each valid-from date the latest recorded version, as date intervals.
with known as (
    select partner_id, market, device, valid_from, cpc_minor, recorded_at,
           row_number() over (partition by partner_id, market, device, valid_from order by recorded_at desc) as rk
    from rate_card
    where recorded_at <= ${as_of}
)
select partner_id, market, device, valid_from, cpc_minor, recorded_at,
       coalesce(lead(valid_from) over (partition by partner_id, market, device order by valid_from),
                date '9999-12-31') as valid_to
from known
where rk = 1
