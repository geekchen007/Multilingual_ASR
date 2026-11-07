const $ = (selector, root = document) => root.querySelector(selector);
const esc = (value) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
const csrf = $('meta[name="csrf-token"]').content;
const research = document.body.dataset.role === 'research';
const content = $('#content');
let config,
  currentTest,
  currentCases = [],
  pollTimer,
  recorder,
  recordingStream,
  recordedFile,
  inlineTestId;
let routeVersion = 0;
let modelPickerBound = false;
const statusNames = {
  awaiting_audio: '待补充音频',
  queued: '排队中',
  running: '识别中',
  completed: '已完成',
  partial: '部分完成',
  failed: '失败',
};
const timeText = (value) => new Date(value).toLocaleString('zh-CN', { hour12: false });
const options = (items, selected = '') =>
  items
    .map(
      (item) =>
        `<option value="${esc(item)}" ${item === selected ? 'selected' : ''}>${esc(item)}</option>`,
    )
    .join('');
const languages = (all = false) =>
  (all ? '<option value="">全部语种</option>' : '') +
  Object.entries(config.languages)
    .map(([key, value]) => `<option value="${key}">${esc(value)}</option>`)
    .join('');
const badge = (status) =>
  `<span class="pill ${status === 'completed' || status === '已解决' ? 'success' : status === 'awaiting_audio' || status === '待复核' ? 'warning' : status === 'failed' ? 'failure' : ''}">${esc(statusNames[status] || status)}</span>`;
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.add('visible');
  setTimeout(() => $('#toast').classList.remove('visible'), 5000);
}
async function api(url, settings = {}) {
  const headers = { 'X-CSRF-Token': csrf, ...settings.headers };
  if (settings.body && !(settings.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    settings.body = JSON.stringify(settings.body);
  }
  const response = await fetch(url, { ...settings, headers });
  if (response.status === 401) {
    location.href = '/login';
    throw Error('请先登录');
  }
  const body = await response.json();
  if (!response.ok) throw Error(body.error || '操作未完成，请稍后重试');
  return body;
}
function head(title, description, action = '') {
  return `<div class="page-head"><div><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
}
function empty(title, description) {
  return `<div class="empty"><div class="orb">◎</div><h3>${title}</h3><p>${description}</p></div>`;
}
function modelChooser() {
  const defaults = new Set(
    config.models.slice(0, Math.min(2, config.models.length)).map((model) => model.id),
  );
  const choices = config.models
    .map((model) => {
      const name = `${esc(model.name)}${model.demo ? '（演示）' : ''}`;
      const checked = defaults.has(model.id) ? 'checked' : '';
      return `<label class="model-option"><input type="checkbox" name="models" form="test-form" value="${esc(model.id)}" data-name="${name}" ${checked}><span>${name}</span></label>`;
    })
    .join('');
  return `<div class="model-picker" id="model-picker"><span class="model-picker-label" id="model-picker-label">ASR 模型</span><button type="button" class="model-picker-toggle" aria-haspopup="listbox" aria-expanded="false" aria-labelledby="model-picker-label"><span class="model-picker-summary">请选择模型</span><span class="model-picker-caret" aria-hidden="true"></span></button><div class="model-picker-menu" role="group" aria-label="选择 ASR 模型" hidden>${choices}<p class="model-picker-hint">最多选择 3 个，开始测评后同时送测。</p></div></div>`;
}

function bindModelPicker() {
  const picker = $('#model-picker');
  if (!picker || typeof picker.querySelectorAll !== 'function') return;
  const toggle = picker.querySelector('.model-picker-toggle');
  const menu = picker.querySelector('.model-picker-menu');
  const summary = picker.querySelector('.model-picker-summary');
  const boxes = () => [...picker.querySelectorAll('.model-option input')];
  const refresh = () => {
    const chosen = boxes().filter((box) => box.checked);
    boxes().forEach((box) => {
      box.disabled = !box.checked && chosen.length >= 3;
    });
    summary.textContent = chosen.length
      ? chosen.map((box) => box.dataset.name).join('、')
      : '请选择模型';
    toggle.setAttribute('aria-expanded', menu.hidden ? 'false' : 'true');
  };
  toggle.onclick = () => {
    menu.hidden = !menu.hidden;
    refresh();
  };
  menu.onchange = refresh;
  if (!modelPickerBound && typeof document.addEventListener === 'function') {
    modelPickerBound = true;
    document.addEventListener('click', (event) => {
      const current = $('#model-picker');
      if (!current || current.contains(event.target)) return;
      const openMenu = current.querySelector('.model-picker-menu');
      const openToggle = current.querySelector('.model-picker-toggle');
      if (openMenu) openMenu.hidden = true;
      if (openToggle) openToggle.setAttribute('aria-expanded', 'false');
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const current = $('#model-picker');
      if (!current) return;
      const openMenu = current.querySelector('.model-picker-menu');
      const openToggle = current.querySelector('.model-picker-toggle');
      if (!openMenu || openMenu.hidden) return;
      openMenu.hidden = true;
      openToggle.setAttribute('aria-expanded', 'false');
      openToggle.focus();
    });
  }
  refresh();
}

function sampleInfo(sample) {
  return `<p class="sample-attribution"><a href="${esc(sample.source_url)}" target="_blank" rel="noopener noreferrer">${esc(sample.dataset)} ↗</a> · <a href="${esc(sample.license_url)}" target="_blank" rel="noopener noreferrer">${esc(sample.license)}</a><br>${esc(sample.attribution)}</p><details class="sample-reference"><summary>查看数据集原始参考文本</summary><p lang="${esc(sample.language)}" dir="auto">${esc(sample.reference)}</p><small class="muted">原始全文仅供对照；若截取片段，请按实际音频判断。</small></details>`;
}

function testPage() {
  recordedFile = null;
  content.innerHTML = `
    <header class="test-intro">
      <div><span class="eyebrow">WORLD VOICE LAB / 多语言语音实验室</span><h1>在线测评</h1><p>选择音频与语言，对比模型的理解，留下值得改进的细节。</p></div>
      <div class="intro-greetings" aria-label="不同语言的问候"><span lang="zh">你好</span><span lang="en">Hello</span><span lang="ar" dir="rtl">مرحبًا</span><small>不同语言，同样用心。</small></div>
    </header>
    <div class="run-toolbar" role="group" aria-label="模型选择与开始测评">
      <div class="run-models">${modelChooser()}</div>
      <div class="run-actions"><button class="primary" id="submit-test" type="submit" form="test-form">开始测评 <svg aria-hidden="true"><use href="/static/icons.svg#arrow"/></svg></button><button type="button" id="view-results" class="hidden">查看本轮结果</button></div>
      <p id="test-feedback" class="test-feedback" role="status" aria-live="polite">可多选 1—3 个模型。所选模型接收同一段音频，识别结果在本页并排展示。</p>
    </div>
    <div class="workbench-layout">
    <form id="test-form" class="evaluation-form">
      <div class="evaluation-grid">
        <section class="card audio-card" aria-labelledby="audio-heading">
          <div class="audio-context"><div><h2 id="audio-heading">准备测试音频</h2><p class="small muted">公开示例或自己的音频 · 最长 120 秒</p></div><label class="language-field">识别语言<select name="language" aria-describedby="language-help">${languages()}</select></label></div>
          <p class="language-help" id="language-help">不确定语种时使用自动识别；混说音频可选择对应的混合语种。</p>
          <div class="tabs"><button type="button" class="active" data-source="sample">公开示例</button><button type="button" data-source="file">上传文件</button><button type="button" data-source="record">麦克风录音</button><button type="button" data-source="link">视频链接</button></div>
          <div id="source-sample"><p class="sample-intro">公开数据集真实录音，无需上传。</p><label class="sample-selector">示例录音<select name="sample_id" id="sample-select">${config.samples.map((sample) => `<option value="${esc(sample.id)}">${esc(sample.title)} · ${sample.duration.toFixed(1)} 秒</option>`).join('')}</select></label><audio id="sample-player" controls preload="none" aria-label="公开示例试听"></audio><details class="sample-source"><summary>数据来源与参考文本</summary><div id="sample-meta"></div></details></div>
          <div id="source-file" class="hidden"><label class="upload"><span class="upload-icon"><svg aria-hidden="true"><use href="/static/icons.svg#upload"/></svg></span><b>选择一段音频或视频</b><input id="file-input" name="file" type="file" accept="audio/*,video/*"><small>WAV / MP3 / M4A / WebM / MP4 · 最大 100 MB</small></label></div>
          <div id="source-record" class="hidden"><div class="record-state"><b id="record-label">准备录音</b><p>使用电脑麦克风，停止后可试听并提交。</p><button type="button" id="record-button">● 开始录音</button></div><audio id="record-preview" controls class="hidden"></audio></div>
          <div id="source-link" class="hidden"><label>视频链接<input name="url" type="url" placeholder="粘贴 B 站 / YouTube 链接"></label><p class="inset small">保存视频来源与选段，并补传有权使用的同源音视频文件。也可以先保存链接，稍后补传。</p><label>同源音视频文件（可稍后补传）<input id="link-file" type="file" accept="audio/*,video/*"></label></div>
          <details class="optional-settings clip-options"><summary>截取音频片段 <span>可选 · 默认从开头识别</span></summary><div class="grid two"><label>开始时间（秒）<input name="start" type="number" min="0" step="0.1" value="0"></label><label>结束时间（秒）<input name="end" type="number" min="0" step="0.1" placeholder="留空取最多 120 秒"></label></div><p class="small muted">视频链接的时间范围对应原视频；上传文件的时间范围对应原文件。</p></details>
        </section>
        <section class="card settings-card" aria-labelledby="settings-heading">
          <div class="card-title"><div><h2 id="settings-heading">测评设置</h2></div><a href="#history">测试历史 ↗</a></div>
          <label class="check blind-option"><input type="checkbox" name="blind" value="1" checked><span>盲测模式，投票后揭晓模型${research ? '<small class="muted">研发账号始终可见模型身份</small>' : ''}</span></label>
          <details class="optional-settings"><summary>补充测试信息 <span>可选</span></summary><label>测试名称<input name="title" maxlength="160" placeholder="例如：一段马英混说"></label><label>使用场景<select name="scene">${options(config.scenes)}</select></label></details>
          <p class="small muted privacy-note">音频将发送给顶部选中的模型服务；演示模型仅返回固定示例。</p>
        </section>
      </div>
    </form>
    <section id="inline-results" class="inline-results" aria-label="本轮测评结果" tabindex="-1"><div class="result-placeholder"><svg aria-hidden="true"><use href="/static/icons.svg#wave"/></svg><h2>识别结果</h2><p>选择音频和模型，点击“开始测评”。<br>识别进度、转写和反馈都在这里完成。</p></div></section>
    </div>
    <details class="inspiration-drawer">
      <summary><span><span class="eyebrow">VOICES OF EVERYDAY LIFE</span><b>寻找测试灵感</b><span class="inspiration-caption">从一句日常，探索不同语言的表达。</span></span><span class="inspiration-toggle">展开 / 收起</span></summary>
      <div class="discovery-column">
        <section class="card phrase-card"><h2>一句日常，也有万千表达。</h2><p class="muted small">试试身边真实的语言场景，听听模型如何理解。</p>
          <div class="phrase phrase-malay"><div><span class="language-code">MS + EN</span><span>马英混说 · 日常安排</span></div><p lang="ms">Tolong book meeting room<br>pukul tiga.</p><small>请帮忙预订三点的会议室。</small></div>
          <div class="phrase phrase-japanese"><div><span class="language-code">JA</span><span>日语 · 城市出行</span></div><p lang="ja">次の駅は、渋谷です。</p><small>下一站是涩谷。</small></div>
          <div class="phrase phrase-arabic"><div><span class="language-code">AR</span><span>阿拉伯语 · 朋友问候</span></div><p lang="ar" dir="rtl">صباح الخير، كيف حالك؟</p><small>早上好，你怎么样？</small></div>
          <p class="phrase-disclaimer">以上为测评灵感示例，不代表模型识别结果。</p>
        </section>
        <section class="card guide-card"><span class="eyebrow">FROM VOICE TO INSIGHT</span><h2>让一次聆听，留下价值。</h2><ol class="guide-steps"><li><b>带来一段真实声音</b><p>口音、地名、数字，或自然的混语。</p></li><li><b>对比模型的理解</b><p>试听原音，判断哪份转写更准确。</p></li><li><b>标记值得改进的地方</b><p>把具体问题沉淀为可复现的 Case。</p></li></ol><a href="#cases">探索 Case 库 <span aria-hidden="true">→</span></a></section>
      </div>
    </details>`;
  let source = 'sample';
  function selectSample() {
    const form = $('#test-form');
    const sample = config.samples.find(
      (row) => row.id === form.elements.sample_id.value,
    );
    form.elements.language.value = sample.language;
    form.elements.start.value = '0';
    form.elements.end.value = '';
    $('#sample-player').src =
      '/api/samples/' + encodeURIComponent(sample.id) + '/audio';
    $('#sample-meta').innerHTML = sampleInfo(sample);
  }
  document
    .querySelectorAll('[name="sample_id"]')
    .forEach((input) => (input.onchange = selectSample));
  selectSample();
  bindModelPicker();
  $('#view-results').onclick = () => {
    const target = $('#inline-results');
    target.scrollIntoView({
      block: 'start',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'auto'
        : 'smooth',
    });
    target.focus({ preventScroll: true });
  };
  document.querySelectorAll('[data-source]').forEach(
    (button) =>
      (button.onclick = () => {
        if (recorder?.state === 'recording') {
          toast('请先停止录音');
          return;
        }
        $('#sample-player').pause();
        source = button.dataset.source;
        if (source === 'sample') selectSample();
        document
          .querySelectorAll('[data-source]')
          .forEach((b) => b.classList.toggle('active', b === button));
        ['sample', 'file', 'record', 'link'].forEach((name) =>
          $('#source-' + name).classList.toggle('hidden', name !== source),
        );
      }),
  );
  $('#record-button').onclick = async () => {
    if (recorder?.state === 'recording') {
      recorder.stop();
      return;
    }
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
        throw Error('当前浏览器无法录音，请使用 localhost 或 HTTPS 下的 Chrome / Edge');
      recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(recordingStream);
      const chunks = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        recordedFile = new File(chunks, 'recording.webm', { type: recorder.mimeType });
        const preview = $('#record-preview');
        if (preview) {
          if (preview.src) URL.revokeObjectURL(preview.src);
          preview.src = URL.createObjectURL(recordedFile);
          preview.classList.remove('hidden');
          $('#record-label').textContent = '录音已就绪';
          $('#record-button').textContent = '重新录音';
        }
        recordingStream.getTracks().forEach((track) => track.stop());
      };
      recorder.start();
      $('#record-label').textContent = '正在录音…';
      $('#record-button').textContent = '■ 停止录音';
      const activeRecorder = recorder;
      setTimeout(() => {
        if (activeRecorder.state === 'recording') activeRecorder.stop();
      }, 120000);
    } catch (error) {
      toast(error.message);
    }
  };
  $('#test-form').onsubmit = async (event) => {
    event.preventDefault();
    const form = event.target;
    const button = $('#submit-test');
    if (recorder?.state === 'recording') {
      toast('请先停止录音并试听');
      return;
    }
    const data = new FormData(form);
    data.delete('file');
    const selectedModels = data.getAll('models').filter(Boolean);
    if (!selectedModels.length) {
      toast('请至少选择一个 ASR 模型');
      return;
    }
    if (
      new Set(selectedModels).size !== selectedModels.length ||
      selectedModels.length > 3
    ) {
      toast('请选择 1—3 个不同的 ASR 模型');
      return;
    }
    data.delete('models');
    selectedModels.forEach((model) => data.append('models', model));
    if (source !== 'link') data.delete('url');
    if (source !== 'sample') data.delete('sample_id');
    const file =
      source === 'record'
        ? recordedFile
        : source === 'link'
          ? $('#link-file').files[0]
          : source === 'file'
            ? $('#file-input').files[0]
            : null;
    if (file) data.set('file', file);
    if (!file && source !== 'link' && source !== 'sample') {
      toast('请先上传文件或完成录音');
      return;
    }
    const version = routeVersion;
    button.disabled = true;
    button.textContent = '正在准备音频…';
    $('#test-feedback').textContent = '正在准备音频，结果将在本页结果区展示。';
    try {
      const result = await api('/api/tests', { method: 'POST', body: data });
      if (version !== routeVersion) return;
      await showInlineResult(result.id);
    } catch (error) {
      if (version !== routeVersion) return;
      toast(error.message);
      button.disabled = false;
      button.textContent = '开始测评';
      $('#test-feedback').textContent = '提交失败，请检查设置后重试。';
    }
  };
}

async function showInlineResult(id) {
  const target = $('#inline-results');
  if (!target) return;
  const version = routeVersion;
  inlineTestId = id;
  clearTimeout(pollTimer);
  target.classList.remove('hidden');
  target.setAttribute('aria-busy', 'true');
  target.innerHTML =
    '<div class="card"><h2>本轮识别结果</h2><p class="muted">测试已创建，正在读取识别进度…</p></div>';
  $('#view-results').classList.remove('hidden');
  $('#submit-test').disabled = true;
  $('#submit-test').textContent = '正在识别…';
  $('#test-feedback').textContent = '正在识别，进度与结果将在本页结果区更新。';
  try {
    await detailPage(id, true);
  } catch (error) {
    if (version !== routeVersion || inlineTestId !== id) return;
    target.setAttribute('aria-busy', 'false');
    target.innerHTML = `<div class="card"><h2>测试已创建，结果暂时无法读取</h2><p class="muted">${esc(error.message)}</p><button id="retry-inline" type="button">重试读取结果</button> <a href="#history">查看测试历史</a></div>`;
    $('#retry-inline').onclick = () => showInlineResult(id);
    $('#submit-test').disabled = false;
    $('#submit-test').textContent = '开始测评';
    $('#test-feedback').textContent =
      '测试已保存。可在结果区重试读取结果，无需再次提交。';
  }
}

async function historyPage() {
  const version = routeVersion;
  content.innerHTML =
    head(
      '测试历史',
      '每次测试的音频、模型输出与反馈都保存在这里。',
      '<a class="primary button" href="#test">＋ 新建测试</a>',
    ) +
    `<section class="card"><form class="toolbar" id="history-filter"><input name="q" placeholder="搜索名称 / 测试 ID" aria-label="搜索测试"><select name="language" aria-label="语言筛选">${languages(true)}</select><select name="status" aria-label="状态筛选"><option value="">全部状态</option>${Object.entries(
      statusNames,
    )
      .map(([k, v]) => `<option value="${k}">${v}</option>`)
      .join(
        '',
      )}</select><button>筛选</button></form><div id="history-list"></div></section>`;
  async function load() {
    const rows = await api(
      '/api/tests?' + new URLSearchParams(new FormData($('#history-filter'))),
    );
    if (version !== routeVersion) return;
    $('#history-list').innerHTML = rows.length
      ? `<div class="table-wrap"><table><thead><tr><th>测试 / 来源</th><th>语言</th><th>状态</th><th>标注</th><th>时间</th><th></th></tr></thead><tbody>${rows.map((row) => `<tr class="clickable" data-test="${row.id}"><td><strong>${esc(row.title)}</strong><small>${row.sample_id ? '公开示例' : row.url ? '视频链接' : '录音 / 文件'} · ${esc(row.id)}${research ? ' · ' + esc(row.username) : ''}</small>${row.demo ? '<span class="tag warning">演示</span>' : ''}</td><td>${esc(config.languages[row.language])}</td><td>${badge(row.status)}</td><td>${row.annotations} 条</td><td>${timeText(row.created)}</td><td><a href="#detail/${row.id}">查看 →</a></td></tr>`).join('')}</tbody></table></div>`
      : empty('还没有测试记录', '开始第一次测评，记录会自动出现在这里。');
    document
      .querySelectorAll('[data-test]')
      .forEach(
        (row) => (row.onclick = () => (location.hash = 'detail/' + row.dataset.test)),
      );
  }
  $('#history-filter').onsubmit = (event) => {
    event.preventDefault();
    load().catch((e) => toast(e.message));
  };
  await load();
}

async function detailPage(id, inline = false) {
  const version = routeVersion;
  if (inline && inlineTestId !== id) return;
  const item = await api('/api/tests/' + id);
  if (version !== routeVersion || (inline && inlineTestId !== id)) return;
  const target = inline ? $('#inline-results') : content;
  if (!target) return;
  currentTest = item;
  const running = ['queued', 'running'].includes(item.status);
  const heading = inline
    ? `<div class="inline-result-head"><div><h2>本轮识别结果</h2><p>${esc(item.title)} · ${esc(config.languages[item.language])} · ${badge(item.status)}</p></div><a href="#history">已保存到测试历史 ↗</a></div>`
    : `<a class="back" href="#history">← 测试历史</a>` +
      head(
        esc(item.title),
        `${esc(config.languages[item.language])} · ${esc(item.scene)} · ${timeText(item.created)}`,
        badge(item.status),
      );
  target.innerHTML =
    heading +
    `<section class="card"><div class="row spread"><h2>测试片段</h2><button id="rerun" ${!item.duration || running ? 'disabled' : ''}>↻ 使用当前模型重测</button></div>${inline ? '<details class="audio-details"><summary>音频与来源信息</summary>' : ''}<div class="details-meta"><span>ID ${item.id}</span><span>原文件起点 ${item.start} 秒</span><span>片段时长 ${item.duration.toFixed(2)} 秒</span>${item.parent_id ? `<a href="#detail/${item.parent_id}">查看上次测试 →</a>` : ''}</div>${item.url ? `<p class="small source-url">来源 <a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.url)}</a></p>` : ''}${item.sample ? `<div class="sample-origin"><span class="tag">公开数据集示例 · ${esc(item.sample.title)}</span>${sampleInfo(item.sample)}</div>` : ''}${inline ? `<p class="small source-url">SHA-256 ${item.sha256 || '待补充音频'}</p></details>` : ''}${item.duration ? `<audio id="test-audio" controls src="/api/tests/${id}/audio"></audio>${!inline ? `<details><summary>音频 SHA-256</summary><p class="small source-url">${item.sha256}</p></details>` : ''}` : `<div class="inset"><p>链接已保存，请补传同源音视频文件后测试。</p><form id="attach-form" class="row"><input type="file" name="file" accept="audio/*,video/*" required aria-label="补传音视频"><button class="primary">补充音频</button></form></div>`}</section><div class="section-space row spread"><h2>识别结果</h2><span class="muted small">${item.revealed ? '模型身份已显示' : '盲测中 · 投票后揭晓'}</span></div><div class="result-grid">${item.results.map((result) => `<article class="result"><div class="row spread"><h3>结果 ${result.label}</h3>${badge(result.status)}</div>${result.demo ? '<span class="tag warning">演示输出 · 固定示例</span>' : ''}<small>${item.revealed ? esc(result.provider) : '模型身份隐藏'}</small><div class="transcript" data-result="${result.id}">${esc(result.text || result.error || '正在等待模型返回…')}</div><small>调用耗时 ${result.elapsed.toFixed(2)} 秒</small><button class="annotate" data-result-id="${result.id}" ${!item.duration ? 'disabled' : ''}>标记问题</button>${item.revealed ? `<details><summary>模型配置快照</summary><pre class="small">${esc(JSON.stringify(result.snapshot, null, 2))}</pre></details>` : ''}</article>`).join('')}</div>${
      !running && item.status !== 'awaiting_audio'
        ? `<section class="card section-space"><h3>哪份结果更接近你听到的内容？</h3><div class="vote">${item.results
            .filter((r) => r.status === 'completed')
            .map(
              (r) =>
                `<button data-choice="${r.label}" class="${item.vote === r.label ? 'selected' : ''}">结果 ${r.label} 更准</button>`,
            )
            .join('')}${[
            ['both_good', '都准确'],
            ['both_bad', '都有问题'],
            ['skip', '听不清，跳过'],
          ]
            .map(
              ([value, label]) =>
                `<button data-choice="${value}" class="${item.vote === value ? 'selected' : ''}">${label}</button>`,
            )
            .join(
              '',
            )}</div><p class="small muted">可以先完成投票，再标记具体错误。${item.vote ? '本轮投票已保存。' : ''}</p></section>`
        : ''
    }${inline ? '<details class="card section-space annotation-history"><summary>本轮问题标注</summary>' : '<section class="card section-space">'}<div class="row spread">${inline ? '' : '<h2>本轮问题标注</h2>'}<button id="annotate-general" ${!item.duration ? 'disabled' : ''}>＋ 标记问题</button></div><div id="detail-cases"></div>${inline ? '</details>' : '</section>'}`;
  if (inline) {
    target.setAttribute('aria-busy', String(running));
    $('#submit-test').disabled = running;
    $('#submit-test').textContent = running ? '正在识别…' : '开始测评';
    const completed = item.results.filter(
      (result) => result.status === 'completed',
    ).length;
    $('#test-feedback').textContent = running
      ? `识别中 · 已返回 ${completed}/${item.results.length} 个模型，结果在本页更新。`
      : item.status === 'awaiting_audio'
        ? '链接已保存，请在结果区补充同源音频。'
        : `${statusNames[item.status] || item.status} · 结果已更新，可调整设置继续测评。`;
  }
  $('#rerun').onclick = async () => {
    const version = routeVersion;
    const button = $('#rerun');
    button.disabled = true;
    try {
      const result = await api(`/api/tests/${id}/rerun`, { method: 'POST' });
      if (version !== routeVersion || (inline && inlineTestId !== id)) return;
      if (inline) await showInlineResult(result.id);
      else location.hash = 'detail/' + result.id;
    } catch (e) {
      toast(e.message);
      button.disabled = false;
    }
  };
  if ($('#attach-form'))
    $('#attach-form').onsubmit = async (event) => {
      event.preventDefault();
      const button = $('button', event.target);
      button.disabled = true;
      try {
        await api(`/api/tests/${id}/audio`, {
          method: 'POST',
          body: new FormData(event.target),
        });
        await detailPage(id, inline);
      } catch (e) {
        toast(e.message);
        button.disabled = false;
      }
    };
  document.querySelectorAll('[data-choice]').forEach(
    (button) =>
      (button.onclick = async () => {
        try {
          await api(`/api/tests/${id}/vote`, {
            method: 'POST',
            body: { choice: button.dataset.choice },
          });
          await detailPage(id, inline);
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  document
    .querySelectorAll('.annotate')
    .forEach(
      (button) => (button.onclick = () => openAnnotation(button.dataset.resultId)),
    );
  $('#annotate-general').onclick = () => openAnnotation('');
  const cases = (await api('/api/cases')).filter((row) => row.test_id === id);
  if (version !== routeVersion || (inline && inlineTestId !== id)) return;
  $('#detail-cases').innerHTML = cases.length
    ? cases
        .map(
          (row) =>
            `<div class="inset"><div class="row spread"><b>${row.types.map(esc).join(' / ')}</b>${badge(row.status)}</div><p class="small">${row.start}—${row.end} 秒 · ${esc(row.selected_text || '未填写识别原文')}</p><p class="small muted">用户修正 ${esc(row.reference || '待补充')}</p><a href="#cases">前往 Case 库 →</a></div>`,
        )
        .join('')
    : '<p class="muted small">选中结果中的文字，点击“标记问题”，也可以只反馈听到的异常。</p>';
  if (running) scheduleRefresh(id, version, inline);
}

function scheduleRefresh(id, version, inline = false) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    if (
      version !== routeVersion ||
      (inline ? inlineTestId !== id : location.hash !== '#detail/' + id)
    )
      return;
    const player = $('#test-audio');
    if (
      (player && !player.paused) ||
      document.querySelector('dialog[open]') ||
      String(window.getSelection()).length
    ) {
      scheduleRefresh(id, version, inline);
      return;
    }
    try {
      await detailPage(id, inline);
    } catch (e) {
      if (version !== routeVersion || (inline && inlineTestId !== id)) return;
      toast(e.message);
      scheduleRefresh(id, version, inline);
    }
  }, 1800);
}

function openAnnotation(resultId) {
  const form = $('#annotation-form');
  form.reset();
  $('#annotation-result').innerHTML =
    '<option value="">整个测试片段</option>' +
    currentTest.results
      .map(
        (result) =>
          `<option value="${result.id}" ${result.id === resultId ? 'selected' : ''}>结果 ${result.label}${currentTest.revealed ? ' · ' + esc(result.provider) : ''}</option>`,
      )
      .join('');
  form.elements.selected_text.value = String(window.getSelection() || '');
  form.elements.end.value = currentTest.duration.toFixed(2);
  $('#annotation').showModal();
}
$('#annotation-form').onsubmit = async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  data.types = new FormData(form).getAll('types');
  const id = currentTest.id,
    version = routeVersion,
    inline = inlineTestId === id;
  try {
    await api(`/api/tests/${id}/cases`, { method: 'POST', body: data });
    $('#annotation').close();
    if (version !== routeVersion || (inline && inlineTestId !== id)) return;
    toast('已保存到 Case 库');
    await detailPage(id, inline);
  } catch (e) {
    toast(e.message);
  }
};

async function casesPage() {
  const version = routeVersion;
  content.innerHTML =
    head(
      'Case 库',
      research
        ? '从真实反馈中复核问题，沉淀可复现的回归样本。'
        : '查看你的问题反馈和研发处理进度。',
      research ? '<a href="/api/regression" class="button">↓ 导出正式回归集</a>' : '',
    ) +
    `<section class="card"><form id="case-filter"><div class="toolbar"><input name="q" placeholder="搜索 Case / 文本 / 负责人" aria-label="搜索 Case"><select name="language" aria-label="语种">${languages(true)}</select><select name="type" aria-label="问题类型"><option value="">全部问题类型</option>${options(config.types)}</select><select name="status" aria-label="状态"><option value="">全部状态</option>${options(config.statuses)}</select></div><div class="toolbar"><select name="feature" aria-label="语言特征"><option value="">全部语言特征</option>${options(config.features)}</select><select name="impact" aria-label="影响程度"><option value="">全部影响程度</option>${options(config.impacts)}</select><button>筛选 Case</button></div></form><div id="case-list"></div></section>`;
  async function load() {
    const rows = await api(
      '/api/cases?' + new URLSearchParams(new FormData($('#case-filter'))),
    );
    if (version !== routeVersion) return;
    currentCases = rows;
    $('#case-list').innerHTML = currentCases.length
      ? currentCases
          .map(
            (row) =>
              `<article class="inset"><div class="row spread"><div><a href="#detail/${row.test_id}"><b>${esc(row.title)}</b></a> <small class="muted">#${row.id}</small></div>${badge(row.status)}</div><div class="details-meta"><span>${esc(config.languages[row.language])}</span><span>${row.start}—${row.end} 秒</span><span>${esc(row.feature)} / ${esc(row.condition)} / ${esc(row.impact)}</span><span>${esc(row.scene)}</span>${row.demo ? '<span class="tag warning">演示 Case</span>' : ''}${row.regression ? '<span class="tag success">回归集</span>' : ''}</div><div>${row.types.map((type) => `<span class="tag">${esc(type)}</span>`).join('')}</div><p>识别原文　${esc(row.selected_text || '未填写')}</p><p>用户修正　${esc(row.reference || '未填写')}</p>${row.note ? `<p class="small">说明　${esc(row.note)}</p>` : ''}${row.reference_reviewed ? `<p>研发参考　${esc(row.reference_reviewed)}</p>` : ''}<div class="row spread"><span class="muted small">${esc(row.owner || '待分派')} · ${esc(row.root_cause || '待定位')} ${row.duplicate_of ? ' · 主 Case ' + esc(row.duplicate_of) : ''}</span>${research ? `<button data-review="${row.id}">复核 / 更新状态</button>` : ''}</div>${row.events.length ? `<details><summary>${row.events.length} 条处理记录</summary>${row.events.map((event) => `<div class="audit">${timeText(event.created)} · ${esc(event.name)}<br>${esc(event.body)}</div>`).join('')}</details>` : ''}</article>`,
          )
          .join('')
      : empty('当前没有匹配的 Case', '测试结果中的每一条标注都会进入这里。');
    document.querySelectorAll('[data-review]').forEach(
      (button) =>
        (button.onclick = () => {
          const row = currentCases.find((item) => item.id === button.dataset.review);
          const form = $('#review-form');
          form.reset();
          [
            'id',
            'revision',
            'status',
            'owner',
            'root_cause',
            'reference_reviewed',
            'duplicate_of',
          ].forEach((key) => (form.elements[key].value = row[key]));
          form.elements.regression.checked = !!row.regression;
          $('#review-original').textContent =
            '用户反馈 · ' +
            row.types.join(' / ') +
            ' · ' +
            (row.reference || row.selected_text || '待补充文本');
          $('#review').showModal();
        }),
    );
  }
  $('#case-filter').onsubmit = (event) => {
    event.preventDefault();
    load().catch((e) => toast(e.message));
  };
  await load();
}
$('#review-form').onsubmit = async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  data.revision = Number(data.revision);
  data.regression = form.elements.regression.checked;
  try {
    await api('/api/cases/' + data.id, { method: 'PATCH', body: data });
    $('#review').close();
    toast('复核已保存');
    await casesPage();
  } catch (e) {
    toast(e.message);
  }
};

