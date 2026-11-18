/* Static documentation only. This application never calls the Taskiller API. */
(() => {
  'use strict';
  const D = window.TASKILLER_DATA;
  const main = document.getElementById('main');
  if (!D) {
    main.innerHTML = '<div class="error-screen"><h1>The guide data is missing.</h1><p>Run <code>python docs/tools/build_data.py</code> before serving this folder.</p></div>';
    return;
  }
  const E = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const groupNames = {auth:'Identity & access',work:'Work',focus:'Focus',execution:'Execution',analytics:'Analytics',privacy:'Privacy',operations:'Operations',health:'Health'};
  const entityById = Object.fromEntries(D.entities.map(entity => [entity.id, entity]));
  const operationById = Object.fromEntries(D.operations.map(operation => [operation.id, operation]));
  const sourceBase = 'https://github.com/kmab5/taskiller-backend/blob/main/';
  const state = {apiQuery:'',apiGroup:'all',apiMethod:'all',apiTab:'explain',objectQuery:'',entityQuery:'',journeyIndex:0,played:[],responseStatus:null,optional:false,showFramework:false};
  const paths = {
    home:'M3 10.5 12 3l9 7.5M5 9v12h5v-7h4v7h5V9',
    route:'M5 4h4v4H5zM15 16h4v4h-4zM7 8v8a2 2 0 0 0 2 2h6M17 16V8a2 2 0 0 0-2-2h-6',
    api:'m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 20',
    database:'M20 6c0 2-3.6 3-8 3S4 8 4 6s3.6-3 8-3 8 1 8 3ZM4 6v12c0 2 3.6 3 8 3s8-1 8-3V6M4 12c0 2 3.6 3 8 3s8-1 8-3',
    object:'m12 3 9 5-9 5-9-5 9-5Zm-9 5v9l9 5 9-5V8m-9 5v9',
    settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',
    book:'M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1m0-15c3-2 6-2 10-1v15c-4-1-7-1-10 1V5Z',
    search:'m20 20-5-5M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z',
    arrow:'M5 12h14m-6-6 6 6-6 6', external:'M14 4h6v6m-1-5-9 9M10 4H4v16h16v-6',
    info:'M12 11v6m0-10v.1M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z',
    shield:'m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Zm-4 10 3 3 5-6',
    menu:'M4 6h16M4 12h16M4 18h16', close:'m6 6 12 12M6 18 18 6',
    check:'m5 12 4 4L19 6', file:'M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 12h8m-8 4h6',
    spark:'m12 2 2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6L12 2Z',
    play:'m8 4 12 8-12 8V4Z', clock:'M12 7v5l3 2M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z',
    layers:'m12 3 10 5-10 5L2 8l10-5Zm-9 10 9 5 9-5M3 18l9 5 9-5',
  };
  function icon(name, small=false) { return `<svg class="icon${small?' sm':''}" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.file}"></path></svg>`; }
  function method(operation) { return `<span class="method ${operation.method.toLowerCase()}">${E(operation.method)}</span>`; }
  function pill(text, group='outline') { return `<span class="pill ${E(group)}">${E(text)}</span>`; }
  function entityLink(id) { const entity=entityById[id]; return entity ? `<a class="table-chip" href="#/database/${E(id)}">${icon('database',true)}${E(id)}</a>` : `<code>${E(id)}</code>`; }
  function schemaLink(id) { return `<a class="schema-link" href="#/objects/${encodeURIComponent(id)}">${E(id)} ↗</a>`; }
  function sources(items=[]) { return [...new Set(items)].map(path => `<a class="source-link" target="_blank" rel="noopener" href="${path.startsWith('https://')?E(path):sourceBase+E(path.replace(/:(\d+)$/, '#L$1'))}">${E(path)} ↗</a>`).join(''); }
  function pageHead(kicker, title, description, extra='') { return `<div class="page-head"><div class="kicker"><span class="tiny-strike"></span>${E(kicker)}</div><h1>${E(title)}</h1><p>${E(description)}</p>${extra}</div>`; }
  function codeBlock(value,label='JSON') {
    const text = typeof value==='string'?value:JSON.stringify(value,null,2);
    const highlighted = E(text).replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false|null|\d+)\b/g, (match,string,key,number) => string?`<span class="${key?'code-key':'code-string'}">${string}</span>${key||''}`:`<span class="code-number">${number}</span>`);
    return `<div class="code-wrap"><div class="code-bar"><span>${E(label)}</span><button data-copy="${E(text)}" aria-label="Copy ${E(label)}">Copy</button></div><pre><code>${highlighted}</code></pre></div>`;
  }
  function toast(message) { const node=document.getElementById('toast'); node.textContent=message;node.classList.add('visible');clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.classList.remove('visible'),2300); }
  function empty(title, description) { return `<div class="empty-state"><h3>${E(title)}</h3><p>${E(description)}</p><button class="button secondary small" data-action="clear-filters">Clear filters</button></div>`; }
  function operationMini(operation) { return `<a class="operation-mini" href="#/api/${E(operation.id)}">${method(operation)}<span><strong>${E(operation.title)}</strong><code>${E(operation.path)}</code></span></a>`; }
  function resolve(schema, seen=new Set()) {
    if (!schema || typeof schema!=='object') return {};
    if (schema.$ref) {
      const id=schema.$ref.split('/').pop();
      if (seen.has(id)) return {...schema,type:'object'};
      return {...resolve(D.schemas[id],new Set([...seen,id])),...Object.fromEntries(Object.entries(schema).filter(([key])=>key!=='$ref'))};
    }
    if (schema.allOf) {
      const merged={properties:{},required:[]};
      for (const branch of schema.allOf) { const value=resolve(branch,seen);Object.assign(merged,value,{properties:{...merged.properties,...value.properties},required:[...new Set([...merged.required,...value.required||[]])]}); }
      return {...merged,...Object.fromEntries(Object.entries(schema).filter(([key])=>key!=='allOf'))};
    }
    return schema;
  }
  function baseSchema(schema) { const value=resolve(schema); return value.anyOf || value.oneOf ? resolve((value.anyOf||value.oneOf).find(item=>item.type!=='null')||{}) : value; }
  function nullable(schema) { const value=resolve(schema);return value.nullable || value.type==='null' || (Array.isArray(value.type)&&value.type.includes('null')) || (value.anyOf||value.oneOf||[]).some(item=>item.type==='null'); }
  function typeHTML(schema) {
    if (schema?.$ref) return schemaLink(schema.$ref.split('/').pop());
    const value=resolve(schema);
    if(value.anyOf || value.oneOf) return (value.anyOf||value.oneOf).map(typeHTML).join('<span class="muted"> or </span>');
    if(value.type==='array') return `list of ${typeHTML(value.items||{})}`;
    return `<span class="field-type">${E(value.format || value.type || (value.properties?'object':'any value'))}</span>`;
  }
  const meanings={
    id:'A stable identifier for this record. It lets other requests refer to the same thing.',
    workItemId:'The Project, Sprint, or Chore this object belongs to or describes.',
    focusPlanId:'The saved focus plan selected for this work session.',recommendationId:'The recommendation used to explain where a selected plan came from.',
    parentId:'The Project or Sprint containing this item. A null value means there is no parent.',
    version:'A revision number. The ETag uses it to prevent an older screen overwriting newer changes.',
    createdAt:'When the server created this record.',updatedAt:'When the server last changed it.',
    email:'The email address used for sign-in and account recovery.',password:'The password supplied over HTTPS. The server stores a hash, not this value.',
    newPassword:'The replacement password, applied only after the reset token is verified.',
    token:'A temporary credential. The examples here are synthetic and cannot authenticate.',
    accessToken:'A short-lived sign-in credential sent with protected requests. Never put a real one in documentation.',
    tokenType:'The authorization scheme used with the access token.',expiresIn:'How many seconds remain in the access-token lifetime.',
    timezone:'An IANA timezone, such as Europe/Istanbul, used for local calendar and reporting boundaries.',
    locale:'The preferred language and regional presentation setting.',kind:'The category of this object; the allowed values below define the choices.',
    name:'The human-readable name shown in Taskiller.',description:'Additional context for a person reading this item.',
    status:'The current lifecycle stage. Different objects have different allowed stages.',state:'The current execution state; transitions must follow the session rules.',
    segments:'The ordered steps in a Focus Plan: work, breaks, retrieval, review, and other supported activities.',
    durationMode:'Whether a segment has a fixed target, flexible bounds, or an open duration.',
    targetSeconds:'The planned duration in seconds. Reaching it does not itself create a server event.',
    minSeconds:'The lower duration bound, when a flexible segment needs one.',maxSeconds:'The upper duration bound, when a flexible segment needs one.',
    linkedWorkItemId:'A Chore connected to this segment. It must still belong to the plan target when work starts.',
    optional:'Whether this segment may be skipped through the supported event flow.',
    template:'Whether this is a reusable plan template rather than a directly executable plan.',
    planSnapshot:'The plan as it existed at session start, preserved so later edits do not rewrite history.',
    sessionStartedAt:'The authoritative server timestamp for the beginning of this session.',
    currentSegmentStartedAt:'The current segment’s time anchor, adjusted to exclude pauses. Null means between segments.',
    currentSegmentIndex:'The zero-based position of the current segment in the saved plan snapshot.',
    occurredAt:'When the server accepted the event. This is authoritative for session history.',
    clientOccurredAt:'Optional client-reported time; it does not replace the authoritative server timestamp.',
    payload:'Event-specific information. The accepted content depends on the event type.',
    items:'The records returned in this page or collection.',page:'Information for continuing through a paginated result.',
    nextCursor:'An opaque bookmark for the next page. Pass it back unchanged.',hasMore:'Whether another page of results is available.',
    atomic:'Whether the import is all-or-nothing: either all work is imported or none of it is.',
    requestId:'An identifier used to look up an export request or correlate an API response, depending on this object.',
    downloadUrl:'A short-lived signed link to a completed export. Treat it like a credential.',
    effectiveCharacteristics:'Work Type defaults combined with this item’s explicit overrides.',
    characteristicOverrides:'Only the behavioral characteristics explicitly overridden for this item.',
    reasons:'The explainable reasons for a recommendation, rather than a hidden productivity score.',
    focusScore:'An optional self-reported focus rating after a session.',fatigueScore:'An optional self-reported fatigue rating.',
    note:'Optional written context from the person, not an automatically inferred judgement.',
  };
  function fieldMeaning(name,schema) {
    const value=baseSchema(schema);
    if (schema.description || value.description) return schema.description||value.description;
    if (meanings[name]) return meanings[name];
    if (D.fieldHelp?.[name]) return D.fieldHelp[name];
    const snake=name.replace(/[A-Z]/g,char=>'_'+char.toLowerCase());
    for (const entity of D.entities) { const field=entity.fields.find(item=>item.column===snake);if(field) return field.description; }
    if(schema.$ref) return `A ${schema.$ref.split('/').pop().replace(/([a-z])([A-Z])/g,'$1 $2').toLowerCase()} object. Open its type for every field.`;
    if(value.enum) return 'Choose one of the allowed values below; other values are rejected.';
    if(value.type==='array') return 'A collection of the objects described by its item type. Open the type to inspect its fields.';
    return `${name.replace(/([a-z])([A-Z])/g,'$1 $2').replace(/^./,char=>char.toUpperCase())}; its exact type, bounds, and nullability are shown here.`;
  }
  function constraints(schema) {
    const value=baseSchema(schema), parts=[];
    for (const [key,label] of [['minimum','minimum'],['maximum','maximum'],['minLength','min. length'],['maxLength','max. length'],['minItems','min. items'],['maxItems','max. items'],['pattern','pattern'],['multipleOf','multiple of']]) if(value[key]!==undefined) parts.push(`${label}: ${value[key]}`);
    if(value.default!==undefined) parts.push(`default: ${JSON.stringify(value.default)}`);
    if(value.readOnly) parts.push('read-only');if(value.writeOnly) parts.push('write-only');
    return parts.length?`<span class="requirements">${E(parts.join(' · '))}</span>`:'';
  }
  function schemaFields(schema,depth=0) {
    const value=resolve(schema), required=new Set(value.required||[]), properties=Object.entries(value.properties||{});
    if(!properties.length) {
      if(value.enum) return `<div class="enum-list">${value.enum.map(item=>`<code>${E(JSON.stringify(item))}</code>`).join('')}</div>`;
      if(value.anyOf||value.oneOf) return (value.anyOf||value.oneOf).map((branch,index)=>`<details class="type-branch"><summary>Variant ${index+1}: ${E(baseSchema(branch).type||branch.$ref?.split('/').pop()||'value')}</summary>${depth<4?schemaFields(branch,depth+1):typeHTML(branch)}</details>`).join('');
      return `<p class="schema-description">${typeHTML(value)}${constraints(value)}${value.additionalProperties?' · Additional named properties are accepted.':''}</p>`;
    }
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th scope="col">Property</th><th scope="col">Type & rules</th><th scope="col">In plain language</th></tr></thead><tbody>${properties.map(([name,property])=>{
      const detail=baseSchema(property), enums=detail.enum;
      const nested=depth<2 && !property.$ref && detail.properties?`<details class="technical-details"><summary>Explore nested fields</summary>${schemaFields(detail,depth+1)}</details>`:'';
      return `<tr><td><span class="field-name">${E(name)}</span><span class="field-state">${required.has(name)?'required':'optional'}${nullable(property)?' · may be null':''}</span></td><td>${typeHTML(property)}${constraints(property)}${enums?`<div class="enum-list">${enums.map(item=>`<code>${E(item)}</code>`).join('')}</div>`:''}</td><td class="description">${E(fieldMeaning(name,property))}${nested}</td></tr>`;
    }).join('')}</tbody></table></div>`;
  }
  function example(schema,name='',depth=0,optional=false,seen=new Set()) {
    if(depth>6) return null;
    if(schema?.$ref) { const id=schema.$ref.split('/').pop();if(seen.has(id)) return null;seen=new Set([...seen,id]); }
    let value=resolve(schema);
    if(value.example!==undefined) return value.example;
    if(value.examples?.length) return value.examples[0];
    if(value.anyOf||value.oneOf) value=resolve((value.anyOf||value.oneOf).find(branch=>branch.type!=='null')||{});
    if(value.const!==undefined) return value.const;
    if(value.enum) return value.enum[0];
    if(value.type==='object'||value.properties) {
      const result={}, required=new Set(value.required||[]);
      for (const [key,property] of Object.entries(value.properties||{})) if(optional||required.has(key)||!required.size) result[key]=example(property,key,depth+1,optional,seen);
      return result;
    }
    if(value.type==='array') return [example(value.items||{},name,depth+1,optional,seen)];
    if(value.type==='boolean') return value.default??false;
    if(['integer','number'].includes(value.type)) return value.default??value.minimum??(name.toLowerCase().includes('seconds')?1200:1);
    if(value.type==='null') return null;
    if(value.format==='uuid') return '3f6d43a0-7fc8-4f1b-a631-70e2dcced190';
    if(value.format==='date-time') return '2026-11-18T10:00:00Z';
    if(value.format==='date') return '2026-11-18';
    if(value.format==='email'||name==='email') return 'sam@example.test';
    if(name.toLowerCase().includes('password')) return 'Example-password-123!';
    if(name.toLowerCase().includes('token')) return 'demo-token-not-a-real-credential';
    if(name==='name'||name==='displayName') return 'Write a tiny introduction';
    if(name==='timezone') return 'Europe/Istanbul';if(name==='locale') return 'en';
    if(name==='slug') return 'writing';if(name==='description') return 'A small step for the weekend portfolio.';
    if(name==='label') return 'Write, then take a break';
    if(name==='note') return 'A small, useful bit of progress.';
    return value.default??(value.format==='uri'?'https://example.test/':'example');
  }
  function nav() {
    const sections=[['Understand',[['','home','Start here',''],['journey','route','Follow a task','7 steps']]],['Explore',[['api','api','API explorer',D.meta.apiOperations],['database','database','Database map',D.meta.entities],['objects','object','Object library',D.meta.schemas]]],['Go deeper',[['mechanics','settings','Under the hood',''],['glossary','book','Plain-English glossary',''],['reference','file','Reference notes','']]]];
    document.getElementById('nav-links').innerHTML=sections.map(([label,links])=>`<div class="nav-group"><div class="nav-label">${label}</div>${links.map(([route,symbol,title,count])=>`<a class="nav-link" data-nav="${route}" href="#/${route}">${icon(symbol)}<span>${title}</span>${count?`<span class="nav-count">${count}</span>`:''}</a>`).join('')}</div>`).join('');
  }
  const heroNodes=[
    {name:'Project',hint:'The bigger picture',table:'work_items',color:'#e66442',text:'Project, Sprint, and Chore are three kinds of Work Item. They share a table, but each has a different place in the hierarchy.'},
    {name:'Chore',hint:'One thing you can do',table:'work_items',color:'#e66442',text:'A Chore is an executable unit of work. It can sit in your inbox, a Project, or a Sprint. The backend checks that its parent belongs to you.'},
    {name:'Focus Plan',hint:'A way to approach it',table:'focus_plans',color:'#8966b0',text:'A Focus Plan turns intent into ordered segments. Work, breaks, and review have explicit duration rules—rather than one timer for everything.'},
    {name:'Execution Session',hint:'What actually happened',table:'execution_sessions',color:'#4b9277',text:'Starting work creates a session and a snapshot of the plan. Server timestamps and events keep it correct even if the browser closes.'},
    {name:'Session Events',hint:'An honest little history',table:'session_events',color:'#4b9277',text:'Pause, resume, and completion become append-only events. They are history, not a constantly running countdown process.'},
    {name:'Analytics',hint:'Learn from the real work',table:'session_reviews',color:'#537caa',text:'Analytics interprets recorded work and optional reviews. It does not invent a single mysterious productivity score.'},
  ];
  function home() {
    main.innerHTML=`<section class="home-hero"><div class="hero-copy"><div class="kicker"><span class="tiny-strike"></span>The Taskiller backend, explained</div><h1>Your tasks have a life <em>behind the screen.</em></h1><p>From “I should do this” to “here’s what happened.” Meet the API, the data, and the little rules that keep your work in sync.</p><div class="hero-actions"><a class="button" href="#/journey">Follow a task ${icon('arrow',true)}</a><a class="text-link" href="#/api">Explore the API ${icon('api',true)}</a></div><div class="hero-footnote">${icon('shield')}No backend experience required. Curiosity helps.</div></div><div class="story-map"><div class="story-map-top"><span>A small task. A whole system.</span><span class="live-label"><span class="status-dot"></span>Click to explore</span></div><div class="story-canvas">${heroNodes.map((node,index)=>`<button class="story-node" data-hero="${index}" aria-pressed="${index===3}" style="--node-color:${node.color}"><span class="node-dot"></span><strong>${node.name}</strong><small>${node.hint}</small></button>`).join('')}</div><div class="story-insight" id="hero-insight">${icon('spark')}<div><strong>Execution Session</strong><br>${E(heroNodes[3].text)}</div></div></div></section>
    <div class="home-paths"><a class="path-link" href="#/api"><div class="path-icon">${icon('api')}</div><strong>Every request has a reason.</strong><p>Browse ${D.meta.apiOperations} operations. See what they do, why they exist, and which records they touch.</p>${icon('arrow')}</a><a class="path-link" href="#/database"><div class="path-icon">${icon('database')}</div><strong>Meet the records behind it.</strong><p>Explore ${D.meta.entities} tables and their relationships. The database doesn’t have to feel like a black box.</p>${icon('arrow')}</a><a class="path-link" href="#/objects"><div class="path-icon">${icon('object')}</div><strong>Get to know every field.</strong><p>Inspect ${D.meta.schemas} API objects, from a Chore’s name to a session’s snapshot. Exact types included.</p>${icon('arrow')}</a></div>
    <section class="section home-tour"><div><div class="kicker"><span class="tiny-strike"></span>A map, not a wall of jargon</div><h2>Start with the story.<br>Go as deep as you like.</h2><p>A button in the app becomes a request. A request reaches a service. A service reads or changes records. This guide connects those dots.</p><a class="text-link" style="margin-top:20px" href="#/mechanics">See how a request travels ${icon('arrow',true)}</a></div><div class="legend-list"><div class="legend-item"><span class="legend-letter">Aa</span><div><strong>Plain language first</strong><p>What it means and why you would use it, before the technical details.</p></div></div><div class="legend-item"><span class="legend-letter">{ }</span><div><strong>The precise bits, one click away</strong><p>Headers, JSON, required fields, database columns, and source code links.</p></div></div><div class="legend-item"><span class="legend-letter">↗</span><div><strong>Follow the connections</strong><p>Jump from an endpoint to its tables, or from a property to its object definition.</p></div></div></div></section>
    <div class="home-bottom"><span>Django + PostgreSQL, with an API shared by every client.</span><a class="text-link" href="#/reference">Looking for the original technical notes? ${icon('arrow',true)}</a></div>`;
    main.querySelectorAll('[data-hero]').forEach(button=>button.addEventListener('click',()=>{
      const selected=heroNodes[Number(button.dataset.hero)];main.querySelectorAll('[data-hero]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
      document.getElementById('hero-insight').innerHTML=`${icon('spark')}<div><strong>${E(selected.name)}</strong><br>${E(selected.text)} <a href="#/database/${selected.table}" class="schema-link">See the data ↗</a></div>`;
    }));
  }
  function api(id) {
    const selected=operationById[id]||operationById.createWorkItem||D.operations[0];
    main.innerHTML=pageHead('The API explorer','Every request, with a reason.','An endpoint is a doorway into the backend. Pick one to see what goes in, what comes out, and what changes behind it.')+`<div class="explorer"><aside class="catalog" aria-label="Endpoint catalog"><div class="catalog-controls"><label class="sr-only" for="endpoint-search">Filter endpoints</label><input class="form-control" id="endpoint-search" type="search" placeholder="Find an endpoint…" value="${E(state.apiQuery)}"><div class="form-row"><label><span class="sr-only">Domain</span><select class="form-control" id="endpoint-group"><option value="all">All domains</option>${Object.entries(groupNames).filter(([key])=>key!=='operations').map(([key,label])=>`<option value="${key}" ${key===state.apiGroup?'selected':''}>${label}</option>`).join('')}</select></label><label><span class="sr-only">HTTP method</span><select class="form-control" id="endpoint-method"><option value="all">All methods</option>${['GET','POST','PUT','PATCH','DELETE'].map(value=>`<option ${value===state.apiMethod?'selected':''}>${value}</option>`).join('')}</select></label></div><div class="catalog-meta"><span id="endpoint-count"></span><span>Contract v${E(D.meta.version)}</span></div></div><div class="catalog-results" id="endpoint-list"></div></aside><section class="panel" id="endpoint-detail" aria-label="Selected endpoint"></section></div>`;
    renderAPIList(selected.id);renderAPIDetail(selected);
    const bindings=[['endpoint-search','apiQuery','input'],['endpoint-group','apiGroup','change'],['endpoint-method','apiMethod','change']];
    for(const [element,key,event] of bindings) document.getElementById(element).addEventListener(event,entry=>{state[key]=entry.target.value;renderAPIList(selected.id);});
  }
  function renderAPIList(selectedId) {
    const query=state.apiQuery.toLowerCase();
    const operations=D.operations.filter(operation=>(state.apiGroup==='all'||operation.group===state.apiGroup)&&(state.apiMethod==='all'||operation.method===state.apiMethod)&&`${operation.title} ${operation.path} ${operation.id} ${operation.what}`.toLowerCase().includes(query));
    document.getElementById('endpoint-count').textContent=`${operations.length} of ${D.operations.length} operations`;
    document.getElementById('endpoint-list').innerHTML=operations.length?operations.map(operation=>`<a class="catalog-item ${selectedId===operation.id?'active':''}" href="#/api/${E(operation.id)}" ${selectedId===operation.id?'aria-current="true"':''}>${method(operation)}<span><strong>${E(operation.title)}</strong><code>${E(operation.path)}</code></span></a>`).join(''):empty('No matching endpoints','Try a different word or clear the domain and method filters.');
  }
  function renderAPIDetail(operation) {
    const target=document.getElementById('endpoint-detail');
    const secured=(operation.contract.security||[]).some(item=>Object.keys(item).length>0);
    target.innerHTML=`<div class="api-header"><div class="stack">${method(operation)}${pill(groupNames[operation.group]||operation.group,operation.group)}${pill(secured?'Sign-in required':'Public endpoint')}</div><h2>${E(operation.title)}</h2><div class="endpoint-path">${E(operation.path)}</div></div><div class="tab-list" role="tablist" aria-label="Endpoint details">${[['explain','Explain it'],['request','Request & response'],['impact','Data impact'],['source','Implementation']].map(([key,label])=>`<button class="tab" role="tab" aria-selected="${state.apiTab===key}" data-api-tab="${key}" id="tab-${key}" aria-controls="api-tab-content">${label}</button>`).join('')}</div><div class="api-body" role="tabpanel" id="api-tab-content" aria-labelledby="tab-${state.apiTab}"></div>`;
    target.querySelectorAll('[data-api-tab]').forEach(button=>button.addEventListener('click',()=>{state.apiTab=button.dataset.apiTab;renderAPIDetail(operation);document.getElementById('tab-'+state.apiTab).focus();}));
    const content=document.getElementById('api-tab-content');
    if(state.apiTab==='explain') content.innerHTML=`<div class="api-two"><div><h3>What it does</h3><p>${E(operation.what)}</p></div><div><h3>Why you’d use it</h3><p>${E(operation.why)}</p></div></div><div class="detail-section"><h3>Behind the request</h3><ol class="steps-list">${operation.steps.map(step=>`<li>${E(step)}</li>`).join('')}</ol></div><div class="detail-section"><h3>${operation.writes.length?'Records that may change':'Records it reads'}</h3><div class="table-chips">${[...new Set(operation.writes.length?operation.writes.map(item=>item.table):operation.reads)].map(entityLink).join('')||'<span class="caption">No application records are changed.</span>'}</div></div>${operation.notes.length?`<div class="detail-section"><div class="note">${icon('info')}<div>${operation.notes.map(note=>`<p>${E(note)}</p>`).join('')}</div></div>`:''}`;
    if(state.apiTab==='request') renderRequest(operation,content);
    if(state.apiTab==='impact') content.innerHTML=`<div class="detail-section"><h3>Reads: the records it looks at</h3><div class="table-chips">${operation.reads.map(entityLink).join('')||'<span class="caption">No application data is needed.</span>'}</div></div><div class="detail-section"><h3>Writes: the records it changes</h3>${changesHTML(operation.writes)}<div class="note" style="margin-top:20px">${icon('info')}<div>A write can create, update, append, or delete a record. Background jobs can make additional changes later. Protected requests also resolve your user and device session; those shared checks are separate from the business action.</div></div></div>`;
    if(state.apiTab==='source') content.innerHTML=`<div class="detail-section"><h3>Follow it into the code</h3><p>The HTTP view checks the request. Services enforce the rules. Django’s ORM reads and writes PostgreSQL. These are the implementation files for this operation.</p>${sources(operation.source)}</div><div class="detail-section"><h3>Canonical operation ID</h3><code>${E(operation.id)}</code></div><details class="technical-details"><summary>Exact OpenAPI operation</summary>${codeBlock(operation.contract,'OpenAPI operation')}</details>`;
  }
  function changesHTML(changes=[]) {
    if(!changes.length) return '<div class="note">'+icon('book')+'<div>This operation reads information. It does not change application records.</div></div>';
    return `<div class="changes-list">${changes.map(change=>`<div class="change-row"><span class="change-action">${E(change.action)}</span><div>${entityLink(change.table)}<p>${E(change.detail||change.description)}</p></div></div>`).join('')}</div>`;
  }
  function renderRequest(operation,content) {
    const contract=operation.contract,params=contract.parameters||[],body=contract.requestBody?.content?.['application/json']?.schema;
    const statuses=Object.keys(contract.responses||{}),success=statuses.find(status=>/^2/.test(status))||statuses[0];
    if(!statuses.includes(state.responseStatus))state.responseStatus=success;
    const response=contract.responses[state.responseStatus],responseSchema=response?.content?.['application/json']?.schema||response?.content?.['application/problem+json']?.schema;
    const requestExample=body?example(body,'',0,state.optional):null;
    const secured=(contract.security||[]).some(item=>Object.keys(item).length);
    let requestPath=operation.path.replace(/\{[^}]+\}/g,'3f6d43a0-7fc8-4f1b-a631-70e2dcced190');
    const query=new URLSearchParams();
    for(const param of params.filter(item=>item.in==='query'&&item.required))query.set(param.name,param.name==='from'?'2026-11-18T09:00:00Z':param.name==='to'?'2026-11-18T10:00:00Z':String(example(param.schema,param.name)));
    if(query.size)requestPath+='?'+query.toString();
    const curl=[`curl -X ${operation.method} \\\n  'https://api.example.test${requestPath}'`,...(secured?["  -H 'Authorization: Bearer demo-access-token'"]:[]),...(operation.id==='refreshAccessToken'?["  --cookie 'taskiller_refresh=demo-refresh-token'"]:[]),...params.filter(p=>p.in==='header'&&p.required).map(param=>`  -H '${param.name}: ${param.name==='If-Match'?'"latest-etag"':'demo-request-key-001'}'`),...(body?["  -H 'Content-Type: application/json'",`  --data '${JSON.stringify(requestExample,null,2).replace(/'/g,"'\\''")}'`]:[])].join(' \\\n');
    content.innerHTML=`<div class="note warm">${icon('shield')}<div>These are generated, synthetic examples. The <code>example.test</code> address and demo credentials are not a live service. No request is sent from this guide.</div></div>${params.length?`<div class="detail-section"><h3>Headers & parameters</h3><div class="table-wrap"><table class="data-table"><thead><tr><th>Parameter</th><th>Where / type</th><th>Meaning</th></tr></thead><tbody>${params.map(param=>`<tr><td><code>${E(param.name)}</code><span class="field-state">${param.required?'required':'optional'}</span></td><td>${E(param.in)}<br>${typeHTML(param.schema||{})}${constraints(param.schema||{})}</td><td class="description">${E(param.description||parameterMeaning(param.name))}</td></tr>`).join('')}</tbody></table></div></div>`:''}<div class="detail-section"><h3>Request body</h3>${body?schemaFields(body):'<p>No JSON request body is required by this operation’s contract.</p>'}${body?`<label class="inline-checkbox"><input id="include-optional" type="checkbox" ${state.optional?'checked':''}>Include optional properties in the example</label>${codeBlock(requestExample,'Illustrative request JSON')}`:''}<details class="technical-details"><summary>Copy a cURL example</summary>${codeBlock(curl,'cURL · illustrative only')}</details></div><div class="detail-section"><h3>Response</h3><div class="status-selector" aria-label="Response status">${statuses.map(status=>`<button data-response-status="${E(status)}" class="${state.responseStatus===status?'active':''}" aria-pressed="${state.responseStatus===status}">${E(status)}</button>`).join('')}</div><p class="schema-description">${E(response?.description||'')}</p>${responseSchema?schemaFields(responseSchema)+codeBlock(example(responseSchema,'',0,true),'Illustrative response JSON'):'<p class="caption">This response has no JSON body documented in the contract.</p>'}${response?.headers?`<div class="detail-section"><h3>Response headers</h3>${Object.entries(response.headers).map(([name,value])=>`<p class="caption"><code>${E(name)}</code> — ${E(value.description||parameterMeaning(name))}</p>`).join('')}</div>`:''}</div>`;
    document.getElementById('include-optional')?.addEventListener('change',event=>{state.optional=event.target.checked;renderRequest(operation,content);});
    content.querySelectorAll('[data-response-status]').forEach(button=>button.addEventListener('click',()=>{state.responseStatus=button.dataset.responseStatus;renderRequest(operation,content);}));
  }
  function parameterMeaning(name) { return ({'Idempotency-Key':'A retry label. Reuse it for the same request, so a network retry does not create duplicate work.','If-Match':'The last ETag you read. If the record changed, the backend returns 412 instead of overwriting it.','ETag':'A revision fingerprint to send back as If-Match on a protected edit.','cursor':'An opaque bookmark from the previous page. Return it unchanged.','limit':'The maximum number of items to return in this page.','from':'Beginning of the reporting window; supply a timestamp with its timezone offset.','to':'End of the reporting window; supply a timestamp with its timezone offset.'})[name]||'An input used by this request. Its exact type, location, and bounds are part of the API contract.'; }
  function database(id) {
    const entity=entityById[id]||entityById.work_items||D.entities[0];
    if(entity.framework)state.showFramework=true;
    main.innerHTML=pageHead('The database map','Everything has a place.','Tables are collections of records. Relationships connect those records: a person owns work, a plan describes it, and a session remembers what happened.')+`<div class="database-head"><div class="caption">Select a table. Its direct relationships light up.</div><label><span class="sr-only">Find a database table</span><input class="form-control" id="table-search" type="search" placeholder="Find a table or field…" value="${E(state.entityQuery)}"></label></div><div class="db-workspace"><section class="panel" aria-label="Interactive entity relationships"><div class="panel-head"><h2>How the records connect</h2><span class="caption">${D.relations.length} foreign keys</span></div><div class="graph-scroll"><div class="graph-stage" id="graph-stage"><svg class="graph-lines" id="graph-lines" aria-hidden="true"><defs><marker id="relation-arrow" markerWidth="5" markerHeight="5" refX="5" refY="2.5" orient="auto"><path d="M0,0 L5,2.5 L0,5" style="fill:#8b9ab0;stroke:none"></path></marker></defs></svg>${['auth','work','focus','execution','operations'].map(group=>`<div class="graph-lane"><h3>${E(groupNames[group])}</h3>${D.entities.filter(item=>item.group===group).map(item=>`<button class="graph-node" data-table="${E(item.id)}" aria-pressed="${item.id===entity.id}"><strong>${E(item.id)}</strong><span>${E(item.label)}</span></button>`).join('')}</div>`).join('')}</div></div><div class="graph-key"><span class="line-sample"></span>Arrow: this record points to that record. Fields below list every relationship.</div></section><section class="panel entity-intro"><div>${pill(groupNames[entity.group],entity.group)}</div><h2>${E(entity.label)}</h2><code>${E(entity.id)}</code><p>${E(entity.summary)}</p><p>${E(entity.why)}</p><div class="relation-list"><h3 style="font-size:12px;margin-bottom:9px">Connected records</h3>${relationsHTML(entity)}</div></section></div><section class="panel entity-fields"><div class="panel-head"><h2>Inside ${E(entity.id)}</h2><span class="caption">${entity.fields.length} stored fields</span></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Database column</th><th>Storage & rules</th><th>What it means</th></tr></thead><tbody>${entity.fields.map(field=>`<tr><td><span class="field-name">${E(field.column)}</span><span class="field-state">${field.primaryKey||entity.compositeKey.includes(field.name)?'primary key':field.nullable?'nullable':'not null'}</span></td><td><span class="field-type">${E(field.type)}</span>${field.maxLength?`<span class="requirements">max. length ${field.maxLength}</span>`:''}${field.relatedTable?`<span class="requirements">${schemaLikeTableLink(field.relatedTable)}<br>${E(field.relation)}</span>`:''}</td><td class="description">${E(field.description)}</td></tr>`).join('')}</tbody></table></div></section><section class="entity-tabs panel"><div class="panel-body"><div class="detail-section"><h3>How these records change</h3><p>${E(entity.lifecycle)}</p></div><div class="detail-section"><h3>Requests that touch this table</h3><div class="readwrite-list">${D.operations.filter(op=>op.reads.includes(entity.id)||op.writes.some(change=>change.table===entity.id)).map(operationMini).join('')||'<p class="caption">This internal table is maintained by application services, the worker, or Django’s staff administration rather than a dedicated public endpoint.</p>'}</div></div>${entity.notes?.length?`<div class="detail-section"><h3>Rules worth knowing</h3><ul>${entity.notes.map(note=>`<li>${E(note)}</li>`).join('')}</ul></div>`:''}<details class="technical-details"><summary>Database constraints & indexes (${entity.constraints.length+entity.indexes.length})</summary>${[...entity.constraints,...entity.indexes].map(rule=>`<p class="caption" style="margin-top:14px"><strong>${E(rule.name)}</strong></p><pre>${E(rule.definition)}</pre>`).join('')||'<p class="caption">Primary keys and foreign keys still apply. Additional guards may be installed by migrations.</p>'}<p class="caption" style="margin-top:13px">Taskiller’s domain relations use explicit dependency removal and migration-installed guards. Django’s internal admin/auth tables have their own framework-managed relationships; their policies are separate from the public API.</p></details><details class="technical-details"><summary>Source model & implementation</summary>${sources(entity.source)}</details></div></section>`;
    const graphControls=document.createElement('label');graphControls.className='inline-checkbox';graphControls.style.margin='0';graphControls.innerHTML=`<input type="checkbox" id="framework-tables" ${state.showFramework?'checked':''}>Include Django’s ${D.meta.frameworkEntities} internal tables`;
    document.querySelector('.database-head').prepend(graphControls);
    document.getElementById('framework-tables').addEventListener('change',event=>{state.showFramework=event.target.checked;database(state.showFramework?entity.id:entity.framework?'work_items':entity.id);});
    const connected=new Set([entity.id,...D.relations.filter(relation=>relation.from===entity.id||relation.to===entity.id).flatMap(relation=>[relation.from,relation.to])]);
    document.querySelectorAll('[data-table]').forEach(button=>{button.classList.add(button.dataset.table===entity.id?'selected':connected.has(button.dataset.table)?'related':'dim');button.addEventListener('click',()=>{location.hash='/database/'+button.dataset.table;});});
    document.querySelectorAll('[data-table]').forEach(button=>{button.hidden=Boolean(entityById[button.dataset.table].framework&&!state.showFramework);});
    document.getElementById('table-search').addEventListener('input',event=>{state.entityQuery=event.target.value;const query=state.entityQuery.toLowerCase();document.querySelectorAll('[data-table]').forEach(button=>{const item=entityById[button.dataset.table],matches=`${item.id} ${item.label} ${item.fields.map(field=>field.column).join(' ')}`.toLowerCase().includes(query);if(query&&matches)button.hidden=false;else button.hidden=Boolean(item.framework&&!state.showFramework);button.style.opacity=!query||matches?'1':'.2';});requestAnimationFrame(()=>drawRelations(entity.id));});
    const fieldPanel=document.querySelector('.entity-fields'),fieldRows=[...fieldPanel.querySelectorAll('tbody tr')];
    const fieldTools=document.createElement('div');fieldTools.className='field-filterbar';fieldTools.innerHTML=`<label class="sr-only" for="database-field-search">Find a field in this table</label><input id="database-field-search" class="form-control" type="search" placeholder="Find a field in this table…"><span class="caption" id="field-view-count" aria-live="polite"></span>${fieldRows.length>8?`<button class="button secondary small" id="all-database-fields" aria-expanded="false">Show all ${fieldRows.length} fields</button>`:''}`;
    fieldPanel.querySelector('.panel-head').after(fieldTools);
    let allFields=false;
    const updateFields=()=>{const query=document.getElementById('database-field-search').value.toLowerCase();let visible=0;fieldRows.forEach((row,index)=>{row.hidden=query?!row.textContent.toLowerCase().includes(query):!allFields&&index>=8;if(!row.hidden)visible++;});document.getElementById('field-view-count').textContent=`${visible} of ${fieldRows.length} fields`;const toggle=document.getElementById('all-database-fields');if(toggle){toggle.hidden=Boolean(query);toggle.textContent=allFields?'Show fewer fields':`Show all ${fieldRows.length} fields`;toggle.setAttribute('aria-expanded',String(allFields));}};
    document.getElementById('database-field-search').addEventListener('input',updateFields);document.getElementById('all-database-fields')?.addEventListener('click',()=>{allFields=!allFields;updateFields();});updateFields();
    const relatedList=document.querySelector('.readwrite-list');if(relatedList&&relatedList.querySelectorAll('a').length>6){const details=document.createElement('details');details.className='technical-details';const summary=document.createElement('summary');summary.textContent=`Explore ${relatedList.querySelectorAll('a').length} related API operations`;relatedList.replaceWith(details);details.append(summary,relatedList);}
    requestAnimationFrame(()=>drawRelations(entity.id));
  }
  function schemaLikeTableLink(id) { return `<a class="schema-link" href="#/database/${E(id)}">${E(id)} ↗</a>`; }
  function relationsHTML(entity) {
    const relations=D.relations.filter(relation=>relation.from===entity.id||relation.to===entity.id);
    return relations.map(relation=>`<div class="relation-item"><small>${relation.from===entity.id?`${relation.field} → points to`:'referenced by'}</small>${schemaLikeTableLink(relation.from===entity.id?relation.to:relation.from)}${relation.from!==entity.id?`<small>through ${E(relation.field)}</small>`:''}</div>`).join('')||'<p class="caption">No declared foreign keys. Some identifiers or JSON payloads are logical references checked by application code.</p>';
  }
  function drawRelations(id) {
    const stage=document.getElementById('graph-stage'),svg=document.getElementById('graph-lines');if(!stage||!svg)return;
    svg.querySelectorAll('path[data-edge]').forEach(path=>path.remove());
    const bounds=stage.getBoundingClientRect();svg.setAttribute('viewBox',`0 0 ${stage.offsetWidth} ${stage.offsetHeight}`);
    for(const relation of D.relations.filter(item=>item.from===id||item.to===id)) {
      const from=stage.querySelector(`[data-table="${relation.from}"]`),to=stage.querySelector(`[data-table="${relation.to}"]`);if(!from||!to||from===to||from.hidden||to.hidden)continue;
      const a=from.getBoundingClientRect(),b=to.getBoundingClientRect(),right=b.left>a.left;
      const x1=(right?a.right:a.left)-bounds.left,y1=a.top+a.height/2-bounds.top,x2=(right?b.left:b.right)-bounds.left,y2=b.top+b.height/2-bounds.top;
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.dataset.edge='true';path.setAttribute('d',`M${x1} ${y1} C${(x1+x2)/2} ${y1},${(x1+x2)/2} ${y2},${x2} ${y2}`);path.setAttribute('marker-end','url(#relation-arrow)');svg.append(path);
    }
  }
  function objects(id) {
    const selected=D.schemas[id]?id:'WorkItemResponse' in D.schemas?'WorkItemResponse':Object.keys(D.schemas)[0];
    const schema=D.schemas[selected];
    main.innerHTML=pageHead('The object library','What’s inside the JSON?','API objects are the shapes of information crossing the wire. They are not database tables: a response may combine records, compute a value, or hide sensitive fields.')+`<div class="explorer"><aside class="catalog" aria-label="API schema catalog"><div class="catalog-controls"><label class="sr-only" for="object-search">Filter API objects</label><input id="object-search" class="form-control" type="search" placeholder="Find an object or property…" value="${E(state.objectQuery)}"><div class="catalog-meta"><span id="object-count"></span><span>Click a type to follow it</span></div></div><div class="catalog-results" id="object-list"></div></aside><section class="panel"><div class="dictionary-header"><div class="stack">${pill('API object')}${pill(Object.keys(resolve(schema).properties||{}).length+' direct properties')}</div><h2>${E(selected.replace(/([a-z])([A-Z])/g,'$1 $2'))}</h2><span class="schema-kind">${E(selected)}</span>${schema.description?`<p class="schema-description">${E(schema.description)}</p>`:''}</div>${schemaFields(schema)}<div class="dictionary-help">Required means the property must be present. Nullable means its value may be <code>null</code>. Those are separate rules. Blue object types open their own definition.</div><div class="panel-body"><details><summary class="caption">Illustrative JSON example</summary>${codeBlock(example(schema,'',0,true),'Synthetic object example')}</details><details class="technical-details"><summary>Exact schema definition</summary>${codeBlock(schema,selected)}</details></div></section></div>`;
    function renderList() {
      const query=state.objectQuery.toLowerCase();const items=Object.keys(D.schemas).sort().filter(name=>`${name} ${Object.keys(resolve(D.schemas[name]).properties||{}).join(' ')}`.toLowerCase().includes(query));
      document.getElementById('object-count').textContent=`${items.length} of ${D.meta.schemas} definitions`;
      document.getElementById('object-list').innerHTML=items.length?items.map(name=>`<a class="catalog-item ${name===selected?'active':''}" href="#/objects/${encodeURIComponent(name)}"><span class="entity-item-icon">${icon('object',true)}</span><span><strong>${E(name)}</strong><code>${D.schemas[name].enum?'allowed values':`${Object.keys(resolve(D.schemas[name]).properties||{}).length} properties`}</code></span></a>`).join(''):empty('No matching objects','Search a name such as WorkItem, a property such as version, or clear the filter.');
    }
    renderList();document.getElementById('object-search').addEventListener('input',event=>{state.objectQuery=event.target.value;renderList();});
  }
  function journey() {
    const steps=D.guides.journey,index=Math.min(state.journeyIndex,steps.length-1),step=steps[index],operation=operationById[step.operationId];
    main.innerHTML=pageHead('Follow a task','One small task. The whole journey.','Let’s draft a short outline for a weekend project. Our sample Chore starts in the inbox. Follow the records without touching the live backend.',`<div class="stack">${pill('Interactive walkthrough')}${pill('Synthetic examples · no live requests')}</div>`)+`<div class="journey-layout"><aside class="journey-stops" aria-label="Walkthrough steps">${steps.map((item,i)=>`<button class="journey-stop ${index===i?'active':''} ${state.played.includes(i)?'completed':''}" data-journey-step="${i}" aria-current="${i===index?'step':'false'}"><span class="stop-number">${state.played.includes(i)?'✓':i+1}</span><span>${E(item.title)}</span></button>`).join('')}</aside><div><section class="panel"><div class="journey-story"><div class="stack">${pill(`Step ${index+1} of ${steps.length}`)}<span class="fake-label">A simulated story</span></div><h2>${E(step.title)}</h2><p>${E(step.explanation)}</p><div class="journey-example"><span class="task-check">${icon('clock',true)}</span><div><strong>Draft a short outline</strong><small>Chore · Starts in your inbox</small></div></div><a class="operation-mini" href="#/api/${E(step.operationId)}">${method(operation)}<span><strong>${E(operation.title)}</strong><code>${E(operation.path)}</code></span></a><div class="detail-section"><h3>What changes in the database?</h3>${changesHTML(step.changes)}</div><div class="note journey-takeaway">${icon('spark')}<div>${E(step.takeaway)}</div></div><div class="journey-controls"><button class="button secondary small" data-action="reset-journey">Start over</button><button class="button" id="play-step" ${index>state.played.length?'disabled title="Simulate the earlier steps first to keep the story in order."':''}>${state.played.includes(index)?index===steps.length-1?'Story complete':'Continue the story':'Simulate this step'} ${icon('arrow',true)}</button></div></div></section><details class="journey-code"><summary class="caption">See the illustrative request and response</summary>${codeBlock(step.request,'Synthetic request')}${codeBlock(step.response,'Synthetic response')}</details><section class="journal"><h3 style="font-size:12px;margin-bottom:12px">Your local story so far</h3>${state.played.length?state.played.map(i=>`<div class="journal-entry"><span class="status-dot"></span><span>${String(i+1).padStart(2,'0')}</span><span>${E(steps[i].title)}</span><span class="muted">simulated</span></div>`).join(''):'<p class="journal-empty">Simulate a step to add it here. This journal lives only in this page’s memory.</p>'}</section></div></div>`;
    main.querySelectorAll('[data-journey-step]').forEach(button=>button.addEventListener('click',()=>{state.journeyIndex=Number(button.dataset.journeyStep);journey();}));
    document.getElementById('play-step').addEventListener('click',()=>{
      if(state.played.includes(index)) {if(index<steps.length-1)state.journeyIndex=index+1;else toast('You’ve followed the whole task. Explore any endpoint next.');}
      else {state.played=[...new Set([...state.played,index])].sort((a,b)=>a-b);toast('Simulated locally. The real backend has not changed.');}
      journey();
    });
  }
  function mechanics(id) {
    const articles=D.guides.mechanics,article=articles.find(item=>item.id===id)||articles[0],index=articles.indexOf(article);
    main.innerHTML=pageHead('Under the hood','The little rules doing the big work.','A backend is more than a list of endpoints. These are the mechanisms that keep Taskiller’s records consistent, its history honest, and its clients in sync.')+`<div class="mechanics-layout"><nav class="contents" aria-label="Backend concepts">${articles.map(item=>`<a href="#/mechanics/${E(item.id)}" class="${item.id===article.id?'active':''}">${E(item.title)}</a>`).join('')}</nav><article class="mechanic-article"><div class="stack">${pill('How it works')}${pill('Django backend')}</div><h2>${E(article.title)}</h2><p class="summary">${E(article.summary)}</p><div class="prose">${E(article.explanation).split('\n\n').map(paragraph=>`<p>${paragraph}</p>`).join('')}</div><ol class="steps-list">${(article.steps||[]).map(step=>`<li>${E(step)}</li>`).join('')}</ol>${article.example?codeBlock(article.example,'Illustrative mechanism example'):''}${article.relatedTables?.length?`<div class="detail-section"><h3>Meet the records involved</h3><div class="table-chips">${article.relatedTables.map(entityLink).join('')}</div></div>`:''}${article.relatedOperations?.length?`<div class="detail-section"><h3>Explore the requests</h3>${article.relatedOperations.map(key=>operationById[key]?operationMini(operationById[key]):'').join('')}</div>`:''}<details class="technical-details"><summary>Read the implementation</summary>${sources(article.source)}</details><div class="mechanic-next"><a class="caption" href="#/glossary">Need a term explained?</a>${index<articles.length-1?`<a class="text-link" href="#/mechanics/${E(articles[index+1].id)}">Next concept ${icon('arrow',true)}</a>`:''}</div></article></div><section class="section"><div class="section-head"><div><h2>The other public doorways</h2><p>These Django routes complement the ${D.meta.apiOperations} documented contract operations.</p></div></div><div class="runtime-route"><code>/openapi.json</code><p>The machine-readable client contract. This guide includes a <a class="schema-link" href="./assets/data/openapi.json">downloadable snapshot</a>.</p></div><div class="runtime-route"><code>/docs</code><p>The backend’s Swagger API reference. It is separate from this static GitHub Pages field guide.</p></div><div class="runtime-route"><code>/admin/</code><p>Django’s staff-only administration interface, with a separate staff login. It is not an API backdoor for ordinary clients.</p></div></section>`;
  }
  function glossary() {
    main.innerHTML=pageHead('Plain-English glossary','The jargon, translated.','A few words show up everywhere in backend work. Here’s what they mean in Taskiller, with a small example to make each one stick.')+`<label class="input-label" for="glossary-search">Find a term</label><input class="form-control" id="glossary-search" type="search" placeholder="Try ETag, record, or snapshot…" style="max-width:400px"><div class="glossary section" id="glossary-list"></div>`;
    function fill(query='') {const entries=D.guides.glossary.filter(entry=>`${entry.term} ${entry.meaning} ${entry.example}`.toLowerCase().includes(query.toLowerCase()));document.getElementById('glossary-list').innerHTML=entries.length?entries.map(entry=>`<article class="glossary-entry"><h3>${E(entry.term)}</h3><p>${E(entry.meaning)}</p><small>${E(entry.example)}</small></article>`).join(''):'<p class="caption">No matching terms. Try another word.</p>';}
    fill();document.getElementById('glossary-search').addEventListener('input',event=>fill(event.target.value));
  }
  function reference(path) {
    const note=D.notes.find(item=>item.path===path);
    if(!note) {
      main.innerHTML=pageHead('The reference shelf','The original notes, neatly shelved.','The interactive guide describes the current code. These original Markdown documents remain at their established paths for contributors and historical context.')+`<div class="note">${icon('info')}<div>Domain and migration notes record earlier stages of the project. Some mention FastAPI, Alembic, or older deployment choices. Use the current guide and source code for today’s behavior.</div></div><div class="coverage-strip"><span><strong>${D.meta.apiOperations}</strong> operations covered</span><span><strong>${D.meta.entities}</strong> tables · <strong>${D.meta.fields}</strong> fields</span><span><strong>${D.meta.schemas}</strong> API schemas</span><span>Source fingerprint <code>${E(D.meta.fingerprint)}</code></span></div><div class="reference-index section">${[...new Set(D.notes.map(item=>item.category))].map(category=>`<section class="reference-group"><h2>${E(category)}</h2>${D.notes.filter(item=>item.category===category).map(item=>`<a class="reference-note" href="#/reference/${encodeURIComponent(item.path)}">${icon('file')}<span><strong>${E(item.title)}</strong><small>${E(item.path)}</small></span></a>`).join('')}</section>`).join('')}</div>`;
      return;
    }
    main.innerHTML=`<div class="reference-top"><a class="text-link" href="#/reference">← Reference shelf</a>${pill(note.category)}<a class="text-link" href="./${E(note.path)}" download>Download Markdown ↓</a></div><div class="markdown" id="markdown-content"><p>Opening ${E(note.path)}…</p></div>`;
    const expected=location.hash;
    fetch(new URL(note.path,location.href.split('#')[0])).then(response=>{if(!response.ok)throw Error('The document could not be opened.');return response.text();}).then(text=>{if(location.hash===expected)document.getElementById('markdown-content').innerHTML=markdown(text,note.path);}).catch(()=>{if(location.hash===expected)document.getElementById('markdown-content').innerHTML=`<h1>${E(note.title)}</h1><p>This document needs an HTTP preview server or GitHub Pages to open in the reader. <a href="./${E(note.path)}">Open the Markdown file</a> or <a href="${sourceBase}docs/${E(note.path)}" target="_blank" rel="noopener">read it on GitHub</a>.</p>`;});
  }
  function markdown(text,documentPath) {
    const lines=text.replace(/\r/g,'').split('\n');let html='',fence=false,code=[],list=null;
    const inline=value=>E(value).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\[([^\]]+)\]\(([^)]+)\)/g,(all,label,url)=>{
      if(url.startsWith('https://'))return `<a href="${url}" target="_blank" rel="noopener">${label}</a>`;
      try { const resolved=new URL(url,`https://guide.invalid/docs/${documentPath}`);if(resolved.protocol!=='https:')return label;const repoPath=decodeURIComponent(resolved.pathname).replace(/^\//,'');const clean=repoPath.replace(/^docs\//,'');const target=D.notes.find(item=>item.path===clean);return target?`<a href="#/reference/${encodeURIComponent(clean)}">${label}</a>`:`<a href="${sourceBase}${E(repoPath)}${E(resolved.hash)}" target="_blank" rel="noopener">${label}</a>`;}catch{return label;}
    });
    const endList=()=>{if(list){html+=`</${list}>`;list=null;}};
    for(let i=0;i<lines.length;i++) {
      const line=lines[i];
      if(line.startsWith('```')) {endList();if(fence){html+=`<pre><code>${E(code.join('\n'))}</code></pre>`;code=[];}fence=!fence;continue;}
      if(fence){code.push(line);continue;}
      if(!line.trim()){endList();continue;}
      if(/^\|/.test(line)&&/^\|[\s:|-]+\|\s*$/.test(lines[i+1]||'')) {
        endList();const cells=value=>value.trim().replace(/^\||\|$/g,'').split('|');
        html+='<div class="markdown-table"><table><thead><tr>'+cells(line).map(cell=>`<th>${inline(cell.trim())}</th>`).join('')+'</tr></thead><tbody>';i+=2;
        while(i<lines.length&&lines[i].startsWith('|')){html+='<tr>'+cells(lines[i]).map(cell=>`<td>${inline(cell.trim())}</td>`).join('')+'</tr>';i++;}i--;html+='</tbody></table></div>';continue;
      }
      const heading=line.match(/^(#{1,6})\s+(.*)/);if(heading){endList();html+=`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`;continue;}
      const bullet=line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)/);if(bullet){const tag=/^\s*\d/.test(line)?'ol':'ul';if(list!==tag){endList();html+=`<${tag}>`;list=tag;}html+=`<li>${inline(bullet[1])}</li>`;continue;}
      endList();if(line.startsWith('> '))html+=`<blockquote>${inline(line.slice(2))}</blockquote>`;else if(!/^---+$/.test(line))html+=`<p>${inline(line)}</p>`;
    }
    endList();if(fence)html+=`<pre><code>${E(code.join('\n'))}</code></pre>`;return html;
  }
  function search(query) {
    const results=document.getElementById('search-results'),input=document.getElementById('global-search');
    if(!query.trim()){results.hidden=true;input.setAttribute('aria-expanded','false');return;}
    const words=query.toLowerCase().split(/\s+/).filter(Boolean),matches=value=>words.every(word=>value.toLowerCase().includes(word)),found=[];
    for(const operation of D.operations) if(matches(`${operation.title} ${operation.path} ${operation.id} ${operation.what}`))found.push({type:operation.method,title:operation.title,sub:operation.path,route:'api/'+operation.id});
    for(const entity of D.entities) if(matches(`${entity.id} ${entity.label} ${entity.fields.map(field=>field.column).join(' ')}`))found.push({type:'Table',title:entity.label,sub:entity.id,route:'database/'+entity.id});
    for(const [name,schema]of Object.entries(D.schemas))if(matches(`${name} ${Object.keys(resolve(schema).properties||{}).join(' ')}`))found.push({type:'Object',title:name,sub:'API data shape',route:'objects/'+encodeURIComponent(name)});
    for(const article of D.guides.mechanics)if(matches(`${article.title} ${article.summary}`))found.push({type:'Guide',title:article.title,sub:'Under the hood',route:'mechanics/'+article.id});
    results.innerHTML=`<div class="search-summary" role="presentation">${found.length?`${found.length} results · showing the first ${Math.min(found.length,12)}`:'No matches. Try “session”, “version”, or “export”.'}</div>${found.slice(0,12).map(item=>`<a class="search-result" role="option" aria-selected="false" href="#/${E(item.route)}"><span class="search-type">${E(item.type)}</span><span><strong>${E(item.title)}</strong><small>${E(item.sub)}</small></span></a>`).join('')}`;
    results.hidden=false;input.setAttribute('aria-expanded','true');
  }
  function closeNavigation({restoreFocus=true}={}){const navigation=document.getElementById('navigation'),mobile=window.matchMedia('(max-width:700px)').matches,wasOpen=navigation.classList.contains('open');navigation.classList.remove('open');navigation.inert=mobile;document.getElementById('nav-backdrop').hidden=true;const toggle=document.getElementById('menu-toggle');toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','Open navigation');if(mobile&&wasOpen&&restoreFocus)toggle.focus();}
  function route() {
    const previous=route.previous||'',hash=location.hash.replace(/^#\/?/,'');const [page,...parts]=hash.split('/');let id;
    try{id=decodeURIComponent(parts.join('/'));}catch{id='';}
    const titles={'':'Start here',api:'API explorer',database:'Database map',objects:'Object library',journey:'Follow a task',mechanics:'Under the hood',glossary:'Glossary',reference:'Reference notes'};
    document.getElementById('current-page').textContent=titles[page]||'Page not found';
    document.title=`${titles[page]||'Page not found'} — Taskiller field guide`;
    document.querySelectorAll('[data-nav]').forEach(link=>{link.classList.toggle('active',link.dataset.nav===page);if(link.dataset.nav===page)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
    const focusContent=document.getElementById('navigation').classList.contains('open');closeNavigation({restoreFocus:false});document.getElementById('search-results').hidden=true;document.getElementById('global-search').setAttribute('aria-expanded','false');
    try {
      ({'':home,api:()=>api(id),database:()=>database(id),objects:()=>objects(id),journey,mechanics:()=>mechanics(id),glossary,reference:()=>reference(id)})[page]?.();
      if(!(page in titles))main.innerHTML='<div class="error-screen"><h1>That page wandered off.</h1><p>Head back to the guide, or use search to find an endpoint, table, or object.</p><a class="button" href="#/">Start here</a></div>';
    } catch(error) { console.error(error);main.innerHTML='<div class="error-screen"><h1>This page could not open.</h1><p>Reload the guide. If you maintain it, regenerate the catalog and check the browser console.</p><a class="button" href="#/">Start here</a></div>'; }
    if(previous.split('/')[0]!==page||!['api','database','objects'].includes(page))window.scrollTo({top:0,behavior:'instant'});
    if(focusContent)main.focus({preventScroll:true});route.previous=hash;
  }
  nav();document.getElementById('search-icon').innerHTML=icon('search',true);document.getElementById('menu-toggle').innerHTML=icon('menu');
  document.querySelector('.skip-link').addEventListener('click',event=>{event.preventDefault();main.focus();main.scrollIntoView();});
  document.getElementById('global-search').addEventListener('input',event=>search(event.target.value));
  document.getElementById('global-search').addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();document.querySelector('.search-result')?.focus();}});
  document.getElementById('search-results').addEventListener('keydown',event=>{const links=[...event.currentTarget.querySelectorAll('a')],index=links.indexOf(document.activeElement);if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();links[(index+(event.key==='ArrowDown'?1:links.length-1))%links.length]?.focus();}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){document.getElementById('search-results').hidden=true;document.getElementById('global-search').setAttribute('aria-expanded','false');closeNavigation();}if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();document.getElementById('global-search').focus();}});
  document.getElementById('menu-toggle').addEventListener('click',()=>{const navigation=document.getElementById('navigation'),opened=navigation.classList.toggle('open');navigation.inert=!opened;document.getElementById('menu-toggle').setAttribute('aria-expanded',String(opened));document.getElementById('menu-toggle').setAttribute('aria-label',opened?'Close navigation':'Open navigation');document.getElementById('nav-backdrop').hidden=!opened;if(opened)navigation.querySelector('.nav-link')?.focus();});
  document.getElementById('nav-backdrop').addEventListener('click',closeNavigation);
  document.addEventListener('click',async event=>{
    const navLink=event.target.closest('[data-nav]');if(navLink&&navLink.hash===location.hash)closeNavigation();
    const copy=event.target.closest('[data-copy]');if(copy){try{await navigator.clipboard.writeText(copy.dataset.copy);toast('Copied to clipboard.');}catch{toast('Clipboard unavailable. Select the code and copy it manually.');}}
    const action=event.target.closest('[data-action]')?.dataset.action;
    if(action==='clear-filters'){state.apiQuery='';state.apiGroup='all';state.apiMethod='all';state.objectQuery='';route();}
    if(action==='reset-journey'){state.played=[];state.journeyIndex=0;journey();toast('The local story has been reset.');}
    if(!event.target.closest('.search-wrap')){document.getElementById('search-results').hidden=true;document.getElementById('global-search').setAttribute('aria-expanded','false');}
  });
  document.addEventListener('keydown',event=>{if(event.target.matches('.tab')&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const tabs=[...event.target.parentElement.querySelectorAll('.tab')],index=tabs.indexOf(event.target),next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length;tabs[next].click();}});
  let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{const navigation=document.getElementById('navigation');navigation.inert=window.matchMedia('(max-width:700px)').matches&&!navigation.classList.contains('open');const id=location.hash.match(/^#\/database\/(.+)/)?.[1]||'work_items';drawRelations(id);},100);});
  window.addEventListener('hashchange',route);route();
})();
