-- Invalid-traffic rules. Each click gets the first rule it breaks, or null.
with net as (
    select ip24, date_trunc('hour', ts) as hour, count(*) as clicks
    from int_clicks_unique
    group by ip24, date_trunc('hour', ts)
)
select u.*,
       case
           when not ${bot_rules} then case when lower(u.user_agent) like '%bot%' then 'agent_says_bot' end
           when ${agent_marker_predicate} then 'automated_agent'
           when u.asn_type = 'datacenter' then 'datacenter_network'
           when u.search_to_click_ms < ${min_search_to_click_ms} then 'inhuman_speed'
           when n.clicks > ${max_clicks_per_ip24_hour} then 'network_rate'
       end as invalid_reason
from int_clicks_unique u
join net n on n.ip24 = u.ip24 and n.hour = date_trunc('hour', u.ts)
