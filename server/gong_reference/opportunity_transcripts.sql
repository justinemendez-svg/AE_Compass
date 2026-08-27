-- Copied from the GTM Ops Gong connector.
-- Full transcripts are reserved for an opportunity drill-down, not the overview.
with opp_calls as (
    select ctx.object_id as crm_opportunity_id, ctx.conversation_key
    from cleansed.gong.gong_conversation_contexts_bcv ctx
    join cleansed.salesforce.salesforce_opportunity_scd2 opp
        on opp.id = ctx.object_id and opp.valid_to_timestamp = '9999-12-31' and opp.is_deleted = false
    join cleansed.salesforce.salesforce_account_scd2 acc
        on acc.id = opp.account_id and acc.valid_to_timestamp = '9999-12-31' and acc.is_deleted = false
    join cleansed.gong.gong_calls_bcv call on call.conversation_key = ctx.conversation_key
    where ctx.object_type = 'opportunity'
      and ctx.object_id in ({{opportunity_ids}})
      and call.planned_start_datetime >= dateadd(day, -30, opp.close_date)
      and (opp.close_date is null or call.planned_start_datetime <= opp.close_date)
      and acc.record_type_id != '01280000000Hi8UAAS'
      and acc.name not like '%Skilljar Account%'
      and acc.name not like '%DO NOT WORK%'
    qualify row_number() over (partition by ctx.object_id, ctx.conversation_key order by ctx.real_run_time desc) = 1
)
select oc.crm_opportunity_id, oc.conversation_key, call.title, call.planned_start_datetime,
       call.planned_end_datetime, call.call_spotlight_brief, call.call_spotlight_next_steps,
       call.call_spotlight_key_points,
       listagg(transcript.transcript, '\n') within group (order by transcript.transcript) as transcript
from opp_calls oc
join cleansed.gong.gong_call_transcripts_bcv transcript on transcript.conversation_key = oc.conversation_key
join cleansed.gong.gong_calls_bcv call on call.conversation_key = oc.conversation_key
where transcript.transcript is not null
group by oc.crm_opportunity_id, oc.conversation_key, call.title, call.planned_start_datetime,
         call.planned_end_datetime, call.call_spotlight_brief, call.call_spotlight_next_steps,
         call.call_spotlight_key_points
order by oc.crm_opportunity_id, call.planned_start_datetime desc;
