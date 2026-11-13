-- Typed clicks. Enum values are mapped through the brand's schema contract; an unknown value maps to null.
select r.rid, r.path, r.click_id, r.session_id, r.offer_id, r.brand, r.partner_id,
       mk.canonical as market, dv.canonical as device, r.market as market_sent, r.device as device_sent,
       r.ts, r.ip, regexp_replace(r.ip, '\.[0-9]+$', '') as ip24, r.user_agent, r.asn_type,
       r.search_to_click_ms, r.loaded_at
from raw_clicks r
left join enum_map dv on dv.brand = r.brand and dv.field = 'device' and dv.value = lower(trim(r.device))
left join enum_map mk on mk.brand = r.brand and mk.field = 'market' and mk.value = lower(trim(r.market))
