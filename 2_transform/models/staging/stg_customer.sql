with ranked as (
    select
        customer_id,
        age,
        region,
        loaded_at,
        source_file,
        row_number() over (
            partition by customer_id
            order by
                loaded_at desc,
                case when source_file = 'customer_additional.csv' then 0 else 1 end
        ) as rn
    from {{ source('raw', 'raw_customer') }}
)

select
    customer_id,
    case
        when age is null or btrim(age) = '' then null
        when age ~ '^-?[0-9]+$' and age::integer < 0 then null
        when age ~ '^-?[0-9]+$' then age::integer
        else null
    end as age,
    nullif(btrim(region), '') as region,
    loaded_at,
    source_file
from ranked
where rn = 1
