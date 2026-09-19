const $ = (selector) => document.querySelector(selector);
const cut = $('#cut');
const protocol = $('#protocol');
const metrics = $('#metrics');
const question = $('#question');
const answerTitle = $('#answer-title');
const answerBadge = $('#answer-badge');
const answerBody = $('#answer-body');
const patientPanel = $('#patient');
const watchResults = $('#watch-results');

for (let value = 1; value <= 12; value += 1) {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = `Cut ${value}`;
  if (value === 12) option.selected = true;
  cut.append(option);
}

const formatNumber = (value) => new Intl.NumberFormat().format(value);

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function getJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Request failed');
  return payload;
}

async function loadSummary() {
  const data = await getJson(`/api/summary?cut=${cut.value}`);
  protocol.textContent = `Protocol v${data.protocol_version || 1}`;
  metrics.innerHTML = [['Subjects', data.subjects], ['Graph nodes', data.nodes], ['Edges', data.edges], ['Build time', `${data.ms} ms`]]
    .map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${typeof value === 'number' ? formatNumber(value) : value}</strong></div>`).join('');
}

function cleanSubjectId(raw) {
  if (!raw) return '';
  const match = raw.match(/\b\d{3}-S\d{1,3}-\d{3}\b/i);
  return match ? match[0].toUpperCase() : raw.trim().toUpperCase();
}

function refsHtml(refs) {
  if (!refs.length) return '<span class="explanation">No supporting records.</span>';
  return refs.map((ref) => `<span class="ref clickable-chip" data-usubjid="${ref.usubjid}" title="Click to view Subject 360 for ${ref.usubjid}">${ref.domain} · ${ref.usubjid} · ${ref.seq}</span>`).join('');
}

function renderAnswer(data) {
  const value = data.answer;
  const isEmptyArray = Array.isArray(value) && value.length === 0;
  answerBadge.classList.remove('good', 'neutral');

  if (isEmptyArray) {
    answerTitle.textContent = 'No findings found';
    answerBadge.textContent = 'NO FINDINGS';
    answerBadge.classList.add('neutral');
  } else {
    answerTitle.textContent = Array.isArray(value) ? `${value.length} result${value.length === 1 ? '' : 's'}` : 'Review result';
    answerBadge.textContent = 'EVIDENCE READY';
    answerBadge.classList.add('good');
  }

  answerBody.classList.remove('empty');
  let content = '';
  if (typeof value === 'number') content += `<p class="answer-number">${formatNumber(value)}</p>`;
  else if (Array.isArray(value) && value.length && typeof value[0] === 'string') content += `<div class="answer-list">${value.map((item) => `<span class="subject-chip clickable-chip" data-usubjid="${item}" title="Click to view Subject 360 for ${item}">${item}</span>`).join('')}</div>`;
  else if (Array.isArray(value) && value.length) content += `<p class="explanation">${value.length} records returned. See the cited references below.</p>`;
  else if (isEmptyArray) content += '<p class="answer-number">0</p>';
  content += `<p class="explanation">${data.explanation}</p><div class="evidence"><span class="evidence-title">Supporting records</span><div>${refsHtml(data.evidence)}</div></div>`;
  answerBody.innerHTML = content;

  answerBody.querySelectorAll('.clickable-chip').forEach((chip) => {
    chip.style.cursor = 'pointer';
    chip.addEventListener('click', () => {
      const targetId = chip.dataset.usubjid;
      if (targetId) {
        $('#subject').value = targetId;
        openPatient(targetId);
      }
    });
  });
}

async function ask() {
  const text = question.value.trim();
  if (!text) return;
  $('#ask').disabled = true;
  answerTitle.textContent = 'Reviewing...';
  answerBadge.textContent = 'WORKING';
  try { renderAnswer(await getJson(`/api/answer?q=${encodeURIComponent(text)}`)); }
  catch (error) { answerTitle.textContent = 'Unable to answer'; answerBody.innerHTML = `<p class="explanation">${error.message}</p>`; }
  finally { $('#ask').disabled = false; }
}

function drawSubjectKnowledgeGraph(canvas, data) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const width = (canvas.width = canvas.parentElement.clientWidth || 700);
  const height = (canvas.height = 500);

  ctx.clearRect(0, 0, width, height);

  const centerX = width / 2;
  const centerY = height / 2;

  const domains = [
    { name: 'DM', label: 'Demographics', count: 1, color: '#16795e', bg: '#e4f5cf' },
    { name: 'LB', label: `Labs (${data.labs.length})`, count: data.labs.length, color: '#097969', bg: '#d0f0c0' },
    { name: 'AE', label: `AEs (${data.adverse_events.length})`, count: data.adverse_events.length, color: '#d9534f', bg: '#fde8e7' },
    { name: 'EX', label: `Dosing (${data.dosing.length})`, count: data.dosing.length, color: '#f49c5b', bg: '#fef3e9' },
    { name: 'CM', label: `ConMeds (${data.concomitant_medications.length})`, count: data.concomitant_medications.length, color: '#5b8cf4', bg: '#eaf1fe' },
    { name: 'DS', label: `Disposition (${data.disposition.length})`, count: data.disposition.length, color: '#8e44ad', bg: '#f4ecf7' },
    { name: 'MH', label: `Medical Hx (${data.medical_history.length})`, count: data.medical_history.length, color: '#34495e', bg: '#eaeded' },
    { name: 'EG', label: `ECG (${data.ecg ? data.ecg.length : 0})`, count: data.ecg ? data.ecg.length : 0, color: '#16a085', bg: '#e8f8f5' },
  ];

  const radius = Math.min(width, height) * 0.40;
  const cardWidth = Math.min(150, width * 0.21);
  const cardHeight = 64;
  const nodePositions = [];

  canvas.style.cursor = 'pointer';
  canvas._graphData = data;
  canvas._graphNodes = nodePositions;
  if (!canvas._graphClickBound) {
    canvas.addEventListener('click', (event) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = (event.clientX - rect.left) * scaleX;
      const y = (event.clientY - rect.top) * scaleY;
      const hit = canvas._graphNodes.find((node) => Math.hypot(x - node.x, y - node.y) <= node.radius + 8);
      if (hit) renderGraphDetails(canvas._graphData, hit.domain);
    });
    canvas._graphClickBound = true;
  }

  // Draw Edges
  domains.forEach((dom, i) => {
    const angle = (i * 2 * Math.PI) / domains.length - Math.PI / 2;
    const x = centerX + radius * Math.cos(angle);
    const y = centerY + radius * Math.sin(angle);

    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.lineTo(x, y);
    ctx.strokeStyle = dom.count > 0 ? dom.color : '#d7e2da';
    ctx.lineWidth = dom.count > 0 ? 2 : 1;
    ctx.setLineDash(dom.count > 0 ? [] : [4, 4]);
    ctx.stroke();
    ctx.setLineDash([]);
  });

  // Draw Center Patient Node
  ctx.beginPath();
  ctx.arc(centerX, centerY, 34, 0, 2 * Math.PI);
  ctx.fillStyle = '#16795e';
  ctx.fill();
  ctx.lineWidth = 4;
  ctx.strokeStyle = '#c5ed78';
  ctx.stroke();

  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 11px DM Mono, monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('SUBJECT', centerX, centerY - 7);
  ctx.font = '500 9px DM Mono, monospace';
  ctx.fillText(data.USUBJID.split('-').slice(1).join('-') || data.USUBJID, centerX, centerY + 8);

  // Draw Domain Nodes
  domains.forEach((dom, i) => {
    const angle = (i * 2 * Math.PI) / domains.length - Math.PI / 2;
    const x = centerX + radius * Math.cos(angle);
    const y = centerY + radius * Math.sin(angle);

    const nodeR = dom.count > 0 ? 22 : 18;
    nodePositions.push({ domain: dom.name, x, y, radius: nodeR });

    const left = x - cardWidth / 2;
    const top = y - cardHeight / 2;
    nodePositions[nodePositions.length - 1] = { domain: dom.name, x, y, radius: Math.max(cardWidth, cardHeight) / 2 };
    ctx.beginPath();
    ctx.roundRect(left, top, cardWidth, cardHeight, 10);
    ctx.fillStyle = dom.bg;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = dom.color;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(left + 22, top + 22, 13, 0, 2 * Math.PI);
    ctx.fillStyle = dom.color;
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 9px DM Mono, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(dom.name, left + 22, top + 22);

    ctx.textAlign = 'left';
    ctx.fillStyle = '#15221f';
    ctx.font = '700 11px Manrope, sans-serif';
    ctx.fillText(dom.label.split(' (')[0], left + 42, top + 19);
    ctx.fillStyle = '#687873';
    ctx.font = '500 10px DM Mono, monospace';
    ctx.fillText(`${dom.count} record${dom.count === 1 ? '' : 's'}`, left + 42, top + 38);
  });

  nodePositions.push({ domain: 'SUBJECT', x: centerX, y: centerY, radius: 42 });
}

function graphRecords(data, domain) {
  const map = {
    DM: data.demographics ? [data.demographics] : [],
    LB: data.labs || [],
    AE: data.adverse_events || [],
    EX: data.dosing || [],
    CM: data.concomitant_medications || [],
    EG: data.ecg || [],
    MH: data.medical_history || [],
    DS: data.disposition || [],
  };
  return map[domain] || [];
}

function graphDomainLabel(domain) {
  return {
    SUBJECT: 'Subject overview', DM: 'Demographics', LB: 'Laboratory results', AE: 'Adverse events',
    EX: 'Dosing records', CM: 'Concomitant medications', EG: 'ECG records', MH: 'Medical history', DS: 'Disposition',
  }[domain] || domain;
}

function graphRecordSummary(domain, row) {
  const values = {
    LB: `${row.LBTESTCD || 'Lab'}: ${row.LBORRES || 'not numeric'} ${row.LBORRESU || ''}`,
    AE: `${row.AETERM || 'Adverse event'} · ${row.AESEV || 'severity not recorded'}`,
    EX: `${row.EXTRT || 'Treatment'}: ${row.EXDOSE || 'not recorded'} ${row.EXDOSU || ''}`,
    CM: `${row.CMTRT || 'Medication'} · ${row.CMCLAS || 'class not recorded'}`,
    EG: `${row.EGTESTCD || 'ECG'}: ${row.EGORRES || 'not recorded'} ${row.EGORRESU || ''}`,
    MH: row.MHTERM || 'Medical history record',
    DS: `${row.DSDECOD || 'Disposition'}${row.DSTERM ? ` · ${row.DSTERM}` : ''}`,
    DM: `${row.ARM || 'Arm not recorded'} · ${row.SITEID || 'Site not recorded'} · age ${row.AGE || 'n/a'}`,
  };
  return values[domain] || 'Record available';
}

function renderGraphDetails(data, domain) {
  const panel = $('#graph-details');
  if (!panel) return;
  const rows = graphRecords(data, domain);
  const title = graphDomainLabel(domain);
  const recordCards = rows.slice(0, 80).map((row) => {
    const sequence = row[`${domain}SEQ`] || '1';
    const date = row.LBDTC || row.AESTDTC || row.EXSTDTC || row.CMSTDTC || row.EGDTC || row.DSSTDTC || '';
    return `<button class="graph-record" type="button" data-record-domain="${domain}" data-record-seq="${sequence}"><span class="graph-record-ref">${domain} · ${sequence}</span><strong>${escapeHtml(graphRecordSummary(domain, row))}</strong><small>${escapeHtml(row.VISIT || date || 'Subject-level record')}</small></button>`;
  }).join('');
  const subjectSummary = domain === 'SUBJECT'
    ? `<div class="graph-detail-stats">${['LB', 'AE', 'EX', 'CM', 'EG', 'MH', 'DS'].map((item) => `<span><strong>${graphRecords(data, item).length}</strong>${graphDomainLabel(item)}</span>`).join('')}</div>`
    : '';
  panel.innerHTML = `<div class="graph-detail-head"><div><p class="eyebrow">SELECTED GRAPH NODE</p><h4>${escapeHtml(title)}</h4></div><button id="close-graph-details" class="detail-close" type="button">Close</button></div><p class="graph-detail-caption">${domain === 'SUBJECT' ? 'Choose a colored node to inspect its connected records.' : `${rows.length} connected record${rows.length === 1 ? '' : 's'} for ${escapeHtml(data.USUBJID)}.`}</p>${subjectSummary}<div class="graph-record-list">${recordCards || '<p class="explanation">No records are available for this node.</p>'}</div><div id="graph-record-detail" class="graph-record-detail hidden"></div>`;
  panel.classList.remove('hidden');
  $('#close-graph-details').addEventListener('click', () => panel.classList.add('hidden'));
  panel.querySelectorAll('.graph-record').forEach((card) => card.addEventListener('click', () => {
    panel.querySelectorAll('.graph-record').forEach((item) => item.classList.remove('selected'));
    card.classList.add('selected');
    const selected = rows.find((row) => String(row[`${domain}SEQ`] || '1') === card.dataset.recordSeq) || {};
    const fields = Object.entries(selected).filter(([, value]) => value !== '' && value != null).map(([key, value]) => `<span><b>${escapeHtml(key)}</b>${escapeHtml(value)}</span>`).join('');
    const detail = $('#graph-record-detail');
    detail.classList.remove('hidden');
    detail.innerHTML = `<div class="graph-record-detail-head"><span class="graph-record-ref">${domain} · ${escapeHtml(card.dataset.recordSeq)}</span><span class="evidence-title">FULL RECORD</span></div><div class="graph-field-grid">${fields}</div>`;
  }));
}

function drawLabSafetyChart(canvas, data) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const width = (canvas.width = canvas.parentElement.clientWidth || 700);
  const height = (canvas.height = 320);

  ctx.clearRect(0, 0, width, height);

  const altPoints = data.labs.filter((r) => r.LBTESTCD === 'ALT' && r.LBORRES);
  const astPoints = data.labs.filter((r) => r.LBTESTCD === 'AST' && r.LBORRES);
  const biliPoints = data.labs.filter((r) => r.LBTESTCD === 'BILI' && r.LBORRES);

  if (!altPoints.length && !astPoints.length) {
    ctx.fillStyle = '#687873';
    ctx.font = '12px Manrope';
    ctx.textAlign = 'center';
    ctx.fillText('No liver enzyme lab trajectory records found for this subject.', width / 2, height / 2);
    return;
  }

  const padding = { top: 30, right: 30, bottom: 50, left: 60 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  // Collect visits in chronological order
  const visits = Array.from(new Set(data.labs.map((r) => r.VISIT || 'VISIT'))).slice(0, 8);
  const maxVal = Math.max(
    100,
    ...altPoints.map((r) => parseFloat(r.LBORRES) * (r.LBORRESU === 'ukat/L' ? 60 : 1) || 0),
    ...astPoints.map((r) => parseFloat(r.LBORRES) * (r.LBORRESU === 'ukat/L' ? 60 : 1) || 0)
  );

  // Draw Grid & Axes
  ctx.strokeStyle = '#d7e2da';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top);
  ctx.lineTo(padding.left, height - padding.bottom);
  ctx.lineTo(width - padding.right, height - padding.bottom);
  ctx.stroke();

  // X Axis visit labels
  ctx.fillStyle = '#687873';
  ctx.font = '10px DM Mono, monospace';
  ctx.textAlign = 'center';
  visits.forEach((v, i) => {
    const x = padding.left + (i * chartW) / Math.max(visits.length - 1, 1);
    ctx.fillText(v, x, height - padding.bottom + 18);
  });

  // Plot Curve Helper
  function plotSeries(records, color, label, isBili = false) {
    if (!records.length) return;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2.5;
    ctx.beginPath();

    records.forEach((r, i) => {
      const vIdx = visits.indexOf(r.VISIT);
      const x = vIdx >= 0 ? padding.left + (vIdx * chartW) / Math.max(visits.length - 1, 1) : padding.left + (i * chartW) / Math.max(records.length - 1, 1);
      let val = parseFloat(r.LBORRES) || 0;
      if (r.LBORRESU === 'ukat/L') val *= 60;
      const y = height - padding.bottom - (val / (maxVal * 1.15)) * chartH;

      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Draw dots
    records.forEach((r, i) => {
      const vIdx = visits.indexOf(r.VISIT);
      const x = vIdx >= 0 ? padding.left + (vIdx * chartW) / Math.max(visits.length - 1, 1) : padding.left + (i * chartW) / Math.max(records.length - 1, 1);
      let val = parseFloat(r.LBORRES) || 0;
      if (r.LBORRESU === 'ukat/L') val *= 60;
      const y = height - padding.bottom - (val / (maxVal * 1.15)) * chartH;

      ctx.beginPath();
      ctx.arc(x, y, 4, 0, 2 * Math.PI);
      ctx.fill();
    });
  }

  plotSeries(altPoints, '#16795e', 'ALT (U/L)');
  plotSeries(astPoints, '#f49c5b', 'AST (U/L)');
  plotSeries(biliPoints, '#e74c3c', 'BILI (mg/dL)', true);
}

async function openPatient(explicitId) {
  const rawId = explicitId || $('#subject').value.trim();
  const id = cleanSubjectId(rawId);
  if (!id) return;
  $('#subject').value = id;
  try {
    const data = await getJson(`/api/patient?usubjid=${encodeURIComponent(id)}`);
    const timeline = data.timeline.slice(0, 24).map((item) => `<div class="timeline-item"><strong>${item.domain} · ${item.sequence}</strong><span>${item.visit || 'Record'}${item.date ? ` · ${item.date}` : ''}</span></div>`).join('');
    
    patientPanel.classList.remove('hidden');
    patientPanel.innerHTML = `
      <div class="patient-header">
        <div>
          <p class="eyebrow">SUBJECT 360 & GRAPH</p>
          <h3>${data.USUBJID}</h3>
          <span class="patient-meta">${data.demographics.ARM || 'Unknown arm'} · ${data.demographics.SITEID || 'Unknown site'} · ${data.demographics.COUNTRY || ''}</span>
        </div>
        <div class="patient-stats">
          <div><strong>${data.labs.length}</strong> labs</div>
          <div><strong>${data.adverse_events.length}</strong> AEs</div>
          <div><strong>${data.dosing.length}</strong> doses</div>
        </div>
      </div>
      
      <div class="view-tabs">
        <button class="tab-btn active" id="tab-graph">🕸 Knowledge Graph</button>
        <button class="tab-btn" id="tab-chart">📈 Lab Safety Trajectory</button>
        <button class="tab-btn" id="tab-timeline">📋 Record Timeline</button>
      </div>

      <div id="view-graph-container" class="graph-container">
        <canvas id="kg-canvas" class="graph-canvas"></canvas>
        <div class="graph-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#16795e;"></span> Patient Hub</span>
          <span class="legend-item"><span class="legend-dot" style="background:#097969;"></span> Labs (LB)</span>
          <span class="legend-item"><span class="legend-dot" style="background:#d9534f;"></span> Adverse Events (AE)</span>
          <span class="legend-item"><span class="legend-dot" style="background:#f49c5b;"></span> Dosing (EX)</span>
        </div>
        <div id="graph-details" class="graph-details hidden"></div>
      </div>

      <div id="view-chart-container" class="chart-container hidden">
        <canvas id="chart-canvas" class="graph-canvas"></canvas>
        <div class="graph-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#16795e;"></span> ALT (U/L)</span>
          <span class="legend-item"><span class="legend-dot" style="background:#f49c5b;"></span> AST (U/L)</span>
          <span class="legend-item"><span class="legend-dot" style="background:#e74c3c;"></span> Bilirubin (mg/dL)</span>
        </div>
      </div>

      <div id="view-timeline-container" class="timeline hidden">
        ${timeline || '<p class="explanation">No timeline records.</p>'}
      </div>
    `;

    // Render Knowledge Graph Canvas
    const kgCanvas = $('#kg-canvas');
    drawSubjectKnowledgeGraph(kgCanvas, data);

    // Tab switching logic
    const tabGraph = $('#tab-graph');
    const tabChart = $('#tab-chart');
    const tabTimeline = $('#tab-timeline');
    const vgContainer = $('#view-graph-container');
    const vcContainer = $('#view-chart-container');
    const vtContainer = $('#view-timeline-container');

    tabGraph.addEventListener('click', () => {
      [tabGraph, tabChart, tabTimeline].forEach((b) => b.classList.remove('active'));
      tabGraph.classList.add('active');
      vgContainer.classList.remove('hidden');
      vcContainer.classList.add('hidden');
      vtContainer.classList.add('hidden');
      drawSubjectKnowledgeGraph(kgCanvas, data);
    });

    tabChart.addEventListener('click', () => {
      [tabGraph, tabChart, tabTimeline].forEach((b) => b.classList.remove('active'));
      tabChart.classList.add('active');
      vgContainer.classList.add('hidden');
      vcContainer.classList.remove('hidden');
      vtContainer.classList.add('hidden');
      drawLabSafetyChart($('#chart-canvas'), data);
    });

    tabTimeline.addEventListener('click', () => {
      [tabGraph, tabChart, tabTimeline].forEach((b) => b.classList.remove('active'));
      tabTimeline.classList.add('active');
      vgContainer.classList.add('hidden');
      vcContainer.classList.add('hidden');
      vtContainer.classList.remove('hidden');
    });

    patientPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (error) {
    patientPanel.classList.remove('hidden');
    patientPanel.innerHTML = `<div class="patient-header"><div><p class="eyebrow">PATIENT SEARCH</p><h3>${id}</h3><p class="explanation" style="margin-top:8px;">${error.message}</p></div></div>`;
  }
}

cut.addEventListener('change', loadSummary);
$('#ask').addEventListener('click', ask);
question.addEventListener('keydown', (event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) ask(); });
$('#open-patient').addEventListener('click', () => openPatient());
$('#subject').addEventListener('keydown', (event) => { if (event.key === 'Enter') openPatient(); });
document.querySelectorAll('[data-question]').forEach((button) => button.addEventListener('click', () => { question.value = button.dataset.question; ask(); }));

// STAGE 2 MONITOR CREW INTERACTION
async function runStage2Crew() {
  const btn = $('#run-crew');
  const results = $('#crew-results');
  const stats = $('#crew-stats');
  const pEsc = $('#panel-escalations');
  const pQue = $('#panel-queries');
  const pDev = $('#panel-deviations');
  const pTra = $('#panel-trace');

  btn.disabled = true;
  btn.innerHTML = 'Reviewing 6 Nodes... <span>⏳</span>';

  try {
    const data = await getJson(`/api/stage2/report?cut=${cut.value}`);
    results.classList.remove('hidden');

    // Stats
    stats.innerHTML = [
      ['Data Cut', `Cut ${data.cut}`],
      ['Protocol', `v${data.protocol_version}`],
      ['Findings', data.findings.length],
      ['Queries', data.queries.length],
      ['Escalations', data.escalations.length],
      ['Site Flags', data.site_flags.length],
    ].map(([l, v]) => `<div class="crew-stat"><span>${l}</span><strong>${v}</strong></div>`).join('');

    // Escalations Card List
    let escHtml = data.escalations.length ? data.escalations.map((e) => {
      const bClass = e.status === 'APPROVED' ? 'badge-approved' : e.status === 'REJECTED' ? 'badge-rejected' : e.status === 'CLARIFIED' ? 'badge-clarified' : 'badge-critical';
      return `
        <div class="crew-card">
          <div class="card-header">
            <span class="card-title">${e.id}: ${e.code} · ${e.usubjid} (${e.site})</span>
            <span class="card-badge ${bClass}">${e.status || e.severity}</span>
          </div>
          <div class="card-body">
            <p><strong>Rationale:</strong> ${e.summary}</p>
            ${e.alternatives ? `<p style="margin-top:4px;font-size:11px;"><strong>Alternatives:</strong> ${e.alternatives.join(' | ')}</p>` : ''}
          </div>
          <div class="card-actions">
            <span class="ref clickable-chip" data-usubjid="${e.usubjid}">Patient 360 · ${e.usubjid}</span>
          </div>
        </div>
      `;
    }).join('') : '<p class="explanation">No new escalations for this cut (all issues monitored or resolved).</p>';

    if (data.rejected_escalations && data.rejected_escalations.length > 0) {
      escHtml += `
        <div class="crew-card" style="border-left: 3px solid #788882; background: #f0f2f1; margin-top: 12px;">
          <div class="card-header">
            <span class="card-title">Cross-Cycle State: Downgraded Escalations</span>
            <span class="card-badge badge-rejected">${data.rejected_escalations.length} Downgraded</span>
          </div>
          <div class="card-body">
            <p>${data.rejected_escalations.length} escalation(s) were previously rejected by the medical monitor and remain downgraded to safety monitoring without repeat escalation.</p>
          </div>
        </div>
      `;
    }
    pEsc.innerHTML = escHtml;

    // Data Manager Queries
    let queHtml = data.queries.length ? data.queries.map((q) => `
      <div class="crew-card">
        <div class="card-header">
          <span class="card-title">${q.id}: ${q.domain} · ${q.usubjid} · seq ${q.sequence}</span>
          <span class="card-badge badge-high">${q.status}</span>
        </div>
        <div class="card-body">
          <p>${q.message}</p>
        </div>
        <div class="card-actions">
          <span class="ref clickable-chip" data-usubjid="${q.usubjid}">View ${q.usubjid}</span>
        </div>
      </div>
    `).join('') : '<p class="explanation">No new site queries generated for this cut.</p>';

    if (data.existing_queries_suppressed && data.existing_queries_suppressed.length > 0) {
      queHtml += `
        <div class="crew-card" style="border-left: 3px solid var(--green); background: #f8faf6; margin-top: 12px;">
          <div class="card-header">
            <span class="card-title">Cross-Cycle Idempotency Active</span>
            <span class="card-badge badge-approved">${data.existing_queries_suppressed.length} Suppressed</span>
          </div>
          <div class="card-body">
            <p>${data.existing_queries_suppressed.length} duplicate queries suppressed because they were already issued in previous review cycles.</p>
          </div>
        </div>
      `;
    }
    pQue.innerHTML = queHtml;

    // Compliance Deviations
    pDev.innerHTML = data.compliance_deviations.length ? data.compliance_deviations.map((d) => `
      <div class="crew-card">
        <div class="card-header">
          <span class="card-title">${d.code} · ${d.usubjid}</span>
          <span class="card-badge badge-critical">${d.domain} SEQ ${d.seq}</span>
        </div>
        <div class="card-body">
          <p>${d.message}</p>
        </div>
        <div class="card-actions">
          <span class="ref clickable-chip" data-usubjid="${d.usubjid}">View Profile</span>
        </div>
      </div>
    `).join('') : '<p class="explanation">No compliance deviations recorded.</p>';

    // Trace Feed
    pTra.innerHTML = data.trace.slice(-30).reverse().map((t) => `
      <div class="trace-item">
        <div class="trace-meta">[${t.node.toUpperCase()}] · ${t.timestamp} · Cut ${t.cut} (v${t.protocol_version})</div>
        <div><strong>${t.action}</strong>: ${t.reason || t.rationale || t.summary || t.message || JSON.stringify(t.query || t.escalation || '')}</div>
      </div>
    `).join('');

    // Attach click handlers to chips in Stage 2 panels
    results.querySelectorAll('.clickable-chip').forEach((chip) => {
      chip.style.cursor = 'pointer';
      chip.addEventListener('click', () => {
        const target = chip.dataset.usubjid;
        if (target) {
          $('#subject').value = target;
          openPatient(target);
        }
      });
    });

    results.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (err) {
    alert(`Stage 2 execution error: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Execute Review Cycle <span>⚡</span>';
  }
}

