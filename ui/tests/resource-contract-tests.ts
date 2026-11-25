// Real OPFS/WASI execution of the shared native resource contract helper.
const results:{name:string;seconds:number;error?:string}[]=[];
Object.assign(window,{testResults:results,testDone:false});
const assert=(condition:unknown,message:string)=>{if(!condition)throw new Error(message);};
function request(worker:Worker,message:unknown,transfer:Transferable[],field:string):Promise<any>{
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Resource contract worker timed out')),240000);
    const fail=(error:Error)=>{clearTimeout(timer);reject(error);};
    worker.onerror=event=>fail(new Error(event.message));
    worker.onmessage=({data})=>{
      if(data.error)fail(new Error(data.error));
      else if(data[field]!==undefined){clearTimeout(timer);resolve(data);}
    };
    worker.postMessage(message,transfer);
  });
}
async function main(){
  const started=performance.now();
  const candidate=new URLSearchParams(location.search).has('shuffle-partition');
  const testName=candidate?'retained-parent retry, encoded caps and publication in WASI/OPFS':'input/group admission and unlink-error publication rejection in WASI/OPFS';
  let storage:Worker|undefined,engine:Worker|undefined,storageReady=false;
  let exportTestsRoot:FileSystemDirectoryHandle|undefined,exportDirectoryCreated=false;
  let contractSucceeded=false;
  const jobId='resource-contracts-'+crypto.randomUUID();
  try{
    await navigator.locks.request('chopper-'+jobId,async()=>{
      let contractFailure:unknown;
      try{
        const shared=new SharedArrayBuffer(16+1024*1024),channel=new MessageChannel();
        const available=128*1024*1024;
        storage=new Worker('/storage-worker.js',{type:'module'});
        await request(storage,{type:'init',jobId,available,shared,port:channel.port1},[channel.port1],'ready');
        storageReady=true;
        let exportDirectory:FileSystemDirectoryHandle|undefined;
        if(candidate){
          exportTestsRoot=await(await navigator.storage.getDirectory()).getDirectoryHandle('chopper-resource-export-tests',{create:true});
          exportDirectory=await exportTestsRoot.getDirectoryHandle(jobId,{create:true});
          exportDirectoryCreated=true;
        }
        engine=new Worker('/resource-contract-worker.js'+(candidate?'?shuffle-partition=1':''),{type:'module'});
        const {result,diagnostics,browserExport}=await request(engine,{available,shared,port:channel.port2,exportDirectory},[channel.port2],'result');
        assert(result.auto_fusion?.pre_emission_retry&&result.auto_fusion?.cancellation_cleanup,'Active Auto fusion resource contract failed');
        assert(result.schema_version===1&&result.contract==='input-adapter-resource-contracts-v1','Wrong resource contract report');
        const decode=result.inspection_job_decode, inspectionAdapter=result.inspection_job_adapter;
        assert(decode?.construction_bytes===41209&&decode.retained_bytes===8224&&decode.malformed_error_parity&&
          decode.cases.map((item:any)=>item.available_bytes).join(',')==='8219,41209,41208,41209','WASI Job decode edges failed');
        assert(inspectionAdapter?.calls.length===4&&inspectionAdapter.formula_pause_job_bytes===8200&&
          inspectionAdapter.virtual.map((item:any)=>item.bytes).join(',')==='1048575,1048577','WASI Job inspection adapter contract failed');
        if(new URLSearchParams(location.search).has('spill-blocks')){
          assert(result.spill_blocks?.contract==='spill-block-resource-contracts-v1','Missing actual spill-block contracts');
          assert(JSON.stringify(result.spill_blocks.cases)===JSON.stringify(['roundtrip_chunks_widths','footer_quota','wide_reader_lifetime','local_encoder_fallback_retry','malformed_truncated_utf8_terminal','shared_encoder_fallback_retry','reader_live_cancellation']),'Missing spill-block decode/admission/ownership cases');
        }
        assert(result.fixture_directory_removed===true,'Rust fixtures were not removed');
        const publicationPaths=result.publication_paths;
        assert(publicationPaths?.contract==='publication-path-capacity-contract-v1','Missing publication path contract');
        const paths=publicationPaths.paths;
        assert(paths.cases.length===5&&paths.cases.every((item:any)=>item.retained_capacity_bytes>0)&&paths.local_shared_edge_checks===6&&paths.competitor_retry&&paths.invalid_components_rejected===8&&paths.independent_paths===2&&paths.final_reserved_bytes===0,'Publication path admission/lifetimes failed');
        assert(publicationPaths.filesystem.file_create_metadata_and_drop&&publicationPaths.filesystem.creation_failure_retains_owner&&publicationPaths.filesystem.fixture_directory_removed&&publicationPaths.filesystem.final_reserved_bytes===0,'Publication path filesystem ownership failed');
        assert(publicationPaths.publication.cases.map((item:any)=>item.compression).join(',')==='none,gzip,zip'&&publicationPaths.publication.cases.every((item:any)=>item.typed_path_denial&&item.staging_removed&&item.cancelled_no_publication&&item.retry_csv_equal&&item.final_reserved_bytes===0)&&publicationPaths.publication.fixture_directory_removed&&publicationPaths.publication.final_reserved_bytes===0,'Publication path denial/retry/cleanup failed');
        const jobManifest=result.job_manifest;
        const columnDecoder=result.column_deserialization;
        const direct=result.direct_run;
        assert(direct?.contract==='direct-run-resource-contract-v1','Direct Run resource contract missing');
        for(const field of ['shared_denial_retry','local_denial_retry','final_clone_release','failure_cleanup','fixture_directory_removed'])assert(direct[field]===true,'Direct Run resource contract failed: '+field);
        assert(columnDecoder.usize_bits===32&&columnDecoder.reference_json_cases===36&&columnDecoder.legacy_values_and_errors_preserved&&columnDecoder.owned_control_string_moved_without_copy&&columnDecoder.numeric_string_remains_name,'Column scalar decoding or legacy errors changed');
        const diagnosticOwner=result.analysis_diagnostics;
        assert(diagnosticOwner?.local_shared_edge_checks===6&&diagnosticOwner.construction_peak_bytes>=diagnosticOwner.retained_bytes&&diagnosticOwner.retained_bytes>0&&diagnosticOwner.shared_clone_and_last_drop&&diagnosticOwner.caller_json_equal&&diagnosticOwner.competing_owner_retry,'Diagnostic admission/lifetime failed');
        const diagnosticConstruction=diagnosticOwner.construction;
        assert(diagnosticConstruction.controller_edge_checks===6&&diagnosticConstruction.denied_after_tree_construction_cleanup&&diagnosticConstruction.source_growth_repreflight_and_retry&&diagnosticConstruction.source_growth_denial_cleanup&&diagnosticConstruction.unsupported_display_rejected_before_formatting&&diagnosticConstruction.absent_default_no_allocation,'Diagnostic construction preflight failed');
        assert(diagnosticOwner.source_parity.all_legacy_fields_equal&&(!candidate||diagnosticOwner.source_parity.bounded_audit_records_preserved)&&diagnosticOwner.source_parity.context_and_original_audit_drop_before_snapshot&&diagnosticOwner.source_parity.self_inclusive_workspace_and_process_counts,'Borrowed diagnostic source or retained audit changed');
        const diagnosticLifetime=diagnosticOwner.public_lifetimes;
        assert(diagnosticLifetime.analysis_and_independent_payload_clones&&diagnosticLifetime.prepared_drop_and_execute&&diagnosticLifetime.serialization_failures&&diagnosticLifetime.exact_csv_publication&&diagnosticLifetime.ready_snapshot_cancellation_cleanup&&diagnosticLifetime.last_diagnostic_after_context_release&&diagnosticLifetime.final_reserved_bytes===0,'Public diagnostic ownership failed');
        const warningOwner=result.analysis_warnings;
        assert(warningOwner?.local_shared_edges===6&&warningOwner.required_bytes>0&&warningOwner.shared_clone_and_last_drop&&warningOwner.competing_owner_retry&&warningOwner.caller_json_equal&&warningOwner.empty_no_allocation&&warningOwner.eighth_allowed_ninth_rejected&&warningOwner.partial_copy_denial_preserves_data_and_retry,'Warning admission/lifetime failed');
        assert(warningOwner.conditions.all_eight_conditions_in_original_order&&warningOwner.conditions.max_u64_message_exact&&warningOwner.conditions.inactive_conditions_no_allocation,'Warning contents/order changed');
        const notes=warningOwner.public_lifetimes;
        assert(notes.analysis_and_independent_payload_clones&&notes.prepared_drop_and_execute&&notes.serialization_failures&&notes.exact_csv_publication&&notes.ready_snapshot_cancellation_cleanup&&notes.last_warning_then_timing_release&&notes.final_reserved_bytes===0,'Public warning/timing lifetime failed');
        const timingOwner=result.analysis_timings;
        assert(timingOwner?.local_shared_edges===6&&timingOwner.required_bytes>0&&timingOwner.node_allowance_bytes>0&&timingOwner.shared_clone_and_last_drop&&timingOwner.competing_owner_retry&&timingOwner.caller_json_equal&&timingOwner.empty_no_allocation&&timingOwner.stack_observations_and_overwrite&&timingOwner.sixth_entry_rejected&&timingOwner.partial_key_copy_cleanup,'Timing admission/lifetime failed');
        const automatic=result.automatic_memory;
        assert(automatic?.live_grants&&automatic.numeric_preserved&&automatic.final_reserved_bytes===0,'Automatic memory ledger contract failed');
        const manual=result.manual_memory;
        assert(manual?.explicit_memory_mb===512&&manual.shared_limit_bytes===16*1024*1024&&manual.peak_reserved_bytes<=manual.shared_limit_bytes&&manual.rows===60000&&manual.seeded_csv_parity&&manual.exact_field_and_id_conservation&&manual.final_reserved_bytes===0,'Larger manual memory must retain spill headroom and seeded CSV parity');
        const analysisText=result.analysis_text;
        assert(analysisText?.local_shared_edges===6&&analysisText.required_bytes>0&&analysisText.json_text_unchanged&&analysisText.shared_clone_and_last_drop&&analysisText.competing_owner_retry&&analysisText.empty_no_allocation,'Analysis text admission/lifetime failed');
        assert(analysisText.public_lifetimes.denial_before_csv_read&&analysisText.public_lifetimes.all_text_values_and_clone_identity&&analysisText.public_lifetimes.malformed_and_populated_scan_cancellation_cleanup&&analysisText.public_lifetimes.prepared_drop_and_execute&&analysisText.public_lifetimes.serialization_failure&&analysisText.public_lifetimes.last_analysis_clone_release,'Public Analysis text lifetime failed');
        const stageStats=result.stage_stats;
        assert(stageStats?.local_shared_edges===6&&stageStats.required_bytes>0&&stageStats.max_64_stages&&stageStats.logical_limit_no_growth&&stageStats.shared_clone_and_last_drop&&stageStats.shared_mutation_rejected_then_unique_retry&&stageStats.competing_owner_retry&&stageStats.zero_operations_no_allocation&&stageStats.caller_json_unchanged,'Stage statistics admission/lifetime failed');
        assert(stageStats.public_lifetimes.denial_before_csv_read&&stageStats.public_lifetimes.malformed_and_populated_scan_cancellation_cleanup&&stageStats.public_lifetimes.prepared_drop_and_execute&&stageStats.public_lifetimes.serialization_failure&&stageStats.public_lifetimes.exact_logical_stage_counts&&stageStats.public_lifetimes.last_analysis_clone_release,'Public stage statistics lifetime failed');
        const analysisSummaries=result.column_summaries;
        assert(analysisSummaries.contract==='column-summary-admission-v1'&&analysisSummaries.retained_fixture_bytes>0&&analysisSummaries.node_allowance_per_key>0&&analysisSummaries.local_shared_edges===6&&analysisSummaries.canonical_legacy_equal&&analysisSummaries.clone_shares_trees_and_grant&&analysisSummaries.caller_deserialization_equal&&analysisSummaries.competing_owner_release_retry&&analysisSummaries.entry_denial_preserves_tree_and_display_budget&&analysisSummaries.final_reserved_bytes===0,'Column summary admission failed');
        assert(analysisSummaries.parity.legacy_cases===3&&analysisSummaries.parity.lowest_64_order_and_duplicates&&analysisSummaries.parity.hundred_value_and_display_byte_limits&&analysisSummaries.parity.sticky_truncation&&analysisSummaries.parity.late_invalid_columns_equal&&analysisSummaries.parity.empty_and_unselected_no_allocation,'Column summary selection changed');
        assert(analysisSummaries.public_lifetimes.analysis_clone_shares_summaries&&analysisSummaries.public_lifetimes.serialization_failure_retains_owner&&analysisSummaries.public_lifetimes.prepared_drop_and_execute_lifetimes&&analysisSummaries.public_lifetimes.publication_rows_and_fields&&analysisSummaries.public_lifetimes.last_clone_release&&analysisSummaries.public_lifetimes.malformed_and_populated_scan_cancellation_cleanup&&analysisSummaries.public_lifetimes.fixture_directory_removed&&analysisSummaries.public_lifetimes.final_reserved_bytes===0,'Column summary lifecycle failed');
        const analysisHeader=result.analysis_header;
        assert(analysisHeader.contract==='analysis-header-shared-owner-v1'&&analysisHeader.retained_fixture_bytes>0&&analysisHeader.spare_vector_and_string_capacity&&analysisHeader.local_shared_edges===6&&analysisHeader.clone_shares_fields_and_grant&&analysisHeader.canonical_serialization_equal&&analysisHeader.caller_deserialization_equal&&analysisHeader.competing_owner_release_retry&&analysisHeader.final_reserved_bytes===0,'Analysis header ownership failed');
        assert(analysisHeader.public_lifetimes.analysis_clone_shares_header&&analysisHeader.public_lifetimes.serialization_failure_retains_owner&&analysisHeader.public_lifetimes.prepared_drop_retains_header&&analysisHeader.public_lifetimes.execution_retains_header&&analysisHeader.public_lifetimes.exact_csv_parity&&analysisHeader.public_lifetimes.last_clone_release&&analysisHeader.public_lifetimes.empty_headerless_header_only_presence&&analysisHeader.public_lifetimes.duplicate_empty_multiline_unicode_header_parity&&analysisHeader.public_lifetimes.malformed_header_cleanup&&analysisHeader.public_lifetimes.fixture_directory_removed&&analysisHeader.public_lifetimes.final_reserved_bytes===0,'Analysis header lifetime failed');
        const preview=result.analysis_preview;
        assert(preview.contract==='analysis-preview-owner-v1'&&preview.retained_fixture_bytes>0&&preview.local_shared_edges===6&&preview.clone_shares_rows_and_grant&&preview.competing_owner_release_retry&&preview.empty_field_descriptors_admitted_before_copy&&preview.partial_copy_denial_preserves_builder&&preview.selection_limits_preserved&&preview.caller_deserialization_equal&&preview.empty_preview_no_allocation&&preview.final_reserved_bytes===0,'Analysis preview ownership failed');
        assert(preview.public_preparation.analysis_clone_shares_preview&&preview.public_preparation.serialization_failure_retains_owner&&preview.public_preparation.execute_csv_parity&&preview.public_preparation.retained_after_execute_and_sibling_drop&&preview.public_preparation.last_clone_release&&preview.public_preparation.malformed_and_populated_scan_cancellation_cleanup&&preview.public_preparation.fixture_directory_removed&&preview.public_preparation.final_reserved_bytes===0,'Public Analysis preview lifetime failed');
        const preparedJob=result.prepared_job;
        assert(preparedJob.contract==='prepared-job-capacity-admission-v1'&&preparedJob.retained_bytes>0&&preparedJob.local_shared_edges===6&&preparedJob.spare_nested_capacities_included&&preparedJob.canonical_serialization_equal&&preparedJob.caller_clone_independent&&preparedJob.competing_owner_release_retry&&preparedJob.generated_seed_bytes===64&&preparedJob.final_reserved_bytes===0,'Prepared configuration ownership failed');
        assert(preparedJob.public_preparation.retained_capacity_bytes>=1024*1024&&preparedJob.public_preparation.denial_before_input&&preparedJob.public_preparation.prepared_serialization_equal&&preparedJob.public_preparation.serialization_failure_retains_owner&&preparedJob.public_preparation.execution_csv_parity&&preparedJob.public_preparation.final_reserved_bytes===0,'Public preparation configuration ownership failed');
        assert(jobManifest?.contract==='job-manifest-tree-admission-contract-v1','Missing job manifest tree admission contract');
        assert(jobManifest.trees.cases.length===6&&jobManifest.trees.cases.every((item:any)=>item.allowance_bytes>=item.retained_bytes&&item.retained_bytes>0&&/^[a-f0-9]{64}$/.test(item.manifest_blake3))&&jobManifest.trees.local_shared_edge_checks===6&&jobManifest.trees.competitor_retry&&jobManifest.trees.independent_trees===2&&jobManifest.trees.serialization_failure_retains_owner&&jobManifest.trees.final_reserved_bytes===0,'Manifest tree schema/admission/lifetimes failed');
        assert(jobManifest.failures.denial_runs_only_preflight&&jobManifest.failures.partial_construction_failure_cleanup&&jobManifest.failures.unsupported_display_rejected&&jobManifest.failures.preflight_overflow_rejected&&jobManifest.failures.unsupported_data_enum_rejected&&jobManifest.failures.non_string_keys_rejected&&jobManifest.failures.final_reserved_bytes===0,'Manifest construction failure controls missing');
        assert(jobManifest.publication.construction_shared_denial&&jobManifest.publication.denial_staging_cleanup&&jobManifest.publication.cancelled_no_publication&&jobManifest.publication.fresh_retry_published&&jobManifest.publication.canonical_job_record_bytes_equal&&jobManifest.publication.fixture_directory_removed&&jobManifest.publication.final_reserved_bytes===0,'Manifest publication denial/retry/parity/cleanup failed');
        const plannedMetadata=result.planned_metadata;
        if(result.nested_balanced){
          const nested=result.nested_balanced;
          assert(nested.contract==='nested-balanced-lineage-admission-v1'&&nested.owners.local_shared_edges===6&&nested.owners.construction_peak_bytes>nested.owners.retained_growth_bytes&&nested.owners.retained_growth_bytes>0&&nested.owners.replacement_overlap_admitted&&nested.owners.typed_competitor_denial_and_retry&&nested.owners.invalid_depths===3&&nested.owners.final_reserved_bytes===0,'Nested balanced traversal admission failed');
          assert(nested.outcomes.map((item:any)=>item.mode).join(',')==='success,row_error,end_error,cancelled,last_row_cancelled'&&nested.outcomes.every((item:any)=>item.baseline_restored)&&nested.shared_ranges_and_emitted_rows_match_serial&&nested.stage_statistics_equal&&nested.fixture_directory_removed&&nested.final_reserved_bytes===0,'Nested balanced lineage parity/cancellation/cleanup failed');
        }
        const gzip=result.gzip_codec;
        const zipCodec=result.zip_codec;
        assert(zipCodec.contract==='zip-reader-codec-admission-v1'&&zipCodec.reader_allowance_bytes>8192&&zipCodec.cases.length===6&&zipCodec.cases.every((item:any)=>item.local_shared_edges===6&&item.competitor_release_retry&&item.partial_consumer_failure_cleanup&&item.final_reserved_bytes===0)&&zipCodec.malformed_and_selection_cleanup.length===7&&zipCodec.public_profile_cancellation_cleanup&&zipCodec.final_reserved_bytes===0,'ZIP reader codec admission/lifetimes failed');
        const deflate=result.output_deflate_codec;
        assert(deflate.contract==='output-deflate-codec-admission-v1'&&deflate.capacity_bytes>32768&&deflate.local_shared_edges===12&&deflate.admission_before_construction&&deflate.concurrent_owner_release_retry&&deflate.cases.length===24&&deflate.cases.every((item:any)=>item.final_reserved_bytes===0)&&deflate.cases.filter((item:any)=>item.exact_bytes_checked).length===12&&deflate.final_reserved_bytes===0,'Output deflate codec admission/finalization failed');
        assert(gzip.contract==='gzip-codec-admission-v1'&&gzip.codec_capacity_bytes>gzip.header_allowance_bytes&&gzip.local_shared_edges===6&&gzip.concatenated_maximum_headers_with_crc&&gzip.admission_before_header_read&&gzip.eof_owner_retained&&gzip.malformed_stream_cleanup.length===5&&gzip.consumer_failure_checks===2&&gzip.final_reserved_bytes===0,'Gzip codec admission/lifetimes failed');
        const construction=result.temporary_construction;
        assert(construction?.contract==='temporary-path-construction-admission-v1'&&construction.local_shared_edge_checks===6&&construction.admission_before_filesystem&&construction.competitor_release_retry&&construction.collision_preserves_existing_file&&construction.collision_attempt_limit===128&&construction.random_and_os_failure_cleanup&&construction.invalid_inputs_rejected&&construction.production_reopen_and_cleanup&&construction.join_parity_cases>=4&&construction.fixture_directory_removed&&construction.final_reserved_bytes===0,'Temporary construction admission/collision/cleanup failed');
        const reopen=construction.reopen;
        assert(reopen.independent_offsets&&reopen.no_error_path_copy_or_grant&&reopen.final_reserved_bytes===0,'Temporary reopen identity/offset/error checks failed');
        const boundary=result.partition_boundary;
        assert(boundary?.contract==='partition-boundary-key-admission-v1'&&boundary.local_shared_edge_checks===6&&boundary.empty_tuple_initialized_without_allocation&&boundary.replacement_overlap_bytes>0&&boundary.denial_retains_old_key_and_sibling&&boundary.retained_capacity_after_shrink&&boundary.competitor_release_retry&&boundary.final_reserved_bytes===0,'Partition boundary key admission/lifetime failed');
        const childMetadata=result.child_metadata;
        assert(childMetadata?.contract==='child-lineage-admission-v1'&&childMetadata.cases.length===3&&childMetadata.cases.every((item:any)=>item.construction_bytes>0&&item.local_shared_edge_checks===6&&item.canonical_bytes_and_seeded_domain_preserved&&item.competitor_retry&&item.final_reserved_bytes===0)&&childMetadata.invalid_column_and_cancellation_before_allocation&&childMetadata.fixture_directory_removed,'Child lineage admission/domain parity failed');
        assert(childMetadata.execution.cases.map((item:any)=>item.operation.type).join(',')==='balanced,interleaved,partition,assign,assign_probabilistic'&&childMetadata.execution.cases.every((item:any)=>item.row_and_end_failure_cleanup&&item.first_and_last_row_cancellation_cleanup&&item.retry_exact_order)&&childMetadata.execution.final_reserved_bytes===0,'Child lineage execution cleanup failed');
        if(childMetadata.experimental){
          const cases=childMetadata.experimental.cases;
          assert(cases.length>0&&cases.every((item:any)=>item.row_and_catalog_failure_cleanup&&item.first_and_last_row_cancellation_cleanup&&item.exact_retry&&(item.original_stage_parity||item.scenario.startsWith('Ranges('))&&item.complete_group_rows.reduce((sum:number,count:number)=>sum+count,0)===8&&(!item.scenario.startsWith('Ranges(')||item.complete_group_rows.join(',')==='3,0,5'))&&childMetadata.experimental.unprocessed_root_verified&&childMetadata.experimental.weighted_allocations.join(',')==='40,0,60'&&childMetadata.experimental.final_reserved_bytes===0,'Experimental child lineage parity/cleanup failed');
        }
        if(childMetadata.growth){
          const growth=childMetadata.growth;
          assert(growth.local_shared_edge_checks===6&&growth.growth_overlap&&growth.construction_peak_bytes>growth.retained_bytes&&growth.denied_tree_unchanged&&growth.truncate_and_regrowth&&growth.independent_leaf_survives_source_mutation_and_drop&&growth.final_reserved_bytes===0,'Mutable lineage growth/leaf ownership failed');
        }
        const shuffleMetadata=result.shuffle_metadata;
        assert(shuffleMetadata?.contract==='shuffle-lineage-admission-contract-v1','Missing shuffle lineage admission contract');
        assert(shuffleMetadata.owners.local_shared_edge_checks===6&&shuffleMetadata.owners.denial_precedes_sink_begin&&shuffleMetadata.owners.source_allowance_bytes>=shuffleMetadata.owners.retained_bytes&&shuffleMetadata.owners.retained_bytes>0&&shuffleMetadata.owners.independent_clones===2&&shuffleMetadata.owners.source_drop_retains_clones&&shuffleMetadata.owners.final_reserved_bytes===0,'Shuffle lineage admission or owner lifetime failed');
        assert(shuffleMetadata.execution.cases.map((item:any)=>item.strategy).join(',')==='uniform,fisher_yates'&&shuffleMetadata.execution.cases.every((item:any)=>item.row_and_end_failure_cleanup&&item.cancellation_cleanup&&item.typed_shared_denial_before_begin&&item.release_retry_exact_order&&item.field_and_id_conservation&&item.lineage_and_exactness_preserved&&item.baseline_restored)&&shuffleMetadata.execution.fixture_directory_removed&&shuffleMetadata.execution.final_reserved_bytes===0,'Shuffle lineage executor denial/retry/cleanup failed');
        if(shuffleMetadata.flexible_execution){
          const flexible=shuffleMetadata.flexible_execution;
          assert(flexible.cases.map((item:any)=>item.strategy).join(',')==='uniform,fisher_yates,auto'&&flexible.cases.every((item:any)=>item.row_and_end_failure_cleanup&&item.cancellation_cleanup&&item.typed_shared_denial_before_begin&&item.release_retry_exact_order&&item.field_and_id_conservation&&item.lineage_and_exactness_preserved&&item.baseline_restored)&&flexible.fixture_directory_removed&&flexible.final_reserved_bytes===0,'Flexible shuffle lineage denial/retry/cleanup failed');
        }
        assert(plannedMetadata?.contract==='planned-lineage-metadata-resource-contract-v1','Missing planned-lineage clone ownership contract');
        assert(plannedMetadata.owners.source_allowance_bytes>=plannedMetadata.owners.clone_retained_bytes&&plannedMetadata.owners.clone_retained_bytes>0&&plannedMetadata.owners.local_shared_edge_checks===6&&plannedMetadata.owners.denied_builder_not_called&&plannedMetadata.owners.competitor_retry&&plannedMetadata.owners.independent_clones===2&&plannedMetadata.owners.serialization_failure_retains_owner&&plannedMetadata.owners.final_reserved_bytes===0,'Planned lineage admission/lifetime checks failed');
        assert(plannedMetadata.writer.outcomes.map((item:any)=>item.mode).join(',')==='completed,cancelled,catalog_error,denied_retry,empty_allocation'&&plannedMetadata.writer.outcomes.every((item:any)=>item.idle_directory_baseline_restored),'Missing output writer lineage failure/cleanup checks');
        assert(plannedMetadata.writer.materialized_dataset_csv_and_catalog_parity&&plannedMetadata.writer.fixture_directory_removed&&plannedMetadata.writer.final_reserved_bytes===0,'Materialized output planning parity/cleanup failed');
        const publicationMetadata=result.publication_metadata;
        assert(publicationMetadata?.contract==='publication-metadata-resource-contract-v1','Missing publication metadata admission contract');
        assert(publicationMetadata.names.construction_bytes===246&&publicationMetadata.names.cases.length===3&&publicationMetadata.names.local_shared_edge_checks===6&&publicationMetadata.names.competitor_retry&&publicationMetadata.names.final_reserved_bytes===0,'Name construction admission/retention failed');
        assert(publicationMetadata.batches.task_slot_bytes>0&&publicationMetadata.batches.two_slot_bytes===2*publicationMetadata.batches.task_slot_bytes&&publicationMetadata.batches.local_shared_edge_checks===6&&publicationMetadata.batches.concurrent_batches===2&&publicationMetadata.batches.competitor_retry&&publicationMetadata.batches.final_reserved_bytes===0,'Batch descriptor admission/retention failed');
        assert(publicationMetadata.tasks.fixture_directory_removed&&publicationMetadata.tasks.final_reserved_bytes===0,'Publication metadata fixture/owners leaked');
        assert(publicationMetadata.tasks.outcomes.map((item:any)=>item.mode).join(',')==='success,consumer_error,worker_error,cancelled'&&publicationMetadata.tasks.outcomes.every((item:any)=>item.baseline_restored),'Publication result/task failure coverage missing');
        assert(Array.isArray(result.cases)&&result.cases.length===3,'Missing input-adapter cases');
        assert(JSON.stringify(result.cases.map((c:any)=>c.codec).sort())===JSON.stringify(['gzip','plain','zip']),'Wrong codec coverage');
        for(const item of result.cases){
          assert(item.edge_checks===3&&item.final_reserved_bytes===0,'Capacity edges or final ownership failed: '+item.codec);
          assert(item.consumer_error_cleanup===true,'Consumer error leaked: '+item.codec);
          if(item.codec!=='plain')assert(item.typed_shared_denials>0&&item.release_retries>0,'Missing typed denial/retry: '+item.codec);
        }
        const zip=result.zip_metadata;
        assert(zip?.contract==='zip-metadata-admission-resource-contract-v1'&&zip.fixture_directory_removed===true,'Missing ZIP metadata ownership contract');
        assert(zip.source_buffer_bytes===8192&&zip.cases.length===12&&zip.terminal_callback_denials===90&&zip.crc_error_cleanup&&zip.public_profile_cancellation_cleanup,'ZIP parser denial, CRC or cancellation coverage missing');
        assert(zip.cases.map((item:any)=>item.name).sort().join(',')===['basic','many','fallback','failed_large_candidate','underreported','utf8','cp437','timestamps','ntfs','malformed_extra_scratch','zip64','archive_comment'].sort().join(','),'Wrong ZIP metadata shape coverage');
        for(const item of zip.cases){
          assert(item.required_peak_bytes>=item.retained_at_eof_bytes&&item.retained_at_eof_bytes>8192,'ZIP metadata charge released before EOF: '+item.name);
          assert(item.shared_edges===3&&item.typed_local_denials===1&&item.typed_shared_denials===2&&item.release_retries===1&&item.consumer_error_cleanup&&item.final_reserved_bytes===0,'ZIP metadata denial/retry owner failed: '+item.name);
        }
        const inspection=result.inspection_result;
        assert(inspection?.contract==='inspection-result-owner-v1'&&inspection.denial_precedes_builder&&inspection.cases.length===3,'Missing returned inspection owner contract');
        for(const item of inspection.cases)assert(item.peak_bytes>=item.retained_result_bytes&&item.retained_result_bytes>0&&item.shared_edges===3&&item.typed_shared_denials===2&&item.typed_local_denials===1&&item.fresh_release_retries===1&&item.serialization_error_retains_owner&&item.concurrent_final_owner&&item.final_reserved_bytes===0,'Returned inspection owner failed: '+item.name);
        const columns=result.inspection_columns;
        assert(columns?.contract==='inspection-columns-resource-contracts-v1'&&columns.source_buffer_bytes===65536,'Missing column-inspection resource contract');
        assert(columns.first_record_peak_bytes>=columns.first_record_retained_bytes&&columns.first_record_retained_bytes>65536&&columns.eof_retained_bytes>=65536,'Column parser/source capacity was released early');
        assert(columns.typed_local_denials===2&&columns.typed_shared_denials===2&&columns.fresh_owner_release_retries===2&&columns.invalid_input_cleanup_cases===2&&columns.final_reserved_bytes===0,'Column-inspection admission or cleanup failed');
        for(const field of ['terminal_after_error','eof_owner_retained','read_error_cleanup','json_parity'])assert(columns[field]===true,'Column-inspection contract failed: '+field);
        const sniff=result.inspection_sniff;
        assert(sniff?.contract==='inspection-sniff-resource-contracts-v1'&&sniff.sample_limit_bytes===65536,'Missing sniff resource contract');
        assert(Array.isArray(sniff.capacity_phases)&&JSON.stringify(sniff.capacity_phases.map((phase:any)=>phase.phase))===JSON.stringify(['raw','decoded','candidate'])&&sniff.capacity_phases.every((phase:any)=>phase.peak_bytes>0),'Missing sniff capacity phases');
        assert(sniff.typed_local_denials===3&&sniff.typed_shared_denials===4&&sniff.fresh_owner_release_retries===4&&sniff.bom_boundary_cases===12&&sniff.strict_decode_error_cleanup_cases===5&&sniff.final_reserved_bytes===0,'Sniff admission/edge cleanup failed');
        for(const field of ['eof_truncate_owner_retained','raw_decoded_overlap_charged','typed_candidate_denial_propagates','ordinary_syntax_suppressed','score_ties_threshold_and_50_rows_preserved','json_settings_preserved','source_error_cleanup','fragmented_reads_preserve_capacity_and_json','interrupted_read_retried','sample_read_bound_verified'])assert(sniff[field]===true,'Sniff resource contract failed: '+field);
        const directories=result.directory_paths;
        assert(directories?.contract==='retained-directory-path-resource-contract-v1','Missing directory path contract');
        assert(directories.local_edge_cases===3&&directories.shared_edge_cases===3&&directories.typed_local_denials===1&&directories.typed_shared_denials===3&&directories.final_reserved_bytes===0,'Directory admission edges or cleanup failed');
        assert(directories.retained_unicode_path_bytes>0&&directories.context_path_bytes===directories.retained_unicode_path_bytes&&directories.staging_path_bytes>0,'Directory path capacities are missing');
        for(const field of ['held_sibling_release_retry','relative_unicode_parent','trailing_separator_parent','staging_denial_release_retry','constructor_error_cleanup','cancelled_before_construction','early_context_error_cleanup','final_arc_owner_lifetime','published_disarm'])assert(directories[field]===true,'Directory contract failed: '+field);
        const group=result.group_catalog;
        assert(group?.contract==='decoded-group-catalog-resource-contracts-v1','Missing decoded-group contract');
        assert(group.pointer_bytes===4&&group.record_bytes>0&&group.retained_bytes>0&&group.decode_transient_bytes>=group.retained_bytes,'Invalid WASI group capacity observations');
        assert(group.typed_shared_denials===1&&group.fresh_reader_release_retries===1&&group.final_reserved_bytes===0,'Group admission/release failed');
        for(const field of ['normal_denial_terminal','immutable_record_parity','owner_survives_reader_dataset_context','malformed_terminal','buffered_cancellation_terminal','fixture_directory_removed'])assert(group[field]===true,'Group contract failed: '+field);
        const cleanup=result.cleanup_failure;
        assert(cleanup?.contract==='temporary-unlink-publication-resource-contract-v1'&&cleanup.supported===true,'Missing unlink-error contract');
        assert(cleanup.actual_unlink_failures===1&&cleanup.orphan_bytes_after_prepared_drop===3&&cleanup.path_reserved_bytes_until_context_drop>0&&cleanup.final_reserved_bytes===0,'Cleanup accounting failed');
        assert(cleanup.directory_reserved_bytes_until_context_drop>0&&cleanup.workspace_reserved_bytes_until_context_drop===cleanup.path_reserved_bytes_until_context_drop+cleanup.directory_reserved_bytes_until_context_drop,'Cleanup file/directory ownership equation failed');
        for(const field of ['path_rich_error','publication_rejected','output_directory_absent','staging_removed','orphan_data_retained_until_context_drop','workspace_removed_on_context_drop','fixture_directory_removed'])assert(cleanup[field]===true,'Cleanup contract failed: '+field);
        assert(Array.isArray(diagnostics)&&diagnostics.some((line:string)=>line.includes('chopper: cleanup failed for')),'Unlink failure diagnostic was lost');
        assert(!!result.shuffle_partition===candidate,'Unexpected resource reactor variant');
        if(candidate){
          const retained=result.shuffle_partition.retained_parent;
          assert(retained?.contract==='retained-parent-shuffle-partition-resource-contract-v1'&&retained.scope==='retained-dataset','Missing retained-parent contract');
          assert(retained.shared_bytes===64*1024*1024&&retained.temporary_budget_bytes===32*1024*1024,'Wrong fixture budgets');
          assert(Array.isArray(retained.cases)&&retained.cases.length===4,'Missing retry modes');
          assert(JSON.stringify(retained.cases.map((item:any)=>item.mode).sort())===JSON.stringify(['cancelled','cleanup','released','retained']),'Wrong retry modes');
          const outcomes:Record<string,string>={released:'original-stage-replay-success',cancelled:'cancelled-before-replay',retained:'typed-admission-denied',cleanup:'cleanup-failure-stopped-replay'};
          for(const item of retained.cases){
            assert(item.fixture_blake3==='16d32f81ce2e00d88b3476ae7112a7e01dcd63273c10e1d0a7e4e09767e70799','Retry fixture changed');
            assert(item.fused_parents===1&&item.fused_rows===8&&item.typed_denial_retries===1,'Earlier parent or retry duplicated: '+item.mode);
            assert(item.outcome===outcomes[item.mode]&&item.workspace_removed===true&&item.final_reserved_bytes===0,'Retry outcome/cleanup failed: '+item.mode);
            assert(item.directory_reserved_bytes_before_context_drop>0,'Retry directory ownership released early: '+item.mode);
            assert(item.peak_temporary_bytes>0&&item.peak_temporary_bytes<=retained.temporary_budget_bytes,'Fixture exceeded temporary budget');
            assert(item.committed_groups===(item.mode==='released'?2:1)&&item.committed_rows===(item.mode==='released'?16:8),'Wrong committed rows/groups: '+item.mode);
            assert(item.orphan_bytes_before_context_drop===(item.mode==='cleanup'?3:0),'Wrong orphan bytes: '+item.mode);
            assert(item.mode==='cleanup'?item.retained_path_bytes_before_context_drop>0:item.retained_path_bytes_before_context_drop===0,'Wrong retained path owner: '+item.mode);
            const audit=item.decision_audit,records=audit?.records;
            assert(audit?.version===1&&audit.capacity===16&&audit.reserved_bytes>0&&audit.completed_attempts===2&&audit.omitted_attempts===0&&audit.collection_denied===false,'Decision audit ownership failed: '+item.mode);
            assert(audit.selector===null&&audit.calibration===null,'Fixture unexpectedly claims a calibrated selector');
            assert(Array.isArray(records)&&records.length===2&&records[0].outcome==='fused_committed'&&records[0].observation_complete&&records[0].key_observation_complete,'First parent observation failed: '+item.mode);
            assert(records[1].admission_denial==='shared'&&records[1].admission_denial_phase==='preparation'&&records[1].phase==='original_retry','Typed retry phase lost: '+item.mode);
            assert(!records[1].observation_complete||!records[1].key_observation_complete,'Denied preparation claimed complete observations');
            assert(records[1].outcome===(item.mode==='released'?'original_committed':'terminal')&&records[1].cancelled===(item.mode==='cancelled')&&records[1].cleanup_failed===(item.mode==='cleanup'),'Decision terminal flags changed: '+item.mode);
            if(item.mode==='released'){
              // Native shared helper's serialized rows/lineage and logical stats.
              assert(item.snapshot_blake3==='63812162d082fc543c8e905c266b50fbded1f39826ee0d48313f94c1dcd03d71','Native/WASI snapshot differs');
              assert(item.logical_stats_blake3==='832d3502c4d915a7f1b7e909eacf498edd54d38617c4167bfae2e47460509ed4','Native/WASI logical stats differ');
            }else assert(item.snapshot_blake3===null&&item.logical_stats_blake3===null,'Terminal mode reported successful output');
          }
          const emission=result.shuffle_partition.terminal_emission;
          assert(emission?.contract==='shuffle-partition-terminal-emission-resource-contract-v1'&&emission.scope==='retained-dataset','Missing terminal-emission contract');
          assert(emission.typed_admission_denial===true&&emission.row_calls===1&&emission.committed_groups===0&&emission.retries===0,'Emission denial replayed rows');
          assert(emission.workspace_removed===true&&emission.final_reserved_bytes===0,'Emission denial leaked owners');
          assert(emission.directory_reserved_bytes_before_context_drop>0,'Emission directory ownership released early');
          const audit=emission.decision_audit,record=audit?.records?.[0];
          assert(audit?.reserved_bytes>0&&audit.completed_attempts===1&&audit.records.length===1&&record.outcome==='terminal'&&record.phase==='emission'&&record.terminal_admission_denial==='local'&&record.observation_complete&&record.key_observation_complete,'Emission audit lost terminal ownership or phase');
          const preparation=result.shuffle_partition.public_preparation;
          assert(preparation?.contract==='public-preparation-retained-parent-resource-contract-v1'&&preparation.entry==='prepare_with_memory_pool'&&preparation.fixture_directory_removed===true,'Missing public preparation contract');
          assert(preparation.fixture_blake3==='989fa9f23fec42032f84e885e39fa48decec71b6f87a266c979a577efcce17bb'&&preparation.headroom_bytes_at_public_stage_boundary===256*1024,'Public preparation fixture/headroom changed');
          assert(preparation.control_fused_parents===2&&preparation.control_retries===0&&preparation.direct_encoded_bytes_and_metadata_equality===true,'Public preparation control/parity changed');
          assert(preparation.expected.rows===16&&preparation.expected.output_files===9&&preparation.expected.encoded_bytes===5121016&&preparation.expected.encoded_blake3==='b67637e5cedb6320e301703da496dfb140bb79ef2fd3dd5f2b0dc908b83e8dac','Public prepared CSV identity changed');
          assert(Array.isArray(preparation.cases)&&preparation.cases.length===3&&preparation.cases.map((item:any)=>item.mode).join(',')==='released,cancelled,retained','Missing public preparation modes');
          for(const item of preparation.cases){
            assert(item.retry_entries===1&&item.source_unchanged&&item.temporary_workspace_removed&&item.output_absent_after_cleanup&&item.final_reserved_bytes===0,'Public preparation leaked or repeated retry: '+item.mode);
            assert(item.destination_published===(item.mode==='released')&&item.outcome===({released:'prepared-and-published-exact-retry',cancelled:'cancelled-before-replay',retained:'typed-shared-denial'} as Record<string,string>)[item.mode],'Wrong public preparation outcome: '+item.mode);
            assert(item.mode==='retained'?item.competing_reserved_bytes_after_prepare>0:item.competing_reserved_bytes_after_prepare===0,'Public preparation released competing capacity or retained algorithm owners');
            if(item.mode==='released'){
              const records=item.decision_audit?.records;
              assert(Array.isArray(records)&&records.length===2&&records[0].outcome==='fused_committed'&&records[1].outcome==='original_committed'&&records[1].admission_denial==='shared','Public preparation lost earlier parent or replay audit');
            }
          }
          const publication=result.shuffle_partition.publication;
          assert(publication?.contract==='retained-parent-encoded-publication-resource-contract-v1'&&publication.fixture_directory_removed===true,'Missing encoded publication contract');
          assert(publication.javascript_export_tested===false&&publication.completion_marker_tested===false,'Rust finalization claimed JavaScript export coverage');
          assert(Array.isArray(publication.cases)&&publication.cases.length===3,'Missing encoded publication modes');
          assert(JSON.stringify(publication.cases.map((item:any)=>item.mode).sort())===JSON.stringify(['cancelled_writing','cap_rejected','published']),'Wrong encoded publication modes');
          for(const item of publication.cases){
            assert(item.fixture_blake3==='989fa9f23fec42032f84e885e39fa48decec71b6f87a266c979a577efcce17bb','Encoded publication fixture changed');
            assert(item.retry_entries===1&&item.fused_parents===1&&item.final_reserved_bytes===0&&item.workspace_removed===true&&item.staging_removed===true,'Retry publication leaked or replayed: '+item.mode);
            assert(item.directory_reserved_bytes_before_context_drop>0,'Publication directory ownership released early: '+item.mode);
            assert(item.csv_encoding==='utf-16le'&&item.bom===true&&item.line_ending==='crlf'&&item.prefix_bytes===28&&item.maximum_row_bytes===640048,'Serialized encoding/prefix scope changed');
            assert(item.destination_published===(item.mode==='published')&&item.private_writing_events_before_cancellation===(item.mode==='cancelled_writing'?1:0),'Wrong publication/cancellation outcome');
            assert(item.byte_cap===(item.mode==='cap_rejected'?640075:1280124),'Wrong strict byte cap');
            const audit=item.decision_audit;
            assert(audit.reserved_bytes>0&&audit.records.length===2&&audit.records[1].admission_denial==='shared'&&audit.records[1].outcome===(item.mode==='cap_rejected'?'terminal':'original_committed'),'Encoded publication audit lost retry');
            if(item.mode==='published'){
              assert(item.output_files===5&&item.output_csv_bytes===5120904,'Byte cap did not actively split wide parent');
              assert(item.csv_blake3==='65be09d71f218621b54075b2da1c372aabd498e6740cd493d58575aa3f083aea'&&item.output_records_blake3==='357b9098aff2e4059e730da7187bd9225a574a408b7ff74e4a409ff335ba9b4d','Native/WASI encoded publication differs');
            }else assert(item.csv_blake3===null&&item.output_records_blake3===null,'Failed publication reported successful destination hashes');
          }
          assert(publication.retained_for_browser_export===true&&publication.runtime_finalization==='wasi_internal_directory','Verified WASI output was not retained for export');
          assert(browserExport?.contract==='retained-parent-browser-export-contract-v1'&&browserExport.source==='verified-wasi-retained-parent-retry'&&browserExport.destination_context==='same-origin-opfs','Missing real browser destination export contract');
          assert(browserExport.source_files===6&&browserExport.csv_files===5&&browserExport.csv_bytes===5120904&&browserExport.byte_cap===1280124&&browserExport.exact_source_bytes===true,'Browser export changed retained source bytes/caps');
          const marker=browserExport.complete_marker;
          assert(marker?.complete===true&&marker.files===6&&marker.engine==='chopper-browser'&&marker.version===1&&browserExport.marker_after_result_writers_closed===true,'Completion marker preceded closed result files');
          assert(Array.isArray(browserExport.success_files)&&browserExport.success_files.length===6&&browserExport.success_files.every((file:any)=>typeof file.name==='string'&&file.bytes>0&&/^[a-f0-9]{64}$/.test(file.sha256)),'Missing exported file identities');
          const failure=browserExport.failure;
          assert(failure?.injected_write_rejections===1&&failure.successful_target_writes_before_failure===1&&failure.abort_calls===1&&failure.closed_files>0&&failure.marker_open_calls===0&&failure.partial_directory_present===false&&failure.completion_marker_absent===true,'Mid-copy failure did not abort without marker');
          assert(browserExport.existing_destination_rejected===true,'Existing export destination was modified');
          assert(Array.isArray(browserExport.terminal_faults)&&browserExport.terminal_faults.length===3,'Missing destination finalization faults');
          for(const [index,fault] of ['close','marker_write','marker_close'].entries()){
            const item=browserExport.terminal_faults[index];
            assert(item.fault===fault&&item.abort_calls===1&&item.completion_marker_bytes===0,'Failed destination finalization retained a marker or writer: '+fault);
            assert(item.error_name===(fault==='marker_write'?'QuotaExceededError':'UnknownError'),'Wrong destination finalization error: '+fault);
          }
          assert(browserExport.destination_folders_removed===true&&browserExport.retained_source_files_removed===true,'Browser export owners or test destinations survived cleanup');
        }
        else assert(browserExport===undefined,'Base resource reactor unexpectedly exported candidate results');
        Object.assign(window,{resourceContracts:{report:result,diagnostics,browserExport}});
        contractSucceeded=true;
      }catch(error){
        contractFailure=error;
      }finally{
        engine?.terminate();
        const cleanupFailures:unknown[]=[];
        try{if(storageReady&&storage){
          const cleaned=await request(storage,{type:'cleanup'},[],'cleaned');
          Object.assign(window,{resourceContracts:{...(window as any).resourceContracts,storage:cleaned.storage}});
          assert(cleaned.storage.workspace_bytes_before_cleanup===0,'Rust left fixture bytes before worker cleanup');
          assert(cleaned.storage.workspace_bytes_after_cleanup===0,'OPFS cleanup retained bytes');
          if(contractSucceeded)assert(cleaned.storage.peak_open_handles>0,'Contract did not exercise real OPFS');
          const root=await navigator.storage.getDirectory();
          const workspaces=await root.getDirectoryHandle('chopper-workspaces');
          let removed=false;
          try{await workspaces.getDirectoryHandle(jobId);}catch(error){if(error instanceof DOMException&&error.name==='NotFoundError')removed=true;else throw error;}
          assert(removed,'Resource-contract workspace directory survived cleanup');
          Object.assign(window,{resourceContracts:{...(window as any).resourceContracts,storage:cleaned.storage,workspace_directory_removed:removed}});
        }}catch(cleanupError){cleanupFailures.push(cleanupError);}
        try{if(exportDirectoryCreated&&exportTestsRoot){
          await exportTestsRoot.removeEntry(jobId,{recursive:true});
          let removed=false;
          try{await exportTestsRoot.getDirectoryHandle(jobId);}catch(error){if(error instanceof DOMException&&error.name==='NotFoundError')removed=true;else throw error;}
          assert(removed,'Export-test directory survived parent cleanup');
          Object.assign(window,{resourceContracts:{...(window as any).resourceContracts,export_test_directory_removed:removed}});
        }}catch(cleanupError){cleanupFailures.push(cleanupError);}
        if(cleanupFailures.length){
          const cleanup=cleanupFailures.map(String).join('\n');
          throw new Error((contractFailure?String(contractFailure)+'\nCleanup: ':'Cleanup: ')+cleanup);
        }
      }
      if(contractFailure)throw contractFailure;
    });
    results.push({name:testName,seconds:(performance.now()-started)/1000});
  }catch(error){
    const message=String(error);
    results.push({name:testName,seconds:(performance.now()-started)/1000,error:message});
    Object.assign(window,{testError:message});
  }finally{
    engine?.terminate();storage?.terminate();
    Object.assign(window,{testDone:true});
    document.body.textContent=JSON.stringify({tests:results,resourceContracts:(window as any).resourceContracts},null,2);
  }
}
void main();
