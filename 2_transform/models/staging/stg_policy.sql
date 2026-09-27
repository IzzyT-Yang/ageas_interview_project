with ranked as (
    select
        customer_id,
        policy_id,
        coverage_amount,
        policy_type,
        premium_amount,
        loaded_at,
        source_file,
        row_number() over (
            partition by policy_id
            order by loaded_at desc
        ) as rn
    from {{ source('raw', 'raw_policy') }}
),

parsed as (
    select
        customer_id,
        policy_id,
        coverage_amount,
        premium_amount,
        loaded_at,
        source_file,
        replace(replace(btrim(policy_type), 'None', 'null'), '''', '"')::json as policy_type_json
    from ranked
    where rn = 1
)

select
    customer_id,
    policy_id,
    case
        when coverage_amount is null or btrim(coverage_amount) = '' then null
        when coverage_amount ~ '^-?[0-9]+(\.[0-9]+)?$'
             and coverage_amount::numeric = -2147483649::numeric then null
        when coverage_amount ~ '^-?[0-9]+(\.[0-9]+)?$' then coverage_amount::numeric
        else null
    end as coverage_amount,
    case
        when premium_amount is null or btrim(premium_amount) = '' then null
        when premium_amount ~ '^-?[0-9]+(\.[0-9]+)?$' then premium_amount::numeric
        else null
    end as premium_amount,
    nullif(btrim(policy_type_json ->> 'brand'), '') as brand,
    nullif(btrim(policy_type_json ->> 'type'), '') as product_type,
    loaded_at,
    source_file
from parsed