// Stage 2 Tab Handlers
const tabEsc = $('#tab-escalations');
const tabQue = $('#tab-queries');
const tabDev = $('#tab-deviations');
const tabTra = $('#tab-trace');
const pEsc = $('#panel-escalations');
const pQue = $('#panel-queries');
const pDev = $('#panel-deviations');
const pTra = $('#panel-trace');

if (tabEsc && tabQue && tabDev && tabTra) {
  tabEsc.addEventListener('click', () => {
    [tabEsc, tabQue, tabDev, tabTra].forEach((b) => b.classList.remove('active'));
    tabEsc.classList.add('active');
    pEsc.classList.remove('hidden');
    pQue.classList.add('hidden');
    pDev.classList.add('hidden');
    pTra.classList.add('hidden');
  });

  tabQue.addEventListener('click', () => {
    [tabEsc, tabQue, tabDev, tabTra].forEach((b) => b.classList.remove('active'));
    tabQue.classList.add('active');
    pEsc.classList.add('hidden');
    pQue.classList.remove('hidden');
    pDev.classList.add('hidden');
    pTra.classList.add('hidden');
  });

  tabDev.addEventListener('click', () => {
    [tabEsc, tabQue, tabDev, tabTra].forEach((b) => b.classList.remove('active'));
    tabDev.classList.add('active');
    pEsc.classList.add('hidden');
    pQue.classList.add('hidden');
    pDev.classList.remove('hidden');
    pTra.classList.add('hidden');
  });

  tabTra.addEventListener('click', () => {
    [tabEsc, tabQue, tabDev, tabTra].forEach((b) => b.classList.remove('active'));
    tabTra.classList.add('active');
    pEsc.classList.add('hidden');
    pQue.classList.add('hidden');
    pDev.classList.add('hidden');
    pTra.classList.remove('hidden');
  });
}

