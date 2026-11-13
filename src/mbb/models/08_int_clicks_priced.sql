-- materialize: view
-- Price each click. With amendments repriced: the contract as known now, joined as intervals.
-- Without: the rate that was known when the click was loaded, as a pipeline that prices at ingest would.
select b.*, v.cpc_minor
from int_clicks_billable b
left join int_rate_versions v
       on v.partner_id = b.partner_id and v.market = b.market and v.device = b.device
      and b.local_date >= v.valid_from and b.local_date < v.valid_to
where ${reprice_amendments}
union all
select b.*, c.cpc_minor
from int_clicks_billable b
left join (
    select b2.rid, r.cpc_minor,
           row_number() over (partition by b2.rid order by r.valid_from desc, r.recorded_at desc) as rk
    from int_clicks_billable b2
    join rate_card r
      on r.partner_id = b2.partner_id and r.market = b2.market and r.device = b2.device
     and r.valid_from <= b2.local_date and r.recorded_at <= b2.loaded_at
) c on c.rid = b.rid and c.rk = 1
where not ${reprice_amendments}
