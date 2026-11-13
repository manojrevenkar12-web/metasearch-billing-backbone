-- Invoice lines per partner, month, market and device.
select partner_id, month, currency, market, device,
       count(*) as clicks,
       coalesce(sum(price_minor), 0) as amount_minor,
       count(*) - count(price_minor) as unpriced
from fct_billable_clicks
group by partner_id, month, currency, market, device
