/* FrameBurn 升级版前端交互（原生 JS，零依赖）
   对接端点：/health /api/v1/versions /api/v1/functions /api/v1/tasks ... 均为现有后端
*/
(function () {
  'use strict';

  const form = document.getElementById('generate-form');
  const promptBox = document.getElementById('prompt');
  const promptChips = document.getElementById('prompt-chips');
  const qualityPills = document.getElementById('quality-pills');
  const durationPills = document.getElementById('duration-pills');
  const modeSelect = document.getElementById('mode');
  const providerSelect = document.getElementById('provider');
  const videoFileInput = document.getElementById('video-file');
  const videoModeHint = document.getElementById('video-mode-hint');
  const audioCheck = document.getElementById('with_audio');
  const submitBtn = document.getElementById('submit-btn');
  const stepsBox = document.getElementById('steps');
  const resultHolder = document.getElementById('result-holder');
  const billCard = document.getElementById('bill-card');
  const billKvs = document.getElementById('bill-kvs');
  const alertBox = document.getElementById('alert-box');
  const gallery = document.getElementById('gallery');
  const galleryGrid = document.getElementById('g-grid');
  const insights = document.getElementById('insights');
  const insightSourceList = document.getElementById('insight-source-list');
  const insightPatternList = document.getElementById('insight-pattern-list');
  const insightTemplateList = document.getElementById('insight-template-list');
  const statusPill = document.getElementById('status-pill');
  const statusText = document.getElementById('status-text');

  const DEFAULT_CHIPS = [
    '夜晚城市，雨雾弥漫，镜头缓慢推进，人物在路灯下抬头望向天空',
    '一个孩子在公园里放风筝，金色阳光，镜头上移',
    '产品漂浮在太空中，柔和光线，缓慢旋转',
    '赛博朋克街道，霓虹灯闪烁，镜头快速拉近主角背影',
  ];

  let activePollTimer = null;

  function clearActivePoll() {
    if (activePollTimer) {
      window.clearTimeout(activePollTimer);
      activePollTimer = null;
    }
  }

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const fmtNum = (v) => (typeof v === 'number' && !Number.isNaN(v) ? new Intl.NumberFormat('zh-CN').format(v) : '0');
  const fmtTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  };
  const STATUS_CN = { queued: '排队中', running: '生成中', completed: '已完成', failed: '失败', canceled: '已取消' };

  /* ---------- 服务状态徽章 ---------- */
  async function refreshHealth() {
    try {
      const res = await fetch('/health');
      if (res.ok) {
        statusPill.classList.add('ok');
        statusPill.classList.remove('down');
        statusText.textContent = '服务在线';
      } else {
        throw new Error('bad status');
      }
    } catch {
      statusPill.classList.add('down');
      statusPill.classList.remove('ok');
      statusText.textContent = '服务降级';
    }
  }

  /* ---------- 示例 prompt 胶囊 ---------- */
  function renderChips() {
    promptChips.innerHTML = '';
    DEFAULT_CHIPS.forEach((text) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip';
      btn.textContent = text.length > 26 ? text.slice(0, 26) + '…' : text;
      btn.title = text;
      btn.addEventListener('click', () => { promptBox.value = text; promptBox.focus(); });
      promptChips.appendChild(btn);
    });
  }

  /* ---------- 参数目录（画质/时长 pills） ---------- */
  let catalog = { qualities: [], providers: [] };

  function renderPill(container, name, value, label, checked) {
    const id = `${name}-${value}`;
    const input = document.createElement('input');
    input.type = 'radio';
    input.id = id;
    input.name = name;
    input.value = value;
    input.checked = checked;
    const lbl = document.createElement('label');
    lbl.htmlFor = id;
    lbl.textContent = label;
    container.appendChild(input);
    container.appendChild(lbl);
    return input;
  }

  function renderQualityPills() {
    qualityPills.innerHTML = '';
    if (!catalog.qualities.length) {
      qualityPills.textContent = '暂无可选画质';
      return;
    }
    catalog.qualities.forEach((q, idx) => {
      const input = renderPill(qualityPills, 'quality', q.id, q.label, idx === 0);
      input.addEventListener('change', renderDurationPills);
    });
  }

  function renderDurationPills() {
    durationPills.innerHTML = '';
    const selected = qualityPills.querySelector('input[name="quality"]:checked');
    const q = catalog.qualities.find((item) => item.id === (selected ? selected.value : ''));
    const min = q ? q.min_duration_sec : 3;
    const max = q ? q.max_duration_sec : 10;
    const candidates = [3, 5, 10, 15, 30].filter((v) => v >= min && v <= max);
    const options = candidates.length ? candidates : [min];
    options.forEach((v, idx) => renderPill(durationPills, 'duration', v, `${v}s`, idx === 0));
  }

  function setQualityDuration(quality, duration) {
    if (quality) {
      const qualityInput = qualityPills.querySelector(`input[name="quality"][value="${quality}"]`);
      if (qualityInput) qualityInput.checked = true;
    }
    renderDurationPills();
    if (duration) {
      const durationInput = durationPills.querySelector(`input[name="duration"][value="${duration}"]`);
      if (durationInput) durationInput.checked = true;
    }
  }

  function syncModeRequirements() {
    const isVideoMode = modeSelect.value === 'video';
    if (videoFileInput) {
      videoFileInput.required = isVideoMode;
    }
    if (videoModeHint) {
      videoModeHint.textContent = isVideoMode
        ? '当前为视频生成模式：请上传 MP4 参考视频。'
        : '文本生成模式：参考视频可选。';
    }
  }

  async function bootstrapCatalogs() {
    try {
      const [versionsRes, functionsRes] = await Promise.all([
        fetch('/api/v1/versions'),
        fetch('/api/v1/functions'),
      ]);
      if (versionsRes.ok) {
        const versions = await versionsRes.json();
        catalog.qualities = Array.isArray(versions.qualities) ? versions.qualities : [];
        catalog.providers = Array.isArray(versions.providers) ? versions.providers : [];
        if (catalog.providers.length) {
          providerSelect.innerHTML = '';
          catalog.providers.forEach((p, idx) => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.label;
            opt.selected = idx === 0;
            providerSelect.appendChild(opt);
          });
        }
      }
      if (functionsRes.ok) {
        const data = await functionsRes.json();
        const items = Array.isArray(data.items) ? data.items : [];
        const disabled = items.some((fn) => fn.id === 'video' && !fn.enabled);
        if (disabled) {
          alertBoxShow('视频功能当前未开放，请联系管理员。', 'error');
          submitBtn.disabled = true;
          submitBtn.textContent = '视频功能未开放';
        }
      }
    } catch {
      /* 目录加载失败时保留静态默认值 */
    }
    renderQualityPills();
    renderDurationPills();
  }

  /* ---------- 竞品洞察 / 模板 ---------- */
  function renderInsights(payload) {
    if (!insights || !insightSourceList || !insightPatternList || !insightTemplateList) return;

    const sources = Array.isArray(payload.sources) ? payload.sources : [];
    const designPatterns = payload.design_patterns || {};
    const templates = Array.isArray(payload.prompt_templates) ? payload.prompt_templates : [];

    insightSourceList.innerHTML = '';
    sources.slice(0, 6).forEach((item) => {
      const node = document.createElement('div');
      node.className = 'insight-item';
      node.innerHTML = `
        <div class="title">${esc(item.product || '')}</div>
        <div class="meta">${esc(item.vendor || '')} · ${esc(item.website || '')}</div>
        <div class="desc">${esc(item.highlight || item.positioning || '')}</div>
      `;
      insightSourceList.appendChild(node);
    });

    const patternItems = [
      ...(Array.isArray(designPatterns.homepage_eight_modules) ? designPatterns.homepage_eight_modules.slice(0, 4) : []),
      ...(Array.isArray(designPatterns.low_barrier_triplet) ? designPatterns.low_barrier_triplet.slice(0, 2) : []),
    ];
    insightPatternList.innerHTML = '';
    patternItems.forEach((text) => {
      const li = document.createElement('li');
      li.textContent = text;
      insightPatternList.appendChild(li);
    });

    insightTemplateList.innerHTML = '';
    templates.slice(0, 5).forEach((tpl) => {
      const card = document.createElement('article');
      card.className = 'template-card';
      card.innerHTML = `
        <div class="top">
          <span class="name">${esc(tpl.title || '未命名模板')}</span>
          <span class="rec">${esc(tpl.quality || '')} · ${esc(String(tpl.duration || ''))}s</span>
        </div>
        <div class="text">${esc(tpl.prompt || '')}</div>
      `;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-ghost';
      btn.textContent = '一键填充并应用参数';
      btn.addEventListener('click', () => {
        promptBox.value = tpl.prompt || '';
        setQualityDuration(tpl.quality, tpl.duration);
        modeSelect.value = 'text';
        syncModeRequirements();
        window.scrollTo({ top: 0, behavior: 'smooth' });
        promptBox.focus();
      });
      card.appendChild(btn);
      insightTemplateList.appendChild(card);
    });

    insights.hidden = sources.length === 0 && templates.length === 0;
  }

  async function loadInsights() {
    try {
      const res = await fetch('/api/v1/insights/short-video-sites');
      if (!res.ok) return;
      const data = await res.json();
      renderInsights(data);
    } catch {
      /* 洞察数据加载失败时不影响核心生成功能 */
    }
  }

  /* ---------- 步骤条 ---------- */
  function setSteps(activeKey, failed) {
    const order = ['queued', 'running', 'completed'];
    stepsBox.querySelectorAll('.step').forEach((el) => {
      const key = el.dataset.step;
      const idx = order.indexOf(key);
      const activeIdx = order.indexOf(activeKey);
      el.classList.toggle('active', key === activeKey && !failed && key !== 'completed');
      el.classList.toggle('done', idx < activeIdx || (key === 'completed' && activeKey === 'completed'));
      el.classList.toggle('failed', failed && key === 'completed');
    });
  }

  function alertBoxShow(msg, kind) {
    alertBox.className = 'alert ' + kind;
    alertBox.textContent = msg;
  }
  function alertBoxHide() { alertBox.className = 'alert'; alertBox.textContent = ''; }

  function showResultHtml(html) {
    resultHolder.innerHTML = html;
  }

  function renderTaskDetail(payload, titlePrefix) {
    const segments = Array.isArray(payload.segments) ? payload.segments.map((s) => s.text).filter(Boolean) : [];
    const html = `
      <div style="width:100%">
        <div style="color:var(--muted);font-size:.86rem;line-height:1.7">
          ${titlePrefix || ''}
          任务 <code>${esc(payload.task_id)}</code><br />
          ${esc(payload.quality || '')} / ${esc(String(payload.duration ?? ''))}s · 引擎 ${esc(payload.provider || '')}
          ${segments.length ? `<br />分段：${segments.map(esc).join(' / ')}` : ''}
        </div>
      </div>`;
    showResultHtml(html);
  }

  /* ---------- 账单明细卡 ---------- */
  function renderBill(payload) {
    const usage = payload.usage || {};
    const rows = [
      ['预计消耗', fmtNum(payload.estimate_credits) + ' 积分'],
      ['本次消耗', fmtNum(usage.credits_used) + ' 积分'],
      ['本月额度', fmtNum(usage.monthly_quota) + ' 积分'],
      ['剩余额度', `${fmtNum(usage.credits_remaining)}（${usage.remaining_percent ?? 0}%）`],
    ];
    billKvs.innerHTML = rows.map(([k, v]) => `<span>${k}</span><span><strong>${esc(v)}</strong></span>`).join('');
    billCard.style.display = 'block';
  }

  /* ---------- 下载 ---------- */
  async function triggerDownload(taskId) {
    try {
      const res = await fetch(`/api/v1/tasks/${taskId}/download`);
      const data = await res.json();
      if (res.ok) {
        const url = data.cdn_url || data.local_fallback_url;
        if (url) {
          const a = document.createElement('a');
          a.href = url;
          a.download = `${taskId}.mp4`;
          a.target = '_blank';
          a.rel = 'noopener';
          document.body.appendChild(a);
          a.click();
          a.remove();
          return;
        }
      }
      alertBoxShow('暂无可用下载地址，请稍后重试。', 'error');
    } catch (err) {
      alertBoxShow(`下载失败：${err.message}`, 'error');
    }
  }

  /* ---------- 结果区渲染（含视频与下载按钮） ---------- */
  function renderCompleted(payload) {
    const taskId = payload.task_id;
    const videoHtml = payload.video_url
      ? `<video id="video-output" controls playsinline src="${esc(payload.video_url)}" style="width:100%;border-radius:14px;background:#000"></video>`
      : `<p class="empty-hint">任务已完成，但未找到视频文件。</p>`;
    showResultHtml(videoHtml + `
      <div style="display:flex;gap:10px;margin-top:12px">
        <button class="btn-ghost" id="dl-btn" type="button">下载视频</button>
      </div>`);
    const dlBtn = document.getElementById('dl-btn');
    if (dlBtn) dlBtn.addEventListener('click', () => triggerDownload(taskId));
    alertBoxShow('生成完成，可播放或下载。', 'ok');
  }

  /* ---------- 轮询 ---------- */
  async function pollTask(taskId, startedAt) {
    const elapsed = (Date.now() - startedAt) / 1000;
    const nextInterval = elapsed <= 10 ? 2000 : 5000;
    try {
      const res = await fetch(`/api/v1/tasks/${taskId}`);
      const payload = await res.json();
      if (!res.ok) throw new Error(payload.detail?.message || payload.message || '查询任务状态失败');

      const status = payload.status;
      if (status === 'completed') {
        clearActivePoll();
        setSteps('completed', false);
        renderBill(payload);
        renderCompleted(payload);
        loadGallery();
        return;
      }
      if (status === 'failed' || status === 'canceled') {
        clearActivePoll();
        setSteps('completed', true);
        alertBoxShow(`生成失败：${payload.error || STATUS_CN[status] || status}`, 'error');
        loadGallery();
        return;
      }
      setSteps(status === 'queued' ? 'queued' : 'running', false);
      renderTaskDetail(payload, `任务状态：<strong>${esc(STATUS_CN[status] || status)}</strong><br />`);
      activePollTimer = window.setTimeout(() => pollTask(taskId, startedAt), nextInterval);
    } catch (err) {
      clearActivePoll();
      alertBoxShow(`生成失败：${err.message}`, 'error');
    }
  }

  /* ---------- 提交 ---------- */
  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    const promptValue = (promptBox.value || '').trim();
    const isVideoMode = modeSelect.value === 'video';
    const hasVideoFile = Boolean(videoFileInput && videoFileInput.files && videoFileInput.files.length > 0);

    if (!promptValue) {
      alertBoxShow('请输入提示词后再提交。', 'error');
      promptBox.focus();
      return;
    }
    if (isVideoMode && !hasVideoFile) {
      alertBoxShow('视频生成模式需要上传一段 MP4 参考视频。', 'error');
      if (videoFileInput) videoFileInput.focus();
      return;
    }

    clearActivePoll();

    submitBtn.disabled = true;
    submitBtn.textContent = '提交中…';
    alertBoxHide();
    billCard.style.display = 'none';
    setSteps('queued', false);
    showResultHtml('<p class="empty-hint">任务已提交，正在排队……</p>');

    try {
      const res = await fetch('/api/v1/tasks', { method: 'POST', body: new FormData(form) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail?.message || data.detail || data.message || '创建任务失败');

      showResultHtml(`<p class="empty-hint">任务已创建，ID：<code>${esc(data.task_id)}</code><br />正在轮询状态…</p>`);
      renderBill(data);
      await pollTask(data.task_id, Date.now());
    } catch (err) {
      setSteps('completed', true);
      alertBoxShow(`生成失败：${err.message}`, 'error');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = '生成视频';
    }
  });

  /* ---------- 最近任务画廊 ---------- */
  function taskPromptText(task) {
    const segments = Array.isArray(task.segments) ? task.segments.map((s) => s.text).filter(Boolean) : [];
    return segments.join(' / ') || '（无提示词记录）';
  }

  function cardButton(text, cls, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-ghost' + (cls ? ' ' + cls : '');
    btn.textContent = text;
    btn.addEventListener('click', onClick);
    return btn;
  }

  function fillFormFromTask(task) {
    promptBox.value = taskPromptText(task);
    setQualityDuration(task.quality, task.duration);
    modeSelect.value = task.mode || 'text';
    syncModeRequirements();
    providerSelect.value = task.provider || 'local';
    audioCheck.checked = Boolean(task.with_audio);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    promptBox.focus();
  }

  function watchTaskInResult(task) {
    if (!task.task_id) return;
    clearActivePoll();
    window.scrollTo({ top: resultHolder.getBoundingClientRect().top + window.scrollY - 24, behavior: 'smooth' });
    renderTaskDetail(task, '正在载入任务……<br />');
    pollTask(task.task_id, Date.now());
  }

  function renderGallery(items) {
    const visibleItems = items.filter((task) => !task.is_deleted);
    gallery.hidden = visibleItems.length === 0;
    galleryGrid.innerHTML = '';
    visibleItems.forEach((task) => {
      const card = document.createElement('div');
      card.className = 'g-card';

      const top = document.createElement('div');
      top.className = 'g-top';
      const badge = document.createElement('span');
      badge.className = 'badge ' + (task.status || 'queued');
      badge.textContent = STATUS_CN[task.status] || task.status;
      top.appendChild(badge);
      const time = document.createElement('span');
      time.className = 'g-meta';
      time.textContent = fmtTime(task.created_at);
      top.appendChild(time);
      card.appendChild(top);

      const meta = document.createElement('div');
      meta.className = 'g-meta';
      meta.textContent = `${task.quality || ''} / ${task.duration || ''}s · ${task.provider || ''}`;
      card.appendChild(meta);

      const prompt = document.createElement('div');
      prompt.className = 'g-prompt';
      prompt.textContent = taskPromptText(task);
      card.appendChild(prompt);

      const actions = document.createElement('div');
      actions.className = 'g-actions';
      if (task.status === 'completed') {
        if (task.video_url) {
          actions.appendChild(cardButton('播放', '', () => watchTaskInResult(task)));
        }
        actions.appendChild(cardButton('下载', '', () => triggerDownload(task.task_id)));
        actions.appendChild(cardButton('复用提示词', '', () => fillFormFromTask(task)));
      } else if (task.status === 'failed' || task.status === 'canceled') {
        actions.appendChild(cardButton('复用提示词', '', () => fillFormFromTask(task)));
      } else {
        actions.appendChild(cardButton('查看进度', '', () => watchTaskInResult(task)));
      }
      actions.appendChild(cardButton('删除', 'btn-danger', async () => {
        if (!window.confirm('删除该任务记录？（软删除，可在垃圾桶找回）')) return;
        try {
          await fetch(`/api/v1/tasks/${task.task_id}`, { method: 'DELETE' });
        } catch { /* 忽略 */ }
        loadGallery();
      }));
      card.appendChild(actions);

      galleryGrid.appendChild(card);
    });
  }

  async function loadGallery() {
    try {
      const res = await fetch('/api/v1/tasks');
      if (!res.ok) return;
      const data = await res.json();
      const items = Array.isArray(data.items) ? data.items : [];
      items.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
      renderGallery(items.slice(0, 30));
    } catch { /* 画廊失败不打断主流程 */ }
  }

  /* ---------- 启动 ---------- */
  refreshHealth();
  renderChips();
  modeSelect.addEventListener('change', syncModeRequirements);
  syncModeRequirements();
  bootstrapCatalogs();
  loadInsights();
  loadGallery();
})();