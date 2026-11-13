-- Revenue per UTC day and partner in EUR cents, at the latest reference rate published for that day.
with daily as (
    select cast(ts at time zone 'UTC' as date) as day, partner_id, currency,
           coalesce(sum(price_minor), 0) as amount_minor
    from fct_billable_clicks
    group by cast(ts at time zone 'UTC' as date), partner_id, currency
),
calendar as (
    select d.*,
           case date_diff('day', date '2026-01-05', d.day) % 7
               when 5 then d.day - interval '1' day
               when 6 then d.day - interval '2' day
               else d.day
           end as business_day
    from daily d
),
pick as (
    select c.day, c.partner_id, c.currency, c.amount_minor, f.rate, f.day as rate_day,
           row_number() over (partition by c.day, c.partner_id order by f.day desc) as rk
    from calendar c
    left join fx_rates f
           on f.currency = c.currency and f.recorded_at <= ${as_of}
          and ((${fx_as_published} and f.day <= c.day and f.day > c.day - interval '14' day)
               or (not ${fx_as_published} and f.day = c.business_day))
)
select day, partner_id, currency, amount_minor, rate, rate_day,
       case when currency = 'EUR' then amount_minor
            when rate is null then null
            else cast(round(amount_minor / rate) as bigint) end as revenue_eur_minor
from pick
where rk = 1