async function loadRiskPrediction() {
  const subjectInput = $('#risk-subject');
  const subjectId = (subjectInput ? subjectInput.value.trim() : '') || '042-S08-014';
  const pill = $('#risk-pill');
  const score = $('#risk-score');
  const fill = $('#risk-fill');
  const summary = $('#risk-summary');
  const evidenceList = $('#risk-evidence');
  try {
    const data = await getJson(`/api/risk/predict?subject_id=${encodeURIComponent(subjectId)}`);
    const lvl = data.risk_level || 'Low';
    pill.textContent = lvl;
    pill.className = 'risk-pill ' + (lvl === 'Critical' ? 'critical' : lvl === 'High' ? 'high' : lvl === 'Moderate' ? 'moderate' : 'neutral');
    score.textContent = data.risk_score || 0;
    fill.style.width = `${Math.min(Math.max(Number(data.risk_score || 0), 0), 100)}%`;
    summary.textContent = data.summary || 'No risk summary available.';

    if (evidenceList) {
      const evidence = data.evidence || [];
      if (evidence.length === 0) {
        evidenceList.innerHTML = '<li class="risk-evidence-item"><strong>No high-risk safety signals flagged</strong><span>Baseline</span></li>';
      } else {
        evidenceList.innerHTML = evidence.map((item) => {
          const sevClass = (item.severity || 'low').toLowerCase();
          const valDisplay = item.value !== undefined && item.value !== null ? `(${item.value})` : '';
          return `<li class="risk-evidence-item ${sevClass}">
            <div>
              <strong>${escapeHtml(item.label || item.category || '')}</strong> ${escapeHtml(valDisplay)}
            </div>
            <span>${escapeHtml(item.category || '')} · ${escapeHtml(item.severity || '')}</span>
          </li>`;
        }).join('');
      }
    }
  } catch (error) {
    summary.textContent = error.message || 'Risk prediction unavailable.';
    if (evidenceList) evidenceList.innerHTML = '';
  }
}