async function statsPage() {
  const version = routeVersion;
  const stats = await api('/api/stats');
  if (version !== routeVersion) return;
  const bars = (values) => {
    const max = Math.max(1, ...Object.values(values));
    return Object.entries(values)
      .map(
        ([key, value]) =>
          `<div class="bar-row"><span>${esc(key)}</span><div class="bar"><i style="width:${(value / max) * 100}%"></i></div><b>${value}</b></div>`,
      )
      .join('');
  };
  content.innerHTML =
    head(
      '测评统计',
      research ? '团队测试覆盖与真实问题沉淀。' : '你的测试贡献与反馈进展。',
    ) +
    `<div class="grid four">${[
      ['累计测试', stats.tests],
      ['真实音频测试', stats.real_tests],
      ['待复核 Case', stats.pending],
      ['正式回归 Case', stats.regression],
    ]
      .map(
        ([label, value]) =>
          `<section class="card metric-card"><p>${label}</p><div class="metric">${value}</div></section>`,
      )
      .join(
        '',
      )}</div><p class="small muted">演示测试 ${stats.demo_tests} 次，已单独标识；问题分布包含演示反馈。各计数反映当前样本覆盖。</p><div class="grid two section-space"><section class="card"><h2>测试语种覆盖</h2>${Object.keys(stats.languages).length ? bars(stats.languages) : empty('等待第一次测试', '历史测试会自动汇总。')}</section><section class="card"><h2>问题类型分布</h2>${bars(stats.types)}</section></div><section class="card section-space"><h2>原始投票分布</h2><p class="muted small">A / B / C 是每轮随机位置。计数用于查看参与情况，模型对比请回到具体测试。</p>${stats.votes.length ? stats.votes.map((row) => `<span class="tag">${esc({ both_good: '都准确', both_bad: '都有问题', skip: '跳过' }[row.choice] || '结果 ' + row.choice)} · ${row.count}</span>`).join('') : '<p class="muted">暂无投票</p>'}</section>`;
}

