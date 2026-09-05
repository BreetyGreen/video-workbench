(() => {
  const $ = id => document.getElementById(id);
  const message = text => { $('course-message').textContent = text; };
  const states = {queued:'已排队',running:'学习教程 / 剪辑中',awaiting_device:'成片已完成，等待电脑接收',delivered_to_jianying:'助手已确认写入剪映草稿',handoff_failed:'草稿接收失败',quality_blocked:'质检未通过，未投递',failed:'生成失败',interrupted:'服务曾中断，请先检查已有成片，不会自动重跑'};
  const errors = {device_unavailable:'接收电脑不存在或已停用，请重新配对后新建计划',selected_material_unavailable_or_unlicensed:'选中的素材不属于课程，或没有相应使用权',course_recipe_required:'尚未得到有效的教程规则',course_not_found:'课程不存在'};
  let catalog = {courses:[],devices:[]};
  let plansLoading = false;
  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const body = await response.json();
    if (!response.ok) throw new Error(errors[body.detail] || (typeof body.detail === 'string' ? body.detail : '请求未通过，请检查输入'));
    return body;
  }
  const json = (method, body) => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  function option(value, text) { const node = document.createElement('option'); node.value=value; node.textContent=text; return node; }
  function selectedCourse() {
    const course = catalog.courses.find(c => c.id === $('course-select').value);
    $('course-materials').replaceChildren();
    $('course-recipe').textContent = course ? (course.recipe_id ? '已有学习配方；生成时使用最新配方。' : '首次执行会先分析教程，再按提取规则剪辑。') : '先导入一门课程。';
    for (const asset of course?.assets || []) {
      if (asset.role !== 'material' || !asset.mime_type.startsWith('video/')) continue;
      const label = document.createElement('label'); label.className='check';
      const input = document.createElement('input'); input.type='checkbox'; input.value=asset.id;
      input.checked = asset.rights_status !== 'unknown'; input.disabled = asset.rights_status === 'unknown';
      label.append(input, document.createTextNode(`${asset.name} · ${asset.rights_status === 'commercial_authorized' ? '商用已授权' : asset.rights_status === 'personal_learning' ? '仅个人学习' : '使用权未知，不可用'}`));
      $('course-materials').append(label);
    }
  }
  async function loadCatalog(selected) {
    catalog = await api('/api/course-schedules/catalog');
    $('course-select').replaceChildren(...catalog.courses.map(c=>option(c.id,c.title)));
    if (selected) $('course-select').value=selected;
    $('course-device').replaceChildren(option('','当前服务所在电脑（本地使用）'),...catalog.devices.map(d=>option(d.id,d.name)));
    selectedCourse();
    message(catalog.worker_enabled ? '计划保存后可立即生成，也可按每日时间运行。' : '当前服务关闭了调度器：可以保存计划，但队列暂不执行。请管理员启用 AUTOMATION_SCHEDULER_ENABLED。');
  }
  async function loadPlans() {
    if (plansLoading) return;
    plansLoading = true;
    try {
    const plans = await api('/api/course-schedules');
    const fragment = document.createDocumentFragment();
    for (const plan of plans) {
      const panel = document.createElement('article'); panel.className='course-plan';
      const title = document.createElement('h3'); title.textContent=plan.title;
      const desc = document.createElement('p'); desc.textContent=`${plan.enabled ? '每日 '+plan.daily_time+' · '+plan.timezone : '自动执行已暂停 / 手动计划'} · ${plan.cloud_processing_allowed ? '允许云处理' : '仅本地处理'}`;
      const actions=document.createElement('div'); actions.className='course-actions';
      const now=document.createElement('button'); now.textContent='立即生成（当日一次）';
      now.onclick=async()=>{now.disabled=true;try{const run=await api(`/api/course-schedules/${plan.id}/run`,{method:'POST'});message(states[run.state] || run.state);await loadPlans();}catch(e){message(e.message);}finally{now.disabled=false;}};
      const pause=document.createElement('button'); pause.textContent=plan.enabled?'暂停每日执行':'开启每日执行';
      pause.onclick=async()=>{pause.disabled=true;try{await api(`/api/course-schedules/${plan.id}`,json('PATCH',{enabled:!plan.enabled}));await loadPlans();}catch(e){message(e.message);}finally{pause.disabled=false;}};
      actions.append(now,pause); panel.append(title,desc,actions);
      const runs=await api(`/api/course-schedules/${plan.id}/runs`);
      for (const run of runs) {
        const row=document.createElement('p'); row.textContent=`${run.local_date} · ${states[run.state] || run.state}${run.error_code?' · '+(errors[run.error_code]||run.error_code):''} `;
        if(run.task_id){const link=document.createElement('a');link.href='/review/'+encodeURIComponent(run.task_id);link.textContent='查看成片与证据';row.append(link);}
        panel.append(row);
      }
      if(!runs.length){const empty=document.createElement('p');empty.textContent='暂无执行记录';panel.append(empty);}
      fragment.append(panel);
    }
    $('course-plans').replaceChildren(fragment);
    if(!plans.length) $('course-plans').textContent='还没有计划，请先选择课程和素材。';
    } finally { plansLoading = false; }
  }
  $('course-select').onchange=selectedCourse;
  $('course-refresh').onclick=()=>loadPlans().catch(e=>message(e.message));
  $('course-upload').onsubmit=async event=>{
    event.preventDefault(); const form=event.target;const button=form.querySelector('button');button.disabled=true;
    try {
      const tutorials=[...form.elements.tutorial.files],materials=[...form.elements.materials.files];
      const data=new FormData();data.set('title',form.elements.title.value);data.set('source_type','web_upload');data.set('source_message_id','web-'+crypto.randomUUID());
      data.set('asset_roles',JSON.stringify([...tutorials.map(()=> 'tutorial'),...materials.map(()=> 'material')]));
      data.set('rights_statuses',JSON.stringify([...tutorials.map(()=> 'personal_learning'),...materials.map(()=> form.elements.rights.value)]));
      [...tutorials,...materials].forEach(file=>data.append('files',file));
      message('正在上传文件，请勿关闭页面…'); const course=await api('/api/courses/intake',{method:'POST',body:data});await loadCatalog(course.id);message('导入成功。请选择视频素材并保存计划。');
    }catch(e){message(e.message);}finally{button.disabled=false;}
  };
  $('course-plan-form').onsubmit=async event=>{
    event.preventDefault();const form=event.target;const fields=form.elements;const button=form.querySelector('button');button.disabled=true;
    try {
      const payload={course_id:$('course-select').value,material_ids:[...$('course-materials').querySelectorAll('input:checked')].map(x=>x.value),device_id:$('course-device').value||null};
      for(const key of ['title','requirements_text','content_type','daily_time','timezone'])payload[key]=fields[key].value;
      for(const key of ['commercial','cloud_processing_allowed','enabled'])payload[key]=fields[key].checked;
      await api('/api/course-schedules',json('POST',payload));await loadPlans();message('计划已保存。可以点“立即生成”，或等待所设置的每日时间。');
    }catch(e){message(e.message);}finally{button.disabled=false;}
  };
  loadCatalog().then(loadPlans).catch(e=>message(e.message));
  setInterval(()=>{if(!document.hidden)loadPlans().catch(()=>{});},15000);
})();
