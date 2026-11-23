import type {Job, State} from './app';
import {configureTheme} from './theme';
import {runCommand,defaultCommandPlatform,type CommandPlatform} from './run-command';
import {version} from '../package.json';

const cliVersion=version.split('.').slice(0,2).join('.');

// Presentation only: move the existing form controls, preserving their listeners,
// validation and configuration. The native entry point never calls this module.
export function configureHostedWorkspace() {
  const get = (id: string) => document.getElementById(id)!;
  const label = (id: string) => get(id).closest('.quantity-field,label')!;
  const symbols:Record<string,string>={
    source:'<path d="M14 2H6a2 2 0 0 0-2 2v16h16V8z"/><path d="M14 2v6h6M8 12h8M8 16h5"/>',
    output:'<path d="M3 13h5l2 3h4l2-3h5v7H3zM12 3v9m-4-4 4 4 4-4"/>',
    pipeline:'<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/><path d="M9 6h6a3 3 0 0 1 3 3v6M6 9v9h9"/>',
    resources:'<path d="M5 3v6m0 4v8M12 3v12m0 4v2M19 3v2m0 4v12M2 9h6M9 15h6M16 5h6"/>',
    plan:'<path d="M8 5h13M8 12h13M8 19h13"/><path d="m2 5 1 1 2-2m-3 8 1 1 2-2m-3 8 1 1 2-2"/>',
    results:'<path d="M4 4v16h17M9 15V9m5 6V5m5 10v-4"/>'
  };
  function decorate(card:Element,key:string){
    const icon=document.createElement('span');icon.className='section-icon';icon.setAttribute('aria-hidden','true');
    icon.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${symbols[key]}</svg>`;
    card.querySelector('.section-title h2')!.before(icon);
  }
  const form = get('job-form');
  const cards = form.querySelectorAll<HTMLElement>(':scope > section');
  const [source, pipeline, limits] = cards;
  document.body.classList.add('hosted-workspace');
  configureTheme();
  const footer=document.querySelector('footer')!;
  footer.classList.add('project-footer');
  footer.innerHTML='<nav aria-label="Chopper project"><a href="https://github.com/jsmatfess/chopper" target="_blank" rel="noopener noreferrer">GitHub<span class="sr-only"> (opens in a new tab)</span></a><a href="https://buymeacoffee.com/tblflip" target="_blank" rel="noopener noreferrer">Buy me a coffee<span class="sr-only"> (opens in a new tab)</span></a></nav><div class="footer-cleanup" hidden></div>';
  const utilities=document.createElement('div');utilities.className='workspace-utilities';utilities.setAttribute('role','region');utilities.setAttribute('aria-label','Appearance and project links');
  utilities.append(document.querySelector('.theme-control')!,footer.querySelector('nav')!,footer.querySelector('.footer-cleanup')!);document.querySelector('.rail')!.append(utilities);
  document.querySelector('h1')!.textContent = 'CSV workbench';
  document.querySelector('.eyebrow')!.remove();
  document.querySelector('.intro')!.textContent = 'Split, group, shuffle. All on your device.';
  document.querySelector('.rail-note')!.remove();
  document.querySelector('.mark')!.innerHTML = '<svg width="22" height="24" viewBox="0 0 22 24" fill="none" aria-hidden="true"><path d="M9 3 2 21M20 3l-7 18" stroke="currentColor" stroke-width="3"/></svg>';
  get('add-operation').textContent = '+ Add step';
  document.querySelector('.local-badge')!.remove();
  const nav = document.createElement('nav');
  nav.className = 'workspace-nav'; nav.setAttribute('aria-label','Workspace steps');
  nav.innerHTML = '<a href="#source">Source</a><a href="#output-settings">Output</a><a href="#pipeline">Pipeline</a><a href="#review">Resources</a>';
  const toolbar=document.createElement('div');toolbar.className='workspace-toolbar';
  const dock=document.createElement('div');dock.id='run-dock';
  dock.setAttribute('role','region');dock.setAttribute('aria-label','Run controls');
  const setup=document.createElement('div');setup.className='processing-inner';
  setup.innerHTML='<div class="setup-status"><span id="run-readiness" role="status"></span><button type="button" id="run-next-step" class="text-button" hidden></button></div>';
  const run=get('run-direct');run.classList.remove('full');setup.append(run);
  const processing=document.createElement('div');processing.id='processing-strip';processing.hidden=true;
  processing.setAttribute('role','region');processing.setAttribute('aria-label','Processing status');
  processing.innerHTML='<div class="processing-inner"><div class="processing-copy"><span class="processing-dot" aria-hidden="true"></span><span id="processing-activity" role="status"></span><span id="processing-elapsed"></span></div><div class="processing-actions"><button type="button" class="secondary" id="processing-view">View execution</button><span class="processing-cancel"></span></div></div>';
  const cancel=get('cancel');cancel.textContent='Cancel';cancel.classList.remove('full');
  processing.querySelector('.processing-cancel')!.replaceWith(cancel);
  dock.append(setup,processing);document.body.append(dock);
  toolbar.append(nav);document.querySelector('header')!.after(toolbar);
  get('processing-view').onclick=()=>{
    showView('execution',false);
    const graph=document.querySelector<HTMLDetailsElement>('#execution-history');
    const target=graph??get('run-results');if(graph)graph.open=true;
    target.tabIndex=-1;target.focus({preventScroll:true});target.scrollIntoView({block:'start'});
  };
  let processingStarted:number|null=null;
  const navLinks=[...nav.querySelectorAll<HTMLAnchorElement>('a')];

  const nativeScrollspy=CSS.supports('scroll-target-group: auto'),wideNavigation=matchMedia('(min-width:1600px)');
  let selectedNavigation:HTMLAnchorElement|null=null,selectedScrollY=scrollY;
  function syncNavigation(){
    if(document.body.dataset.workspaceView==='execution')return;
    if(selectedNavigation&&scrollY!==selectedScrollY){selectedNavigation=null;delete nav.dataset.selected;}
    let current:Element|null=selectedNavigation??(nativeScrollspy?nav.querySelector('a:target-current'):null);
    if(!current){const edge=wideNavigation.matches?document.querySelector('.rail')!.getBoundingClientRect().bottom+40:toolbar.getBoundingClientRect().bottom+40;current=navLinks.filter(link=>get(link.hash.slice(1)).getBoundingClientRect().top<=edge).at(-1)??navLinks[0];if(scrollY+innerHeight>=document.documentElement.scrollHeight-2)current=navLinks.at(-1)!;}
    for(const link of navLinks){if(link===current)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');}
  }
  let navigationFrame=0;
  const scheduleNavigation=()=>{if(!navigationFrame)navigationFrame=requestAnimationFrame(()=>{navigationFrame=0;syncNavigation();});};
  document.addEventListener('scroll',scheduleNavigation,{passive:true});document.addEventListener('scrollend',syncNavigation);
  const updateNavigationSize=()=>{document.documentElement.style.setProperty('--workspace-rail-height',`${(document.querySelector('.rail') as HTMLElement).offsetHeight}px`);document.documentElement.style.setProperty('--workspace-toolbar-height',`${wideNavigation.matches?16:toolbar.offsetHeight+24}px`);scheduleNavigation();};
  const toolbarSize=new ResizeObserver(updateNavigationSize);toolbarSize.observe(toolbar);toolbarSize.observe(document.querySelector('.rail')!);wideNavigation.addEventListener('change',updateNavigationSize);
  const processingSize=new ResizeObserver(()=>document.documentElement.style.setProperty('--processing-strip-height',`${dock.offsetHeight}px`));processingSize.observe(dock);
  const sectionObserver=new IntersectionObserver(scheduleNavigation,{threshold:[0,1]});

  function title(card: HTMLElement, id: string, number: string, heading: string) {
    card.id = id; card.tabIndex = -1;
    card.querySelector('.number')!.textContent = number;
    card.querySelector('h2')!.textContent = heading;
    card.setAttribute('aria-label',heading);
  }
  title(source,'source','01','Source');
  const sourceBody = source.querySelector('.section-body')!;
  const sourceSettings = source.querySelector('details')!;
  sourceSettings.id='source-settings';
  sourceSettings.querySelector('summary')!.textContent = 'Parsing, encoding & ZIP member';
  const inputDialect = get('input-csv').parentElement!;
  const outputDialect = get('output-csv').parentElement!;
  sourceSettings.replaceChildren(sourceSettings.querySelector('summary')!,label('zip-member'),inputDialect);
  const output = document.createElement('section'); output.className = 'card';
  output.innerHTML = '<div class="section-title"><span class="number"></span><h2></h2></div><div class="section-body"></div>';
  title(output,'output-settings','02','Output');
  const outputBody = output.querySelector('.section-body')!;
  const caps = document.createElement('div'); caps.className = 'grid2';
  caps.append(label('max-rows'),label('max-bytes'));
  caps.classList.add('file-limits');
  outputBody.append(get('output-picker'),label('compression'),caps);
  const capHelp = document.createElement('p'); capHelp.className = 'hint';
  capHelp.textContent = 'Per CSV: rows or encoded bytes, including headers. Records stay whole.';
  outputBody.append(capHelp);
  const serialization = document.createElement('details');
  serialization.innerHTML = '<summary>Encoding & compression</summary>';
  serialization.append(label('compressed-bytes'),outputDialect);
  const advisory = document.createElement('p'); advisory.className = 'hint';
  advisory.textContent = 'Compressed targets are advisory and may be exceeded. A ZIP target applies to each member, not the whole archive.';
  serialization.append(advisory); outputBody.append(serialization);
  // The old two-column row is now empty; remove it rather than leave a blank gap.
  sourceBody.querySelector(':scope > .grid2')?.remove();
  source.after(output);
  title(pipeline,'pipeline','03','Pipeline');
  pipeline.querySelector<HTMLElement>('.section-body')!.id = 'pipeline-editor';
  pipeline.querySelector('.hint')!.textContent = 'Steps run in order, within the preceding groups.';
  pipeline.querySelector<HTMLElement>('.tag')!.id = 'pipeline-count';
  title(limits,'review','04','Resources');
  for(const [card,key] of [[source,'source'],[pipeline,'pipeline'],[output,'output'],[limits,'resources']] as const)decorate(card,key);
  const reviewBody = limits.querySelector('.section-body')!;
  const resources = limits.querySelector('details')!;
  resources.id = 'resource-settings';
  resources.querySelector('summary')!.textContent = 'Resource budget';
  const autoSettings=document.createElement('div');
  autoSettings.id='auto-processing';autoSettings.hidden=true;
  autoSettings.innerHTML='<p id="auto-summary"></p><details><summary>View Auto decisions</summary><p id="auto-reason" class="hint"></p><dl class="analysis-facts"><div><dt>Working memory</dt><dd id="auto-memory"></dd></div><div><dt>Processing workers</dt><dd id="auto-workers"></dd></div><div><dt>Grouping strategy</dt><dd>Automatic</dd></div><div><dt>Writer concurrency</dt><dd id="auto-writers"></dd></div><div id="auto-codec-fact" hidden><dt>Peak parallel compression workers</dt><dd id="auto-codec-workers"></dd></div></dl></details>';
  function showAutoSettings(plan?:NonNullable<State['analysis']>['auto_plan']){
    const mib=(bytes:number)=>(bytes/(2**20)).toLocaleString(undefined,{maximumFractionDigits:1})+' MiB';
    get('auto-summary').textContent=plan?`Auto · ${mib(plan.effective_memory_bytes)} · ${plan.effective_workers} worker${plan.effective_workers===1?'':'s'} · automatic grouping`:'Auto · Memory and writers sized at Run · 1 browser worker';
    const memory=plan?.memory_plan;
    get('auto-reason').textContent=plan
      ?memory?.from_analyze?'Analyze informed the starting memory target.':memory?.preview_tier_mb?'The input preview informed the starting memory target.':'The engine sized execution using the job and available working capacity.'
      :'Auto uses the input and pipeline to size working memory and writers. Safety limits apply in both modes.';
    get('auto-memory').textContent=plan?`${mib(plan.effective_memory_bytes)} budget for this Run`:'Chosen at Run · usually up to 256 MiB';
    get('auto-workers').textContent=plan?plan.effective_workers.toLocaleString():'1 in the browser';
    get('auto-writers').textContent=plan?`${plan.measurements.peak_writer_slots.toLocaleString()} peak slots used`:'Sized during Run';
    const codecWorkers=plan?.measurements.peak_deflate_workers??0;
    get('auto-codec-fact').hidden=codecWorkers===0;
    get('auto-codec-workers').textContent=codecWorkers.toLocaleString();
  }
  reviewBody.replaceChildren(label('execution-mode'),get('execution-mode-help'),autoSettings,resources);
  showAutoSettings();
  const resourceGrid=resources.querySelector('.grid2')!;
  function resourceGroup(heading:string,ids:string[]){
    const group=document.createElement('fieldset');group.className='config-group';
    const legend=document.createElement('legend');legend.textContent=heading;
    const fields=document.createElement('div');fields.className='grid2';
    group.append(legend,fields);for(const id of ids)fields.append(label(id));
    return group;
  }
  const processingFields=resourceGroup('Processing',['memory-mode','memory','workers','grouping']);
  processingFields.id='advanced-processing';
  processingFields.append(get('memory-help'));
  const safety=resourceGroup('Safety limits · independent of Auto',['max-files','max-record','temp-bytes']);
  // Browser storage has no configurable directory; retain the disabled field for import/export.
  const temporary=label('temp-dir');temporary.setAttribute('hidden','');
  resources.append(processingFields,safety,temporary);resourceGrid.remove();
  const workerLabel=label('workers');workerLabel.firstChild!.textContent='Compression workers';
  const workerHelp=document.createElement('small');workerHelp.textContent='0 lets Auto choose. Use 1 for serial compression. Gzip and ZIP use up to four workers.';workerLabel.append(workerHelp);
  get('workers').setAttribute('aria-describedby','workers-help');workerHelp.id='workers-help';
  get('memory-help').textContent='Automatic normally uses up to 256 MiB and can choose a larger budget for eligible shuffles. Manual uses 1 MiB increments. This budget covers working allocations, not total browser memory.';
  for(const id of ['zip-member']){const input=get(id) as HTMLInputElement;input.spellcheck=false;input.setAttribute('autocapitalize','none');}

  for(const card of [source,output,pipeline,limits]){
    sectionObserver.observe(card);
    card.addEventListener('click',()=>{
      selectedNavigation=navLinks.find(link=>link.hash===`#${card.id}`)!;selectedScrollY=scrollY;
      nav.dataset.selected=card.id;
      history.replaceState(history.state,'',selectedNavigation.hash);
      syncNavigation();
    });
  }
  syncNavigation();
  const facts=document.createElement('p');facts.id='source-facts';facts.className='source-facts';facts.hidden=true;label('input').after(facts);
  const preview=document.createElement('details');preview.id='source-preview';preview.hidden=true;preview.open=true;
  preview.innerHTML='<summary>Input preview <span id="source-sample-note"></span></summary>';
  const previewCard=get('preview-card');previewCard.classList.remove('card');previewCard.querySelector('.section-title')!.remove();preview.append(previewCard);facts.after(preview);
  const values=document.createElement('section');values.id='input-values';values.hidden=true;
  values.innerHTML='<div class="input-values-heading"><h3>Column values</h3><span id="input-values-count"></span></div><p class="hint" id="input-values-origin"></p><label class="input-values-filter">Find a column<input type="search" data-inspection-search placeholder="Column name" autocomplete="off"></label><div class="input-values-list"></div><p class="hint input-values-empty" hidden>No matching columns.</p>';
  const analyze=document.createElement('div');analyze.className='source-analysis-action';
  analyze.innerHTML='<p id="analyze-advice" class="hint"></p>';
  const profile=get('profile');profile.textContent='Analyze input';profile.setAttribute('aria-describedby','analyze-advice');
  const oldAnalyzeActions=profile.parentElement!;
  analyze.prepend(profile);oldAnalyzeActions.remove();
  preview.after(analyze,get('input-profile'),values);
  const valuesSearch=values.querySelector<HTMLInputElement>('input')!,valuesList=values.querySelector<HTMLElement>('.input-values-list')!;
  function filterValues(){const query=valuesSearch.value.trim().toLocaleLowerCase();let matches=0;for(const row of valuesList.querySelectorAll<HTMLElement>('details')){row.hidden=!row.dataset.search!.includes(query);if(!row.hidden)matches++;}values.querySelector<HTMLElement>('.input-values-empty')!.hidden=matches>0;}
  valuesSearch.addEventListener('input',filterValues);
  let valuesKey='';
  const actions = form.querySelector('.actions')!;
  const portable = document.createElement('div'); portable.className = 'job-portability';
  portable.append(get('import'),get('import-file'),get('export')); sourceBody.append(portable);
  actions.remove();
  const results = document.querySelector('.results')!;
  const workspace=document.querySelector('.workspace')!,shell=document.createElement('div');shell.className='configuration-shell';workspace.before(shell);shell.append(toolbar,workspace);
  const execution=document.createElement('section');execution.className='execution-pane';execution.setAttribute('aria-label','Execution graph');
  execution.innerHTML='<div class="execution-live" id="execution-live" hidden><strong id="execution-phase"></strong><span id="execution-counters"></span><button type="button" id="execution-results-link" class="text-button" hidden>View results</button></div><div class="execution-empty card"><h2>Execution will appear here</h2><p>Run your pipeline to follow its execution.</p></div>';
  workspace.prepend(execution);
  const viewControls=document.createElement('div');viewControls.className='workspace-view-controls';viewControls.setAttribute('role','group');viewControls.setAttribute('aria-label','Workspace view');
  viewControls.innerHTML='<button type="button" data-workspace-view="configuration" aria-pressed="true">Configure</button><button type="button" data-workspace-view="execution" aria-pressed="false">Execution</button>';
  const heading=document.querySelector<HTMLElement>('h1')!,intro=document.querySelector<HTMLElement>('.intro')!;
  const headingCopy=document.createElement('div');heading.before(headingCopy);headingCopy.append(heading,intro);headingCopy.after(viewControls);heading.tabIndex=-1;
  document.body.dataset.workspaceView='configuration';
  let view:'configuration'|'execution'='configuration',viewRevision=0,viewTransition:ViewTransition|undefined;
  function showView(next:'configuration'|'execution',animate=true){
    if(view===next&&document.body.dataset.workspaceView===next)return;
    view=next;const revision=++viewRevision;viewTransition?.skipTransition();
    const update=()=>{
      if(revision!==viewRevision)return;
      document.body.dataset.workspaceView=next;
      for(const button of viewControls.querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.workspaceView===next));
      heading.textContent=next==='execution'?'Execution':'CSV workbench';intro.textContent=next==='execution'?'Follow your pipeline and its output plan.':'Split, group, shuffle. All on your device.';
      const graph=document.querySelector<HTMLDetailsElement>('#execution-history');if(next==='execution'&&graph)graph.open=true;
      get('processing-view').hidden=next==='execution';
      heading.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});scheduleNavigation();
    };
    if(animate&&document.startViewTransition&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
      viewTransition=document.startViewTransition(update);void viewTransition.ready.catch(()=>{});void viewTransition.finished.catch(()=>{});
    }else update();
  }
  document.addEventListener('chopper-edit-configuration',()=>showView('configuration',false));
  document.addEventListener('chopper-execution-start',()=>{
    if(view==='execution'&&document.body.dataset.workspaceView==='execution'){heading.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
    else showView('execution');
  });
  for(const button of viewControls.querySelectorAll<HTMLButtonElement>('button'))button.onclick=()=>showView(button.dataset.workspaceView as typeof view);
  results.addEventListener('click',event=>{if((event.target as Element).closest('[data-plan-target]'))showView('configuration',false);},true);
  results.querySelector('.footnote')?.remove();
  get('empty-plan').replaceChildren();
  get('export').textContent = 'Export job'; get('import').textContent = 'Import job';
  const observations = results.querySelector<HTMLElement>('.plan')!;
  observations.querySelector('h2')!.textContent = 'Output plan';
  observations.id = 'output-plan'; observations.tabIndex = -1;decorate(observations,'plan');
  const cli=document.createElement('details');cli.className='cli-handoff';
  cli.innerHTML='<summary>Run in CLI</summary><fieldset class="cli-platform-tabs"><legend class="sr-only">Platform & shell</legend><label><input type="radio" name="cli-platform" value="windows"><span>Windows<small>PowerShell</small></span></label><label><input type="radio" name="cli-platform" value="linux"><span>Linux<small>Bash</small></span></label><label><input type="radio" name="cli-platform" value="macos"><span>macOS<small>zsh / Bash</small></span></label></fieldset><pre tabindex="0"><code id="cli-command"></code></pre><div class="cli-actions"><button type="button" class="secondary" id="cli-export">Export job JSON</button><button type="button" class="secondary" command="--copy" commandfor="cli-command">Copy command</button><a id="cli-download" href="https://github.com/jsmatfess/chopper/releases">CLI releases</a></div><p class="cli-copy-status" role="status"></p><p id="cli-help"></p><p id="cli-platform-help"></p>';
  observations.querySelector('.section-body')!.append(cli);
  get('cli-export').onclick=()=>get('export').click();
  let copyTimer:ReturnType<typeof setTimeout>|undefined,lastCopyMessage='';
  let cliJob:Job|null=null;
  const cliPlatforms=[...cli.querySelectorAll<HTMLInputElement>('[name=cli-platform]')];
  cliPlatforms.find(input=>input.value===defaultCommandPlatform((navigator as Navigator & {userAgentData?:{platform:string}}).userAgentData?.platform??navigator.platform))!.checked=true;
  function renderCommand(){
    const platform=cliPlatforms.find(input=>input.checked)!.value as CommandPlatform,windows=platform==='windows';
    const equivalent=cliJob?runCommand(cliJob,platform):null,executable=windows?'chopper.exe':'chopper';
    get('cli-command').textContent=equivalent?.command??'';
    cli.querySelector<HTMLButtonElement>('[command="--copy"]')!.disabled=!equivalent;
    get('cli-help').textContent=!equivalent?'Finish the configuration to generate a command.':equivalent.usesJson?`This job needs JSON to preserve its settings within native command-line limits. Export the job, replace input and output with full local paths, then run beside ${executable} and chopper-job.json.`:`Steps follow editor order. Replace the browser names with full local paths on the target system; output must name a new folder. Run beside ${executable}. JSON export remains available.`;
    get('cli-platform-help').textContent=windows?`Use Chopper ${cliVersion} with PowerShell 7.3+ and its default argument handling.`:`Use the Chopper ${cliVersion} Linux CLI package. macOS currently requires a source build.`;
    const download=get('cli-download') as HTMLAnchorElement;
    download.href=windows?'https://github.com/jsmatfess/chopper/releases':'https://github.com/jsmatfess/chopper';
    download.textContent=windows?'CLI releases':'Build CLI from source';
    clearTimeout(copyTimer);cli.querySelector('.cli-copy-status')!.textContent='';
  }
  for(const input of cliPlatforms)input.onchange=renderCommand;

  async function copyCommand(){
    if(!get('cli-command').textContent)return;
    let message='Copied';
    try{await navigator.clipboard.writeText(get('cli-command').textContent!);}
    catch{message='Copy failed. Select the command and copy it manually.';}
    if(message===lastCopyMessage)message+='\u00a0';lastCopyMessage=message;
    cli.querySelector('.cli-copy-status')!.textContent=message;
    clearTimeout(copyTimer);copyTimer=setTimeout(()=>{cli.querySelector('.cli-copy-status')!.textContent='';},4000);
  }
  if('CommandEvent' in window)get('cli-command').addEventListener('command',event=>{if((event as Event & {command:string}).command==='--copy')void copyCommand();});
  else cli.querySelector<HTMLButtonElement>('[command="--copy"]')!.onclick=()=>void copyCommand();
  const report=document.createElement('section');report.id='run-results';report.className='card run-results';report.hidden=true;
  report.innerHTML='<div class="section-title"><h2>Results</h2></div><div class="section-body"></div>';
  report.querySelector('.section-title')!.append(get('status'));report.querySelector('.section-title')!.setAttribute('aria-live','polite');
  const reportBody=report.querySelector('.section-body')!;
  for(const id of ['result-path','analysis','progress'])reportBody.append(get(id));
  observations.after(report);decorate(report,'results');
  get('execution-results-link').onclick=()=>{
    report.tabIndex=-1;report.focus({preventScroll:true});
    report.scrollIntoView({block:'nearest',behavior:'instant'});
  };
  nav.addEventListener('click',event=>{
    const link=(event.target as HTMLElement).closest<HTMLAnchorElement>('a');
    if(!link)return;
    const target=get(link.hash.slice(1));
    target.focus();
  });
  // Native validation must be able to reveal an invalid control in a disclosure.
  form.addEventListener('invalid',event=>{
    showView('configuration',false);
    let parent=(event.target as HTMLElement).parentElement;
    while(parent){if(parent instanceof HTMLDetailsElement)parent.open=true;parent=parent.parentElement;}
  },true);
  return {
    readiness(next:{message:string;reveal:()=>void}|undefined){
      const button=get('run-next-step') as HTMLButtonElement;
      button.hidden=!next;
      const message=next?.message.replace(/ with Browse\.$/,'.')??'';
      const step=message.match(/^Step (\d+):/);
      button.textContent=message.length<=64?message:step?`Review step ${step[1]}`:'Review a setting';
      button.title=next?.message??'';
      button.onclick=next?.reveal??null;
      get('run-readiness').textContent=next?'':'Ready to run';
    },
    preview(schema:{columns:number;preview:string[][]}|null,failed=false){
      const input=get('input') as HTMLInputElement;
      facts.hidden=!input.value;preview.hidden=!failed&&!schema?.preview.length;
      const bytes=input.dataset.fileName===input.value?Number(input.dataset.fileBytes):NaN;
      const unit=bytes>=1024**3?'GiB':bytes>=1024**2?'MiB':'KiB',divisor=bytes>=1024**3?1024**3:bytes>=1024**2?1024**2:1024;
      const fileSize=Number.isFinite(bytes)?`${(bytes/divisor).toLocaleString(undefined,{maximumFractionDigits:1})} ${unit}`:null;
      facts.textContent=[fileSize,schema?`${schema.columns.toLocaleString()} columns`:null].filter(Boolean).join(' · ')||'File details available after choosing a source with Browse.';
      get('source-sample-note').textContent=schema?`${schema.preview.length.toLocaleString()} sample row${schema.preview.length===1?'':'s'}`:'';
    },
    values(columns:{column:number;values:string[];frequencies?:Record<string,number>;truncated:boolean;distinct?:number;distinct_exact?:boolean}[],header:string[]|null,origin:string,rows=0){
      const key=JSON.stringify([columns,header,origin,rows]);if(key===valuesKey)return;valuesKey=key;
      values.hidden=!columns.length;
      if(!columns.length){valuesList.replaceChildren();valuesSearch.value='';return;}
      const expanded=new Set([...valuesList.querySelectorAll<HTMLDetailsElement>('details[open]')].map(row=>row.dataset.column));
      valuesList.replaceChildren();
      get('input-values-count').textContent=`${columns.length.toLocaleString()} analyzed`;
      get('input-values-origin').textContent=`${origin} · selected columns only.`;
      valuesSearch.closest('label')!.hidden=columns.length<6;
      for(const column of columns){
        const row=document.createElement('details'),summary=document.createElement('summary'),indexLabel=document.createElement('span'),name=document.createElement('span'),count=document.createElement('span'),list=document.createElement('ul'),note=document.createElement('small');
        row.className='column-values-row';row.dataset.column=String(column.column);row.dataset.countKind=column.distinct===undefined?'values':column.distinct_exact?'exact':'estimated';
        indexLabel.className='column-values-index';indexLabel.textContent=`#${column.column}`;indexLabel.setAttribute('aria-hidden','true');row.open=expanded.has(row.dataset.column);
        name.className='column-values-name';name.textContent=header?.[column.column]??`Column #${column.column}`;row.dataset.search=name.textContent.toLocaleLowerCase();
        count.className='column-values-count';count.textContent=column.distinct===undefined?`${column.values.length.toLocaleString()}${column.truncated?'+':''} values shown`:`${column.distinct_exact?'':'~'}${column.distinct.toLocaleString()} distinct · ${column.distinct_exact?'exact':'estimated'}`;
        list.className='value-chips';list.setAttribute('role','list');list.tabIndex=0;list.setAttribute('aria-label',`Retained values for ${name.textContent}`);for(const value of column.values){const item=document.createElement('li');item.textContent=value||'(empty)';if(value==='')item.dataset.empty='true';list.append(item);}
        const frequencies=column.frequencies;
        const ranked=column.values.map(value=>({value,count:frequencies&&Object.hasOwn(frequencies,value)?frequencies[value]:NaN}));
        const shares=!column.truncated&&rows>0&&ranked.length>0&&ranked.every(entry=>Number.isSafeInteger(entry.count)&&entry.count>0)&&ranked.reduce((sum,entry)=>sum+entry.count,0)===rows;
        if(shares){
          ranked.sort((a,b)=>b.count-a.count);list.classList.add('value-distribution');list.setAttribute('aria-label',`Value shares for ${name.textContent}, largest first`);list.replaceChildren();
          for(const {value,count:frequency} of ranked){
            const item=document.createElement('li'),label=document.createElement('span'),share=document.createElement('span'),track=document.createElement('span'),fill=document.createElement('span');
            label.className='value-label';label.textContent=value||'(empty)';share.className='value-share';
            const percent=100*frequency/rows;share.textContent=percent<0.1?'<0.1%':`${percent.toLocaleString(undefined,{maximumFractionDigits:1})}%`;
            item.title=`${frequency.toLocaleString()} of ${rows.toLocaleString()} input rows`;track.className='value-track';track.setAttribute('aria-hidden','true');fill.className='value-fill';fill.style.inlineSize=`${percent}%`;track.append(fill);item.append(label,share,track);list.append(item);
          }
        }
        note.textContent=shares?'Share of all input rows · exact counts · largest first.':column.truncated?`Showing ${column.values.length.toLocaleString()} values; more exist. Shares omitted for this column.`:`All ${column.values.length.toLocaleString()} values shown.`;
        summary.append(indexLabel,name,count);row.append(summary,list,note);valuesList.append(row);
      }
      filterValues();
    },
    draft(job: Job | null, operations: number, dirty: boolean) {
      if(dirty)showAutoSettings();
      cliJob=job;renderCommand();
      get('pipeline-count').textContent = operations ? `${operations} step${operations===1?'':'s'}` : 'Optional';
      get('draft-source').textContent = job?.input ? `Read ${job.input}${job.zip_member?` → ${job.zip_member}`:''}.` : 'Choose a source file to begin.';
      const format=job?.compression==='zip'?'a ZIP of CSVs':job?.compression==='gzip'?'gzip-compressed CSVs':'uncompressed CSVs';
      const amount=(id:string)=>{const input=get(id) as HTMLInputElement;const unit=(document.getElementById(id+'-unit') as HTMLSelectElement|null)?.value;return input.value?`${input.value}${unit?' '+unit:''}`:'';};
      const caps=[job?.limits.rows?`${job.limits.rows.toLocaleString()} rows`:'',job?.limits.bytes?amount('max-bytes'):''].filter(Boolean);
      const destination=job?.output?` to a new folder in ${job.output}`:'';
      get('draft-output').textContent=`Write ${format}${destination}${caps.length?`. Up to ${caps.join(' and ')} per CSV`:''}.`;
      get('analyze-advice').textContent=job?.operations.some(op=>op.type==='partition'&&op.columns?.length)
        ?'Optional. Estimate distinct partition keys and inspect column values.'
        :'Optional. Count input rows and inspect column values.';
      get('draft-resources').textContent = job ? !(get('execution-mode') as HTMLInputElement).checked ? 'Auto sets working memory, workers, grouping and writers.' : `${job.resources.memory_mb==='auto'?'Auto budget · chosen at Run':`${(get('memory') as HTMLInputElement).value} ${(get('memory-unit') as HTMLSelectElement).value} working budget`} · ${job.resources.workers===0?'auto workers':`${job.resources.workers} worker(s)`}.` : 'Finish the highlighted configuration fields to review the draft.';
    },
    state(state: State, dirty: boolean) {
      if(state.status==='complete'&&!dirty)showAutoSettings(state.analysis?.auto_plan);
      const busy=['profiling','running'].includes(state.status),finished=processingStarted!==null&&!busy;
      const completed=state.status==='complete'?state.analysis:null;
      const files=completed?`${completed.output_files.toLocaleString()} CSV ${completed.output_files===1?'file':'files'}`:'';
      processing.hidden=!busy;setup.hidden=busy;get('execution-live').hidden=!busy&&!completed;
      const viewResults=get('execution-results-link');viewResults.hidden=!completed;
      if(completed){
        get('execution-phase').textContent=dirty?`Previous run · ${files} saved`:`${files} saved`;
        get('execution-counters').textContent=[state.output,completed.warnings.length?`${completed.warnings.length} ${completed.warnings.length===1?'warning':'warnings'}`:''].filter(Boolean).join(' · ');
      }
      if(busy){
        if(run===document.activeElement)cancel.focus({preventScroll:true});
        get('execution-phase').textContent=state.progress.phase||'Processing';
        get('execution-counters').textContent=[
          state.progress.rows>0?`${state.progress.rows.toLocaleString()} ${state.progress.rows===1?'row':'rows'} in this phase`:'',
          state.progress.temp_bytes>0?`${(state.progress.temp_bytes/2**20).toLocaleString(undefined,{maximumFractionDigits:1})} MiB temporary storage`:'',
        ].filter(Boolean).join(' · ');
      }
      get('processing-view').hidden=view==='execution';
      if(busy){
        processingStarted??=performance.now();
        const phase=state.progress.phase||'Processing',activity=get('processing-activity');
        if(activity.textContent!==phase)activity.textContent=activity.title=phase;
        get('processing-elapsed').textContent=`${Math.floor((performance.now()-processingStarted)/1000).toLocaleString()} s elapsed`;
      }else{
        processingStarted=null;
        if(finished&&state.status==='cancelled'&&document.activeElement===document.body)run.focus({preventScroll:true});
      }
      scheduleNavigation();
      report.hidden=!state.analysis&&['idle','profiled','profiling','running'].includes(state.status);
      get('analysis').setAttribute('aria-label',dirty?'Previous processing result; draft has changed':'Processing result');
      if(dirty && state.analysis) {
        const saved=state.status==='complete'&&state.output?` Last completed result folder: ${state.output}.`:'';
        get('result-path').textContent = `Draft changed. Processing results describe the previous submitted configuration.${saved} Run again to process the current settings.`;
      }
      if(completed&&!dirty){
        get('result-path').textContent=`✓ Complete. ${files} ${cliJob?.compression==='zip'?'in a ZIP archive saved to':'saved to'} ${state.output}.`;
      }
      if(finished&&['complete','failed','profiled'].includes(state.status)&&!(document.activeElement as HTMLElement|null)?.closest('#job-form')){
        const active=document.activeElement as HTMLElement|null;
        if(view==='execution'&&state.status!=='failed'){
          if(active?.closest('#run-dock')||active===get('cancel')||active===document.body)heading.focus({preventScroll:true});
        }else{const target=state.status==='failed'?get('error'):state.status==='profiled'?get('input-profile'):report;target.tabIndex=-1;target.focus({preventScroll:true});target.scrollIntoView({block:view==='execution'?'nearest':'start'});}
      }
    },
  };
}
