with ranked as (
    select
        policy_id,
        event_timestamp::timestamp as event_timestamp,
        btrim(event_type) as event_type,
        loaded_at,
        source_file,
        row_number() over (
            partition by policy_id, event_timestamp::timestamp
            order by loaded_at desc
        ) as rn
    from {{ source('raw', 'raw_event') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['policy_id', 'event_timestamp']) }} as event_sk,
    policy_id,
    event_timestamp,
    event_type,
    loaded_at,
    source_file
from ranked
where rn = 1
