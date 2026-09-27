with retention_events as (
    select
        e.policy_id,
        e.event_type,
        e.event_timestamp,
        date_trunc('month', e.event_timestamp)::date as retention_month
    from {{ ref('stg_event') }} e
    where e.event_type in ('renewal', 'cancellation')
),

latest_per_policy_month as (
    select
        policy_id,
        retention_month,
        event_type,
        row_number() over (
            partition by policy_id, retention_month
            order by event_timestamp desc
        ) as rn
    from retention_events
),

classified as (
    select
        l.retention_month,
        pol.brand,
        coalesce(pol.product_type, 'unknown') as product_type,
        l.event_type
    from latest_per_policy_month l
    inner join {{ ref('stg_policy') }} pol
        on l.policy_id = pol.policy_id
    where l.rn = 1
)

select
    retention_month,
    brand,
    product_type,
    count(*) filter (where event_type = 'renewal')::bigint as renewal_count,
    count(*) filter (where event_type = 'cancellation')::bigint as cancellation_count,
    (
        count(*) filter (where event_type = 'renewal')::numeric
        / nullif(
            count(*) filter (where event_type in ('renewal', 'cancellation')),
            0
        )
    )::numeric(18, 6) as retention_rate
from classified
group by 1, 2, 3
