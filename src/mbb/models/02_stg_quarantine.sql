-- Clicks whose values the brand's schema contract does not know. They are held, not billed, until it does.
select rid, path, click_id, brand, partner_id, market_sent, device_sent, ts
from stg_clicks
where market is null or device is null