async function loadRiskReplay() {
  const subjectInput = $('#replay-subject');
  const subjectId = (subjectInput ? subjectInput.value.trim() : '') || '042-S08-014';
  const list = $('#replay-list');
  const counter = $('#replay-counter');
  try {
    const data = await getJson(`/api/risk/replay?subject_id=${encodeURIComponent(subjectId)}`);
    const events = data.events || [];
    if (counter) counter.textContent = `${events.length} Events`;
    list.innerHTML = events.length
      ? events.map((event) => {
          const dom = event.domain || 'EVT';
          const val = event.value !== undefined && event.value !== null && event.value !== event.label ? ` = ${event.value} ${event.unit || ''}` : '';
          return `<li>
            <div class="replay-row">
              <span class="domain-badge ${dom}">${dom}</span>
              <span>${event.date || 'N/A'}</span>
            </div>
            <strong>${escapeHtml(event.label || dom)}${escapeHtml(val)}</strong>
            <small>${escapeHtml(event.source || '')}</small>
          </li>`;
        }).join('')
      : '<li>No replay events available.</li>';
  } catch (error) {
    list.innerHTML = `<li>${error.message || 'Replay unavailable.'}</li>`;
    if (counter) counter.textContent = '0 Events';
  }
}

$('#risk-run').addEventListener('click', loadRiskPrediction);
$('#replay-run').addEventListener('click', loadRiskReplay);
$('#risk-subject').addEventListener('keydown', (event) => { if (event.key === 'Enter') loadRiskPrediction(); });
$('#replay-subject').addEventListener('keydown', (event) => { if (event.key === 'Enter') loadRiskReplay(); });

