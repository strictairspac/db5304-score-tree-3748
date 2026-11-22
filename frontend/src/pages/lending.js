import {heading, panel} from '../components/common/heading.js';
import {entries, records} from '../components/common/records.js';
import {badge} from '../components/common/status.js';
import {itemStateLabels, orderStatusLabels} from '../constants/workflow.js';
import {topic} from '../constants/project.js';
import {date, esc} from '../utils/dom.js';
import {submit} from '../hooks/submit.js';
import {go} from '../router/hash.js';

function newRequestKey() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  return `order-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function rangeLabel(order) {
  return `${order.start_number} 至 ${order.end_number}`;
}

function itemRows(order) {
  if (!order.items.length) return '<p class="empty">该编号段没有已登记曲谱，空单已退回。</p>';
  return records(['曲谱编号', '谱名', '留谱判定', '份数'], order.items.map(item=>[
    esc(item.number), esc(item.title), esc(itemStateLabels[item.state] || item.state), esc(item.copies),
  ]));
}

function inventoryPanel(state, caseId) {
  const rows = state.inventory?.[caseId];
  if (!rows) return '';
  return panel('当前可留份数（已扣已留）', records(['曲谱编号', '谱名', '在库份数', '已留份数', '可留份数'],
    rows.map(row=>[esc(row.number), esc(row.title), esc(row.total_copies), esc(row.held_copies),
      esc(row.available_copies)]), '该批次暂无曲谱。'));
}

function createForm(state) {
  const catalogs = state.cases.filter(row=>Array.isArray(row.payload?.scores));
  if (!catalogs.length) return panel('提交留谱借阅单', '<p class="empty">先建立一份曲目索引批，才能提交借阅单。</p>');
  const options = catalogs.map(row=>`<option value="${row.id}">${esc(row.title)}（${row.payload.scores.length} 种曲谱）</option>`).join('');
  const sample = state.spec.sample;
  return panel('提交留谱借阅单', `<form id="lending-form" class="field-grid">
    <label class="field"><span>曲目索引批</span><select name="case_id">${options}</select></label>
    <label class="field"><span>请求键（重试不重复扣减）</span><input name="request_key" maxlength="64" value="${esc(newRequestKey())}" required /></label>
    <label class="field"><span>起始曲谱编号（含）</span><input name="start_number" type="number" min="1" step="1" value="${esc(sample.range_start)}" required /></label>
    <label class="field"><span>结束曲谱编号（含）</span><input name="end_number" type="number" min="1" step="1" value="${esc(sample.range_end)}" required /></label>
    <div class="actions form-actions"><button>提交借阅单</button><span class="note">任一曲目缺货则整单不留；空段直接退回。</span></div>
  </form>`);
}

export function lendingPage(state, identity) {
  const orders = state.lending || [];
  const selected = orders.find(row=>row.id===identity) || orders[0];
  const operator = state.session.role==='operator';
  const rows = orders.map(row=>[
    `<a href="#lending/${row.id}" ${row.id===selected?.id?'aria-current="true"':''}>留谱单 ${row.id}</a>`,
    esc(row.case_title), esc(rangeLabel(row)), badge(row.status),
    esc(row.held_numbers.length ? row.held_numbers.join('、') : '—'),
    esc(row.shortage_numbers.length ? row.shortage_numbers.join('、') : '—'),
    esc(date(row.created_at)),
  ]);
  const detail = selected ? `<h2>留谱单 ${selected.id} · ${esc(selected.case_title)}</h2>
    <dl><dt>编号段</dt><dd>${esc(rangeLabel(selected))}</dd>
    <dt>留谱结果</dt><dd><span class="status" data-state="${esc(selected.status)}">${esc(orderStatusLabels[selected.status] || selected.status)}</span></dd>
    <dt>留谱份数</dt><dd>${esc(selected.held_total)}</dd>
    <dt>已留编号</dt><dd>${esc(selected.held_numbers.length ? selected.held_numbers.join('、') : '—')}</dd>
    <dt>缺货编号</dt><dd>${esc(selected.shortage_numbers.length ? selected.shortage_numbers.join('、') : '—')}</dd>
    <dt>结论</dt><dd>${esc(selected.note)}</dd></dl>
    ${operator && selected.status!=='cancelled' ? `<button class="secondary" type="button" id="cancel-order" data-id="${selected.id}">撤销借阅单</button>` : ''}`
    : '<h2>留谱结果</h2><p>提交一张范围借阅单后，可在此查看留谱和缺货结果。</p>';
  const shortage = selected && selected.shortage_numbers.length
    ? panel('缺货曲目', records(['曲谱编号', '谱名'], selected.items
        .filter(item=>item.state==='shortage').map(item=>[esc(item.number), esc(item.title)])))
    : '';
  return `${heading(topic.routes.lending, '按曲谱编号段整套留谱，缺货整单不留，撤销只归还本单留过的份数。')}
    <div class="spread"><section aria-label="借阅单目录">
      ${records(['借阅单', '曲目索引批', '编号段', '状态', '已留编号', '缺货编号', '提交时间'], rows, '暂无借阅单。')}
    </section><aside class="brief">${detail}</aside></div>
    ${createForm(state)}
    ${selected ? panel('本单曲谱明细', itemRows(selected)) : ''}
    ${shortage}
    ${selected ? inventoryPanel(state, selected.case_id) : ''}`;
}

export function bindLending(state, api, update, fail) {
  submit('lending-form', async data=>{
    const payload = {
      case_id: Number(data.get('case_id')),
      start_number: Number(data.get('start_number')),
      end_number: Number(data.get('end_number')),
      request_key: (data.get('request_key') || '').trim(),
    };
    const order = await api('/lending/orders', {method:'POST', data:payload});
    go(`lending/${order.id}`);
    await update();
  }, fail);
  const cancel = document.getElementById('cancel-order');
  if (!cancel) return;
  cancel.addEventListener('click', async()=>{
    if (!confirm('撤销后只归还本单留过的份数，确定撤销？')) return;
    try {
      await api(`/lending/orders/${cancel.dataset.id}/cancel`, {method:'POST'});
      await update();
    } catch (error) { fail(error); }
  });
}
