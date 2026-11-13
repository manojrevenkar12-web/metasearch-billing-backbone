-- materialize: view
-- Billable: valid traffic, and not a repeat of the same offer by the same session inside the partner's window.
select l.*,
       l.invalid_reason is null
       and not (${repeat_click_window} and l.prev_click_ts is not null
                and date_diff('millisecond', l.prev_click_ts, l.ts) < l.repeat_window_s * 1000) as billable
from int_clicks_local l