async function route() {
  const version = ++routeVersion;
  inlineTestId = null;
  clearTimeout(pollTimer);
  if (recorder?.state === 'recording') recorder.stop();
  const [page, id] = (location.hash.slice(1) || 'test').split('/');
  document
    .querySelectorAll('nav a')
    .forEach((link) =>
      link.classList.toggle(
        'active',
        link.dataset.page === (page === 'detail' ? 'history' : page),
      ),
    );
  $('#breadcrumb').textContent =
    {
      test: '在线测评',
      history: '测试历史',
      detail: '测试详情',
      cases: 'Case 库',
      stats: '测评统计',
    }[page] || '在线测评';
  try {
    if (page === 'detail' && id) await detailPage(id);
    else if (page === 'history') await historyPage();
    else if (page === 'cases') await casesPage();
    else if (page === 'stats') await statsPage();
    else testPage();
  } catch (error) {
    if (version === routeVersion)
      content.innerHTML = empty('页面暂时无法加载', esc(error.message));
  }
}
const sidebarToggle = document.querySelector('.sidebar-toggle');
if (sidebarToggle && document.body.classList) {
  const sidebarKey = 'asr-sidebar';
  const applySidebar = (collapsed) => {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    sidebarToggle.setAttribute('aria-expanded', String(!collapsed));
    sidebarToggle.title = collapsed ? '展开导航' : '收起导航';
    sidebarToggle.setAttribute('aria-label', sidebarToggle.title);
  };
  let sidebarCollapsed = false;
  try {
    sidebarCollapsed = localStorage.getItem(sidebarKey) === 'collapsed';
  } catch {
    sidebarCollapsed = false;
  }
  applySidebar(sidebarCollapsed);
  sidebarToggle.addEventListener('click', () => {
    sidebarCollapsed = !document.body.classList.contains('sidebar-collapsed');
    applySidebar(sidebarCollapsed);
    try {
      localStorage.setItem(sidebarKey, sidebarCollapsed ? 'collapsed' : 'expanded');
    } catch {
      /* Keep the choice for this visit when storage is unavailable. */
    }
  });
}
api('/api/config')
  .then((value) => {
    config = value;
    $('#type-options').innerHTML = config.types
      .map(
        (type) =>
          `<label><input type="checkbox" name="types" value="${esc(type)}">${esc(type)}</label>`,
      )
      .join('');
    $('#feature-options').innerHTML = options(config.features, '未知');
    $('#condition-options').innerHTML = options(config.conditions, '未知');
    $('#impact-options').innerHTML = options(config.impacts, '未知');
    $('#review-status').innerHTML = options(config.statuses);
    window.addEventListener('hashchange', route);
    route();
  })
  .catch((error) => toast(error.message));