const runCrewBtn = $('#run-crew');
if (runCrewBtn) runCrewBtn.addEventListener('click', runStage2Crew);

async function runStage3Watch() {
  const button = $('#run-watch');
  if (!button || !watchResults) return;
  button.disabled = true;
  button.innerHTML = 'Running surveillance <span>⏳</span>';
  try {
    const data = await getJson(`/api/stage3/report?cut=${cut.value}`);
    const budget = data.budget || {};
    const adversarial = data.adversarial_events || [];
    const openItems = data.open_items || [];
    const siteRisk = (data.site_risks || []).slice(0, 5);
    watchResults.classList.remove('hidden');
    watchResults.innerHTML = `
      <div class="watch-grid">
        <div class="watch-box"><span>Cuts</span><strong>${data.cuts ? data.cuts.length : 0}</strong></div>
        <div class="watch-box"><span>Findings</span><strong>${data.findings ? data.findings.length : 0}</strong></div>
        <div class="watch-box"><span>Adversarial</span><strong>${adversarial.length}</strong></div>
        <div class="watch-box"><span>Budget</span><strong>${budget.mode || 'FULL'}</strong></div>
      </div>
      <div class="watch-card">
        <h4>Top site risk ranking</h4>
        <ul class="watch-list">
          ${siteRisk.length ? siteRisk.map((item, index) => `<li><span class="watch-label">#${index + 1}</span>${item.site} · ${item.finding_count} findings</li>`).join('') : '<li>No site risk signals were detected.</li>'}
        </ul>
      </div>
      <div class="watch-card">
        <h4>Adversarial events</h4>
        <ul class="watch-list">
          ${adversarial.length ? adversarial.map((event) => `<li><span class="watch-label">${event.type}</span>Cut ${event.cut || 'n/a'} · ${event.reason || event.action || 'flagged for review'}</li>`).join('') : '<li>No adversarial events were detected in the current watch run.</li>'}
        </ul>
      </div>
      <div class="watch-card">
        <h4>Open escalations</h4>
        <ul class="watch-list">
          ${openItems.length ? openItems.map((item) => `<li><span class="watch-label">${item.status || 'PENDING'}</span>${item.decision_id || item.code || 'Escalation'} · ${item.subject || 'subject'} · age ${item.age_cuts || 0} cuts</li>`).join('') : '<li>All escalations are currently clear or no monitor responses are still pending.</li>'}
        </ul>
      </div>
    `;
  } catch (error) {
    watchResults.classList.remove('hidden');
    watchResults.innerHTML = `<div class="watch-card"><h4>Study Watch unavailable</h4><ul class="watch-list"><li>${error.message}</li></ul></div>`;
  } finally {
    button.disabled = false;
    button.innerHTML = 'Run surveillance <span>◌</span>';
  }
}

$('#run-watch')?.addEventListener('click', runStage3Watch);

loadSummary();
loadRiskPrediction();
loadRiskReplay();

