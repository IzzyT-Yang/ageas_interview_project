with claims as (
    select
        e.policy_id,
        date_trunc('month', e.event_timestamp)::date as claim_month
    from {{ ref('stg_event') }} e
    where e.event_type = 'claim'
),

enriched as (
    select
        c.claim_month,
        cust.region
    from claims c
    inner join {{ ref('stg_policy') }} pol
        on c.policy_id = pol.policy_id
    inner join {{ ref('stg_customer') }} cust
        on pol.customer_id = cust.customer_id
)

select
    claim_month,
    region,
    count(*)::bigint as claim_count
from enriched
group by 1, 2
