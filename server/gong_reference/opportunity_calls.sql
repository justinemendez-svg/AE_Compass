-- Copied from the GTM Ops Gong connector.
-- Returns lightweight Gong call metadata for selected Salesforce opportunities.
with opp_calls as (
    select ctx.object_id as crm_opportunity_id, ctx.conversation_key
    from cleansed.gong.gong_conversation_contexts_bcv ctx
    join cleansed.salesforce.salesforce_opportunity_scd2 opp
        on opp.id = ctx.object_id and opp.valid_to_timestamp = '9999-12-31' and opp.is_deleted = false
    join cleansed.salesforce.salesforce_account_scd2 acc
        on acc.id = opp.account_id and acc.valid_to_timestamp = '9999-12-31' and acc.is_deleted = false
    join cleansed.gong.gong_calls_bcv call on call.conversation_key = ctx.conversation_key
    where ctx.object_type = 'opportunity'
      and ctx.object_id is not null
      and ctx.object_id in ({{opportunity_ids}})
      and call.planned_start_datetime >= dateadd(day, -30, opp.close_date)
      and (opp.close_date is null or call.planned_start_datetime <= opp.close_date)
      and acc.record_type_id != '01280000000Hi8UAAS'
      and acc.name not like '%Skilljar Account%'
      and acc.name not like '%DO NOT WORK%'
    qualify row_number() over (partition by ctx.object_id, ctx.conversation_key order by ctx.real_run_time desc) = 1
),
call_speakers as (
    select oc.conversation_key, array_agg(object_construct(
        'speaker_id', s.speaker_id, 'name', s.name, 'email', s.email_address,
        'object_type', s.associated_object_type, 'object_id', s.associated_object_id, 'user_id', s.user_id
    )) as speakers
    from opp_calls oc
    join cleansed.gong.gong_conversation_participants_bcv s on s.conversation_key = oc.conversation_key
    group by oc.conversation_key
),
call_meta as (
    select conversation_key, title, planned_start_datetime, planned_end_datetime,
           call_spotlight_brief, call_spotlight_next_steps, call_spotlight_key_points
    from cleansed.gong.gong_calls_bcv
)
select oc.crm_opportunity_id, oc.conversation_key, cm.title, cm.planned_start_datetime,
       cm.planned_end_datetime, cm.call_spotlight_brief, cm.call_spotlight_next_steps,
       cm.call_spotlight_key_points, coalesce(cs.speakers, array_construct()) as speakers
from opp_calls oc
left join call_meta cm on cm.conversation_key = oc.conversation_key
left join call_speakers cs on cs.conversation_key = oc.conversation_key
order by oc.crm_opportunity_id, cm.planned_start_datetime desc;
