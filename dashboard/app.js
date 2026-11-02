'use strict';
const $ = id => document.getElementById(id);
const fullDate = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', dateStyle:'long', timeStyle:'short', hourCycle:'h23'});
const shortTime = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'});
const controlNames = {checking:'正在连接', ready:'远程协助可用', busy:'学生正在使用电脑', partial:'协助已响应，设备资料读取失败',
  denied:'协助认证未通过', unreachable:'网络在线，协助服务未响应', working:'协助任务正在进行',
  unavailable:'协助已连接，桌面暂不可用', unchecked:'等待读取', offline:'设备离线', unknown:'状态待确认'};
const present = value => value !== null && value !== undefined && value !== '';
const dateText = stamp => stamp ? fullDate.format(new Date(stamp)) : '暂无记录';
const networkName = online => online === true ? '在线' : online === false ? '离线' : '待确认';
const networkClass = online => online === true ? 'online' : online === false ? 'offline' : '';
let selected = '', sequence = 0, timer = 0, lastPayload = null, rosterKey = '';

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (present(text)) el.textContent = String(text);
  return el;
}
function relative(stamp) {
  if (!stamp) return '';
  const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(stamp)) / 60000));
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return minutes + ' 分钟前';
  if (minutes < 1440) return Math.floor(minutes/60) + ' 小时前';
  return Math.floor(minutes/1440) + ' 天前';
}
function gib(bytes) {
  if (!Number.isFinite(bytes)) return '';
  return (bytes / 1073741824).toLocaleString('zh-CN', {maximumFractionDigits:1});
}
function duration(seconds) {
  if (!Number.isFinite(seconds)) return '';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + ' 分钟';
  const hours = Math.floor(minutes/60);
  if (hours < 24) return hours + ' 小时 ' + minutes%60 + ' 分钟';
  return Math.floor(hours/24) + ' 天 ' + hours%24 + ' 小时';
}
function sleepTime(seconds, hibernate) {
  if (seconds === 0) return hibernate ? '无固定时限' : '从不';
  if (seconds > 31536000) return '约 ' + Math.round(seconds/31536000) + ' 年';
  if (seconds < 60) return seconds + ' 秒';
  return seconds % 3600 === 0 ? seconds/3600 + ' 小时' : Math.round(seconds/60) + ' 分钟';
}
function powerPair(pair, format) {
  if (!pair) return '';
  const ac = format(pair.ac), dc = format(pair.dc);
  return ac === dc ? '插电与电池均为' + ac : '插电时' + ac + '，用电池时' + dc;
}
function facts(rows) {
  const dl = node('dl','facts');
  for (const [label,value] of rows) {
    if (!present(value)) continue;
    const row = node('div','fact');
    row.append(node('dt','',label),node('dd','',value));
    dl.append(row);
  }
  return dl;
}
function panel(title, content, note='') {
  if (!content.childElementCount) return null;
  const section = node('section','panel'), head = node('div','section-head');
  head.append(node('h3','',title));
  if (note) head.append(node('span','section-note',note));
  section.append(head,content);
  return section;
}
function fold(key, title, content) {
  const el = node('details','fold');
  el.dataset.key = key;
  el.append(node('summary','',title),content);
  return el;
}
function stamp(label, value, note, isTime) {
  const el = node('div','stamp');
  el.append(node('span','stamp-label',label));
  const strong = node(isTime && value ? 'time':'strong','',isTime ? dateText(value) : value);
  if (isTime && value) strong.dateTime = value;
  el.append(strong);
  if (note) el.append(node('span','section-note',note));
  return el;
}
function diskRows(drives=[]) {
  const list = node('div','disk-list');
  for (const disk of drives) {
    if (!(disk.Size > 0) || !Number.isFinite(disk.FreeSpace)) continue;
    const used = Math.max(0, Math.min(100, (1-disk.FreeSpace/disk.Size)*100));
    const item = node('div','disk-row'), line = node('div','disk-heading');
    line.append(node('span','disk-name',disk.DeviceID),
      node('span','disk-meta','可用 ' + gib(disk.FreeSpace) + ' / ' + gib(disk.Size) + ' GiB'));
    const bar = node('progress');
    bar.max = 100; bar.value = used;
    bar.setAttribute('aria-label',disk.DeviceID + ' 已用 ' + Math.round(used) + '%');
    bar.title = '已用 ' + Math.round(used) + '%';
    item.append(line,bar); list.append(item);
  }
  return list;
}
function profile(device, detail) {
  const inv = detail.inventory, sheet = node('article','sheet'), lead = node('header','lead');
  const identity = node('div','identity'), state = networkClass(device.online);
  const badge = node('span','status ' + state);
  badge.append(node('i','dot ' + state),document.createTextNode(networkName(device.online)));
  identity.append(node('h2','',device.name),badge); lead.append(identity);
  if (device.online) {
    const note = detail.controlAt ? shortTime.format(new Date(detail.controlAt)) + ' 检查' : '';
    lead.append(stamp('协助状态', controlNames[detail.control] || '待确认', note, false));
  } else {
    lead.append(stamp(device.approximate ? '最近确认在线' : '最后在线', device.lastSeen, relative(device.lastSeen), true));
  }
  if (detail.control === 'busy') lead.append(node('p','section-note','检测到鼠标或键盘活动，设备资料暂用上次记录。'));
  if (detail.control === 'partial' || detail.control === 'unreachable' || detail.control === 'denied')
    lead.append(node('p','section-note',detail.capturedAt ? '下方显示上次成功读取的资料。' : '本次未取得设备资料。'));
  sheet.append(lead);
  const memory = inv.TotalMemory ? (Number.isFinite(inv.MemoryAvailable) ?
    '可用 ' + gib(inv.MemoryAvailable) + ' / ' + gib(inv.TotalMemory) + ' GiB' : gib(inv.TotalMemory) + ' GiB') : '';
  const gpu = (inv.GPUs || []).map(v => v.Name).filter(Boolean).join('、');
  const resolution = [...new Set((inv.GPUs || []).filter(v => v.CurrentHorizontalResolution && v.CurrentVerticalResolution)
    .map(v => v.CurrentHorizontalResolution + ' × ' + v.CurrentVerticalResolution))].join('、');
  const systems = facts([
    ['电脑名称',inv.ComputerName],['操作系统',inv.OS?.replace(/^Microsoft\s+/i,'') || (device.os === 'windows' ? 'Windows' : device.os)],
    ['Windows 版本',[inv.OSVersion,inv.Architecture?.replace(/(\d+)-bit/i,'$1 位')].filter(Boolean).join(' · ')],['Windows 账户',inv.UserName],
    ['协助进程权限',typeof inv.Administrator === 'boolean' ? (inv.Administrator ? '管理员' : '普通用户') : ''],
    ['设备型号',[inv.Manufacturer,inv.Model].filter(Boolean).join(' ')],['处理器',inv.CPU],
    ['逻辑处理器',inv.Threads ? inv.Threads + ' 个' : ''],['CPU 占用',Number.isFinite(inv.CpuLoad) ? Math.round(inv.CpuLoad) + '%' : ''],
    ['内存',memory],['显卡',gpu],['屏幕分辨率',resolution],['上次开机',inv.BootTime ? dateText(inv.BootTime) : ''],
    ['采集时已开机',duration(inv.UptimeSeconds)]
  ]);
  const sampleNote = detail.capturedAt ? (detail.control === 'ready' ? '资料采集于 ' : '上次资料采集于 ') + dateText(detail.capturedAt) : '尚无配置采集记录';
  const overview = panel('设备概况',systems,sampleNote);
  if (overview) sheet.append(overview);
  else sheet.append(node('p','panel section-note',sampleNote));
  const disks = panel('磁盘空间',diskRows(inv.Drives),'横条表示已用容量');
  if (disks) sheet.append(disks);
  const lids = ['不采取操作','睡眠','休眠','关机'];
  const power = panel('电源与合盖',facts([
    ['供电方式',({Online:'已接电源',Offline:'使用电池'})[inv.PowerLine]],
    ['电池电量',Number.isFinite(inv.Battery) && inv.Battery <= 100 ? inv.Battery + '%' : ''],
    ['合盖动作',powerPair(inv.Lid,v=>lids[v] || '未知')],
    ['自动睡眠',powerPair(inv.Sleep,v=>sleepTime(v,false))],['自动休眠',powerPair(inv.Hibernate,v=>sleepTime(v,true))]
  ]));
  if (power) sheet.append(power);
  const appState = typeof inv.AiwenInstalled === 'boolean' ? (inv.AiwenInstalled ? '已安装' : '未检测到') :
    detail.installedAt ? '已安装' : '';
  const learning = panel('教学软件',facts([
    ['爱问云',appState],['登录记录',({unconfirmed:'尚未确认',confirmed:'已确认登录'})[detail.loginRecord]],
    ['采集时状态',typeof inv.AiwenRunning === 'boolean' ? (inv.AiwenRunning ? '正在运行':'未运行') : '']
  ]),typeof inv.AiwenInstalled !== 'boolean' && detail.installedAt ? '安装确认于 ' + dateText(detail.installedAt) : '');
  if (learning) sheet.append(learning);
  const taskNames = {Running:'已启动',Ready:'已启用，等待运行',Disabled:'已停用',Queued:'等待启动',Unknown:'状态未知'};
  const task = inv.AssistTasks?.find(t => t.Name === 'RemoteWindowsAssist-' + device.id);
  const links = (inv.NetworkAdapters || []).map(a=>[a.Name,a.LinkSpeed].filter(Boolean).join(' · ')).join('、');
  sheet.append(fold('network','连接详情',facts([
    ['协助网络地址',device.address],['设备编号',device.id],['协助响应耗时',Number.isFinite(detail.responseMs) ? detail.responseMs + ' 毫秒' : ''],['物理网卡',links],
    ['自动连接任务',task ? (taskNames[task.State] || task.State) : (inv.AssistTasks ? '未检测到' : '')],
    ['Windows 会话',inv.SessionId]
  ])));
  if (inv.Apps) {
    const list = node('ul','software-list');
    for (const app of inv.Apps) {
      const row = node('li');
      row.append(node('span','',app.Name),node('small','',app.Version || '')); list.append(row);
    }
    sheet.append(fold('software','已登记的桌面软件 · ' + inv.Apps.length + ' 项',list));
  }
  return sheet;
}
function render(payload, lost=false) {
  const rows = payload.devices, detail = payload.detail;
  const item = rows.find(d=>d.id === detail?.id);
  const oldSelected = selected;
  selected = item?.id || '';
  const warning = $('warning');
  warning.hidden = payload.networkOk && !lost;
  warning.textContent = lost ? '无法连接本机状态页。屏幕上保留的是上次读取的记录。' :
    '本机未能读取协助网络状态，当前在线情况待确认。';
  $('clock').textContent = payload.checkedAt ? '最近检查 ' + shortTime.format(new Date(payload.checkedAt)) : '';
  $('total').textContent = rows.length + ' 台';
  $('counts').textContent = payload.networkOk ? rows.filter(d=>d.online).length + ' 台在线 · ' +
    rows.filter(d=>d.online === false).length + ' 台离线' : '在线情况待确认';
  const key = JSON.stringify([selected,rows.map(d=>[d.id,d.name,d.online])]);
  if (key !== rosterKey) {
    const list = document.createDocumentFragment();
    for (const d of rows) {
      const btn = node('button','device-button'), main = node('span','device-main');
      btn.type='button'; btn.setAttribute('aria-current',String(d.id===selected)); btn.title=d.name;
      main.append(node('i','dot '+networkClass(d.online)),node('span','device-name',d.name));
      btn.append(main,node('span','device-state',networkName(d.online)));
      btn.addEventListener('click',()=>load(d.id)); list.append(btn);
    }
    $('devices').replaceChildren(list); rosterKey = key;
  }
  const box = $('profile');
  const open = oldSelected===selected ? [...box.querySelectorAll('details[open]')].map(d=>d.dataset.key) : [];
  const focusedKey = box.contains(document.activeElement) ? document.activeElement.closest('details')?.dataset.key : null;
  const oldScroll = box.querySelector('.software-list')?.scrollTop || 0;
  box.replaceChildren(item ? profile(item,detail) : node('p','empty',payload.networkOk ?
    '尚未发现已配对的学生电脑。' : '等待取得设备列表。'));
  for (const d of box.querySelectorAll('details')) {
    d.open = open.includes(d.dataset.key);
    if (d.dataset.key === focusedKey) d.querySelector('summary').focus({preventScroll:true});
  }
  if (open.includes('software') && box.querySelector('.software-list')) box.querySelector('.software-list').scrollTop = oldScroll;
}
async function load(id=selected, manual=false) {
  clearTimeout(timer);
  const stamp = ++sequence;
  $('refresh').disabled = true;
  let delay = 15000;
  try {
    const q = new URLSearchParams();
    if (id) q.set('device',id);
    if (manual) q.set('refresh','1');
    const res = await fetch('/api/status?' + q, {cache:'no-store', signal:AbortSignal.timeout(11000)});
    if (!res.ok) throw new Error('status unavailable');
    const data = await res.json();
    if (stamp !== sequence) return;
    lastPayload = data; render(data);
    if (data.detail?.control === 'checking') delay = 2200;
  } catch {
    if (stamp !== sequence) return;
    const previous = lastPayload || {devices:[],detail:null};
    render({...previous,networkOk:false,devices:previous.devices.map(d=>({...d,online:null})),
      detail:previous.detail ? {...previous.detail,control:'unknown'} : null},true);
  } finally {
    if (stamp === sequence) {
      $('refresh').disabled = false;
      if (!document.hidden) timer = setTimeout(()=>load(),delay);
    }
  }
}
$('refresh').addEventListener('click',()=>load(selected,true));
document.addEventListener('visibilitychange',()=>{ if (document.hidden) clearTimeout(timer); else load(); });
load();
