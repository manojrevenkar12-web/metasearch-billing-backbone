-- The billable fact: one row per billed click, price in the contract currency's minor unit (null: no rate).
select rid, click_id, brand, partner_id, market, device, ts, local_date,
       substr(cast(local_date as varchar), 1, 7) as month, currency, cpc_minor as price_minor
from int_clicks_priced
where billable
