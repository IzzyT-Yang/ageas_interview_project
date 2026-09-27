-- Reconciliation: total sale_count in the mart must equal purchase events
-- that successfully join to a policy (same join as the mart).

with mart_total as (
    select coalesce(sum(sale_count), 0) as n
    from {{ ref('mart_monthly_sales_by_brand_type') }}
),

upstream as (
    select count(*) as n
    from {{ ref('stg_event') }} e
    inner join {{ ref('stg_policy') }} p
        on e.policy_id = p.policy_id
    where e.event_type = 'purchase'
)

select
    mart_total.n as mart_sale_count,
    upstream.n as purchase_event_count
from mart_total
cross join upstream
where mart_total.n != upstream.n
