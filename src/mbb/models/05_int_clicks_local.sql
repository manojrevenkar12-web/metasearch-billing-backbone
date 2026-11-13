-- materialize: view
-- The partner's contract: billing time zone, currency, repeat-click window; the click's date in that time zone.
select s.*, p.currency, p.billing_tz, p.repeat_window_s,
       lag(s.ts) over (partition by s.partner_id, s.session_id, s.offer_id order by s.ts, s.rid) as prev_click_ts,
       case
           when ${partner_local_time} then cast(s.ts at time zone p.billing_tz as date)
           else cast((s.ts at time zone 'UTC') + p.std_offset_h * interval '1' hour as date)
       end as local_date
from int_clicks_scored s
join partners p on p.partner_id = s.partner_id
