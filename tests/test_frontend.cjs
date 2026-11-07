const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// Run the actual handlers with controlled requests and timers, without a browser.
function workbench(status = 'running') {
  const elements = new Map();
  const timers = new Map();
  const requests = [];
  const item = {
    id: 'job-1',
    title: 'Sample test',
    language: 'zh',
    scene: 'General',
    created: '2026-11-06T00:00:00Z',
    duration: status === 'awaiting_audio' ? 0 : 4,
    start: 0,
    sha256: 'hash',
    status,
    revealed: false,
    vote: null,
    results: [
      {
        id: 'result-1',
        label: 'A',
        status,
        text: '',
        elapsed: 0,
        provider: 'Qwen-ASR',
        snapshot: { model: 'qwen3-asr-flash' },
      },
    ],
  };
  function element(selector) {
    if (selector === 'dialog[open]') return null;
    if (selector === '#attach-form' && item.duration) return null;
    if (!elements.has(selector)) {
      elements.set(selector, {
        innerHTML: '',
        textContent: '',
        value: '',
        disabled: false,
        paused: true,
        content: 'csrf',
        files: [],
        attributes: {},
        classList: { add() {}, remove() {}, toggle() {} },
        setAttribute(name, value) {
          this.attributes[name] = value;
        },
        pause() {},
        scrollIntoView() {},
        focus() {},
        close() {},
        showModal() {},
        querySelector(child) {
          return element(selector + '/' + child);
        },
      });
    }
    return elements.get(selector);
  }
  const fields = {
    sample_id: 'sample-1',
    language: 'zh',
    start: '0',
    end: '',
    scene: 'General',
    title: 'Keep this title',
    models: 'qwen-asr',
  };
  element('#test-form').elements = Object.fromEntries(
    Object.entries(fields).map(([name, value]) => [name, { value }]),
  );
  const annotation = element('#annotation-form');
  annotation.elements = {
    types: { value: ['Other'] },
    selected_text: { value: '' },
    end: { value: '' },
  };
  annotation.reset = () => {};
  const vote = { dataset: { choice: 'A' } };
  const annotate = { dataset: { resultId: 'result-1' } };
  class FormData {
    constructor(form) {
      this.values = new Map(
        Object.entries(form.elements).map(([name, input]) => [name, input.value]),
      );
    }
    delete(name) {
      this.values.delete(name);
    }
    set(name, value) {
      this.values.set(name, value);
    }
    append(name, value) {
      this.values.set(
        name,
        this.values.has(name) ? [].concat(this.values.get(name), value) : value,
      );
    }
    getAll(name) {
      return [].concat(this.values.get(name) || []);
    }
    [Symbol.iterator]() {
      return this.values[Symbol.iterator]();
    }
  }
  const context = vm.createContext({
    document: {
      body: { dataset: { role: 'beta' } },
      querySelector: element,
      querySelectorAll: (selector) =>
        selector === '[data-choice]'
          ? [vote]
          : selector === '.annotate'
            ? [annotate]
            : [],
    },
    window: { getSelection: () => '', matchMedia: () => ({ matches: true }) },
    location: { hash: '#test' },
    FormData,
    setTimeout(callback) {
      const id = timers.size + 1;
      timers.set(id, callback);
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    fetch: async (url, settings = {}) => {
      requests.push({ url, settings });
      let body = {};
      if (url === '/api/tests' && settings.method === 'POST') body = { id: item.id };
      else if (url.endsWith('/rerun')) {
        item.id = 'job-2';
        body = { id: item.id };
      } else if (url.endsWith('/vote')) {
        item.revealed = true;
        item.vote = 'A';
      } else if (url.endsWith('/audio') && settings.method === 'POST') {
        item.duration = 4;
        item.status = item.results[0].status = 'completed';
        item.results[0].text = 'Attached audio result';
      } else if (url.startsWith('/api/tests/')) body = structuredClone(item);
      else if (url.startsWith('/api/cases') || url.startsWith('/api/tests?')) body = [];
      return { status: 200, ok: true, json: async () => body };
    },
  });
  const source = fs.readFileSync(
    path.join(__dirname, '../asr_eval/static/app.js'),
    'utf8',
  );
  vm.runInContext(source.slice(0, source.indexOf("api('/api/config')")), context);
  vm.runInContext(
    `config = ${JSON.stringify({
      languages: { zh: 'Chinese', en: 'English' },
      scenes: ['General'],
      models: [{ id: 'qwen-asr', name: 'Qwen-ASR' }],
      samples: [
        {
          id: 'sample-1',
          language: 'zh',
          title: 'Sample',
          duration: 4,
          dataset: 'FLEURS',
          reference: 'Reference',
          attribution: 'Google',
          source_url: 'https://example.test/',
          license_url: 'https://example.test/',
        },
      ],
    })}; testPage();`,
    context,
  );
  return {
    context,
    item,
    element,
    requests,
    timers,
    vote,
    annotate,
    submit: () =>
      element('#test-form').onsubmit({
        preventDefault() {},
        target: element('#test-form'),
      }),
    async tick() {
      const [id, callback] = timers.entries().next().value;
      timers.delete(id);
      await callback();
    },
  };
}

test('submission and polling keep the editor and route in place', async () => {
  const page = workbench();
  const editor = page.element('#content').innerHTML;
  await page.submit();
  assert.equal(page.context.location.hash, '#test');
  assert.equal(page.element('#content').innerHTML, editor);
  assert.match(page.element('#inline-results').innerHTML, /job-1/);
  assert.equal(page.element('#submit-test').disabled, true);
  page.element('#test-form').elements.title.value = 'Edited while recognizing';
  page.item.status = page.item.results[0].status = 'completed';
  page.item.results[0].text = '<recognized speech>';
  await page.tick();
  assert.match(page.element('#inline-results').innerHTML, /&lt;recognized speech&gt;/);
  assert.equal(page.element('#content').innerHTML, editor);
  assert.equal(
    page.element('#test-form').elements.title.value,
    'Edited while recognizing',
  );
  assert.equal(page.element('#submit-test').disabled, false);
});

test('vote, annotation and rerun refresh the inline result only', async () => {
  const page = workbench('completed');
  await page.submit();
  const editor = page.element('#content').innerHTML;
  await page.vote.onclick();
  assert.equal(page.element('#content').innerHTML, editor);
  assert.match(page.element('#inline-results').innerHTML, /Qwen-ASR/);
  page.annotate.onclick();
  await page.element('#annotation-form').onsubmit({
    preventDefault() {},
    target: page.element('#annotation-form'),
  });
  assert.ok(page.requests.some((request) => request.url === '/api/tests/job-1/cases'));
  assert.equal(page.element('#content').innerHTML, editor);
  await page.element('#rerun').onclick();
  assert.match(page.element('#inline-results').innerHTML, /job-2/);
  assert.equal(page.context.location.hash, '#test');
  assert.equal(page.element('#content').innerHTML, editor);
});

test('navigation stops inline polling; history retains its detail page', async () => {
  const page = workbench();
  await page.submit();
  const queued = [...page.timers.values()][0];
  page.context.location.hash = '#history';
  await vm.runInContext('route()', page.context);
  const history = page.element('#content').innerHTML;
  const count = page.requests.length;
  await queued();
  assert.equal(page.requests.length, count);
  assert.equal(page.element('#content').innerHTML, history);
  page.context.location.hash = '#detail/job-1';
  await vm.runInContext('route()', page.context);
  assert.match(page.element('#content').innerHTML, /job-1/);
});

test('a playing result is not replaced by a polling refresh', async () => {
  const page = workbench();
  await page.submit();
  page.element('#test-audio').paused = false;
  const count = page.requests.length;
  const result = page.element('#inline-results').innerHTML;
  await page.tick();
  assert.equal(page.requests.length, count);
  assert.equal(page.element('#inline-results').innerHTML, result);
  assert.equal(page.timers.size, 1);
});

test('leaving during submission does not pull the user back to results', async () => {
  const page = workbench();
  const fetch = page.context.fetch;
  let release;
  page.context.fetch = async (url, settings) => {
    if (url === '/api/tests')
      await new Promise((resolve) => {
        release = resolve;
      });
    return fetch(url, settings);
  };
  const submitted = page.submit();
  page.context.location.hash = '#history';
  await vm.runInContext('route()', page.context);
  const history = page.element('#content').innerHTML;
  release();
  await submitted;
  assert.equal(page.context.location.hash, '#history');
  assert.equal(page.element('#content').innerHTML, history);
  assert.equal(
    page.requests.some((request) => request.url === '/api/tests/job-1'),
    false,
  );
});

test('a late polling response cannot overwrite another page', async () => {
  const page = workbench();
  await page.submit();
  const fetch = page.context.fetch;
  let release;
  page.context.fetch = async (url, settings) => {
    if (url === '/api/tests/job-1')
      await new Promise((resolve) => {
        release = resolve;
      });
    return fetch(url, settings);
  };
  const refreshing = page.tick();
  page.context.location.hash = '#history';
  await vm.runInContext('route()', page.context);
  const history = page.element('#content').innerHTML;
  release();
  await refreshing;
  assert.equal(page.element('#content').innerHTML, history);
});

test('retrying a result read does not submit another ASR job', async () => {
  const page = workbench('completed');
  const fetch = page.context.fetch;
  let fail = true;
  page.context.fetch = async (url, settings) => {
    if (url === '/api/tests/job-1' && fail) {
      fail = false;
      return { status: 503, ok: false, json: async () => ({ error: 'Unavailable' }) };
    }
    return fetch(url, settings);
  };
  await page.submit();
  assert.ok(page.element('#retry-inline').onclick);
  await page.element('#retry-inline').onclick();
  assert.match(page.element('#inline-results').innerHTML, /job-1/);
  assert.equal(
    page.requests.filter((request) => request.url === '/api/tests').length,
    1,
  );
  assert.equal(page.context.location.hash, '#test');
});

test('a saved video link can receive audio and show results inline', async () => {
  const page = workbench('awaiting_audio');
  await page.submit();
  const editor = page.element('#content').innerHTML;
  const form = page.element('#attach-form');
  form.elements = { file: { value: 'audio-file' } };
  await form.onsubmit({ preventDefault() {}, target: form });
  assert.ok(page.requests.some((request) => request.url === '/api/tests/job-1/audio'));
  assert.match(page.element('#inline-results').innerHTML, /Attached audio result/);
  assert.equal(page.element('#content').innerHTML, editor);
  assert.equal(page.context.location.hash, '#test');
});

test('two ASR selections submit the same sample in one job', async () => {
  const page = workbench();
  page.element('#test-form').elements.models.value = ['qwen-asr', 'fun-asr'];
  await page.submit();
  const sent = page.requests.find((request) => request.url === '/api/tests').settings
    .body;
  assert.deepEqual(sent.getAll('models'), ['qwen-asr', 'fun-asr']);
  assert.deepEqual(sent.getAll('sample_id'), ['sample-1']);
  assert.equal(
    page.requests.filter((request) => request.url === '/api/tests').length,
    1,
  );
});

test('optional second model is omitted and duplicate models are rejected', async () => {
  const page = workbench();
  page.element('#test-form').elements.models.value = ['qwen-asr', ''];
  await page.submit();
  const sent = page.requests.find((request) => request.url === '/api/tests').settings
    .body;
  assert.deepEqual(sent.getAll('models'), ['qwen-asr']);
  const duplicate = workbench();
  duplicate.element('#test-form').elements.models.value = ['qwen-asr', 'qwen-asr'];
  await duplicate.submit();
  assert.equal(
    duplicate.requests.some((request) => request.url === '/api/tests'),
    false,
  );
  const tooMany = workbench();
  tooMany.element('#test-form').elements.models.value = ['a', 'b', 'c', 'd'];
  await tooMany.submit();
  assert.equal(tooMany.requests.some((request) => request.url === '/api/tests'), false);
});

test('online evaluation uses one multi-select model picker', () => {
  const page = workbench();
  const html = page.element('#content').innerHTML;
  assert.match(html, /id="model-picker"/);
  assert.doesNotMatch(html, /ASR 模型 1|ASR 模型 2|不对比/);
  assert.match(html, /name="models" form="test-form"/);
  assert.match(html, /type="checkbox"/);
});
