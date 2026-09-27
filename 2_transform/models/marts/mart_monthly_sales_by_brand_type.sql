with purchases as (
    select
        e.policy_id,
        e.event_timestamp,
        date_trunc('month', e.event_timestamp)::date as sales_month
    from {{ ref('stg_event') }} e
    where e.event_type = 'purchase'
),

enriched as (
    select
        p.sales_month,
        pol.brand,
        coalesce(pol.product_type, 'unknown') as product_type,
        pol.premium_amount
    from purchases p
    inner join {{ ref('stg_policy') }} pol
        on p.policy_id = pol.policy_id
)

select
    sales_month,
    brand,
    product_type,
    count(*)::bigint as sale_count,
    sum(premium_amount)::numeric(18, 2) as premium_amount_sum
from enriched
group by 1, 2, 3
