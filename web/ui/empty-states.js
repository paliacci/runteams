/* Empty-state illustrations share a 96 × 64 grid and inherit the surface foreground. */
window.RunTeamsEmptyStates = (() => {
  function illustration(content) {
    return `<svg viewBox="0 0 96 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" fill="none" stroke-linecap="round" stroke-linejoin="round">${content}</svg>`;
  }

  const lens = `<circle cx="62" cy="40" r="10" fill="var(--surface)" stroke="currentColor" stroke-width="2.5"/>
    <circle cx="62" cy="40" r="8" fill="currentColor" opacity=".12"/>
    <path d="m70 48 7 7" stroke="currentColor" stroke-width="3.5"/>`;
  const document = `<path d="M28 10h26l11 11v28a4 4 0 0 1-4 4H28a4 4 0 0 1-4-4V14a4 4 0 0 1 4-4Z" fill="currentColor" fill-opacity=".10" stroke="currentColor" stroke-opacity=".75" stroke-width="2"/>
    <path d="M54 11v10h10M33 29h17m-17 9h12" stroke="currentColor" stroke-width="2.5" opacity=".66"/>`;
  const skill = `<rect x="23" y="13" width="44" height="38" rx="7" fill="currentColor" fill-opacity=".10" stroke="currentColor" stroke-opacity=".75" stroke-width="2"/>
    <path d="m43 21 3.8 7.2 7.2 3.8-7.2 3.8L43 43l-3.8-7.2L32 32l7.2-3.8Z" fill="currentColor" opacity=".78"/>`;
  const art = {
    records: illustration(`
      <rect x="24" y="12" width="49" height="39" rx="6" fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-opacity=".76" stroke-width="2"/>
      <path d="M24 22h49" stroke="currentColor" stroke-opacity=".34" stroke-width="2"/>
      <rect x="31" y="16" width="12" height="3" rx="1.5" fill="currentColor" opacity=".64"/>
      <path d="M34 31v11" stroke="currentColor" stroke-opacity=".52" stroke-width="2"/>
      <g fill="currentColor"><circle cx="34" cy="31" r="3"/><circle cx="34" cy="42" r="3" opacity=".67"/></g>
      <path d="M43 31h19m-19 11h13" stroke="currentColor" stroke-width="3" opacity=".68"/>`),
    documents: illustration(`
      <path d="M15 22a4 4 0 0 1 4-4h17l6 6h31a4 4 0 0 1 4 4v20H15Z" fill="currentColor" fill-opacity=".16" stroke="currentColor" stroke-width="1.8" stroke-opacity=".58"/>
      <path d="M40 11h18l8 8v21H37V14a3 3 0 0 1 3-3Z" fill="var(--surface)" stroke="currentColor" stroke-width="1.8"/>
      <path d="M58 12v7h7m-22 5h14" stroke="currentColor" stroke-width="1.7" opacity=".65"/>
      <path d="M17 30h60a3 3 0 0 1 3 4l-4 16a4 4 0 0 1-4 3H22a4 4 0 0 1-4-3l-4-16a3 3 0 0 1 3-4Z" fill="var(--surface)" stroke="currentColor" stroke-width="1.8"/>
      <path d="M18 31h58l-5 21H23Z" fill="currentColor" fill-opacity=".13"/>
      <path d="M39 41h15" stroke="currentColor" stroke-width="2.5" opacity=".72"/>`),
    archive: illustration(`
      <path d="M21 23h54v25a4 4 0 0 1-4 4H25a4 4 0 0 1-4-4Z" fill="currentColor" fill-opacity=".10" stroke="currentColor" stroke-opacity=".78" stroke-width="1.7"/>
      <rect x="18" y="15" width="60" height="10" rx="3" fill="var(--surface)" stroke="currentColor" stroke-width="1.7"/>
      <rect x="19" y="16" width="58" height="8" rx="2" fill="currentColor" opacity=".16"/>
      <rect x="39" y="32" width="18" height="3" rx="1.5" fill="currentColor" opacity=".64"/>`),
    railEmployees: illustration(`
      <rect x="18" y="14" width="60" height="38" rx="6" fill="currentColor" fill-opacity=".10" stroke="currentColor" stroke-opacity=".75" stroke-width="2"/>
      <circle cx="36" cy="28" r="5" fill="currentColor" opacity=".74"/>
      <path d="M26 42c0-5 4-8 10-8s10 3 10 8Z" fill="currentColor" opacity=".54"/>
      <path d="M53 28h15m-15 9h10" stroke="currentColor" stroke-width="3" opacity=".7"/>`),
    employeeVersions: illustration(`
      <path d="M23 22v25a6 6 0 0 0 6 6h33" stroke="currentColor" stroke-width="2" opacity=".45"/>
      <rect x="29" y="12" width="44" height="35" rx="5" fill="currentColor" fill-opacity=".10" stroke="currentColor" stroke-opacity=".76" stroke-width="2"/>
      <path d="M56 13h10v15l-5-3-5 3Z" fill="currentColor" opacity=".65"/>
      <path d="M37 25h10m-10 10h22" stroke="currentColor" stroke-width="2.5" opacity=".66"/>`),
    responsibilities: illustration(`
      <rect x="27" y="14" width="42" height="40" rx="5" fill="currentColor" fill-opacity=".10" stroke="currentColor" stroke-width="2" stroke-opacity=".76"/>
      <rect x="38" y="10" width="20" height="8" rx="3" fill="var(--surface)" stroke="currentColor" stroke-width="2"/>
      <path d="m34 29 3 3 5-6m-8 16 3 3 5-6M48 30h12m-12 13h10" stroke="currentColor" stroke-width="2.4" opacity=".75"/>`),
    channels: illustration(`
      <g fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-width="2" stroke-opacity=".76"><rect x="15" y="17" width="24" height="30" rx="5"/><rect x="57" y="17" width="24" height="30" rx="5"/></g>
      <path d="m30 26-6 6 6 6m36-12 6 6-6 6M39 32h18" stroke="currentColor" stroke-width="2.5"/>
      <circle cx="48" cy="32" r="3" fill="currentColor"/>`),
    skills: illustration(skill),
    skillAuthor: illustration(`${skill}
      <circle cx="65" cy="45" r="10" fill="var(--surface)" stroke="currentColor" stroke-width="2"/>
      <path d="M60 45h10m-5-5v10" stroke="currentColor" stroke-width="2.5"/>`),
    documentsSearch: illustration(document + lens),
    skillsSearch: illustration(skill + lens),
    globalSearch: illustration(`
      <rect x="17" y="15" width="56" height="33" rx="6" fill="currentColor" fill-opacity=".10" stroke="currentColor" stroke-width="2" stroke-opacity=".76"/>
      <path d="M26 25h23m-23 9h14" stroke="currentColor" stroke-width="3" opacity=".64"/>${lens}`),
    trash: illustration(`
      <path d="m29 23 2 26a4 4 0 0 0 4 4h26a4 4 0 0 0 4-4l2-26Z" fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-width="2" stroke-opacity=".76"/>
      <path d="M23 21h50m-32-1v-4a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v4" stroke="currentColor" stroke-width="2.5"/>
      <path d="M42 31v13m12-13v13" stroke="currentColor" stroke-width="2.6" opacity=".6"/>`),
  };

  const devicePair = `
    <rect x="14" y="16" width="49" height="31" rx="4" fill="currentColor" fill-opacity=".10" stroke="currentColor" stroke-width="2" stroke-opacity=".76"/>
    <path d="M12 50h43m-25-7h14" stroke="currentColor" stroke-width="2.5" opacity=".65"/>
    <rect x="57" y="20" width="23" height="34" rx="4" fill="var(--surface)" stroke="currentColor" stroke-width="2"/>
    <rect x="60" y="24" width="17" height="23" rx="2" fill="currentColor" opacity=".14"/>
    <path d="M66 50h5" stroke="currentColor" stroke-width="1.8" opacity=".7"/>`;
  art.mobileGuest = illustration(`${devicePair}
    <circle cx="37" cy="26" r="4.5" fill="currentColor" opacity=".78"/>
    <path d="M28 38c0-4 4-7 9-7s9 3 9 7Z" fill="currentColor" opacity=".56"/>`);
  art.devices = illustration(`${devicePair}
    <path d="M24 26h20m-20 8h12" stroke="currentColor" stroke-width="2.5" opacity=".57"/>
    <path d="M64 35h9m-4.5-4.5v9" stroke="currentColor" stroke-width="2"/>`);

  // Draw on the overview's 96px grid so outlines stay legible at the displayed size.
  art.automations = `<svg aria-hidden="true" focusable="false" viewBox="0 0 96 64" xmlns="http://www.w3.org/2000/svg" fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M68 29.3A14 14 0 0 0 52.9 50H25a6 6 0 0 1-6-6V19a6 6 0 0 1 6-6h37a6 6 0 0 1 6 6Z" fill="currentColor" fill-opacity=".1"/>
    <path d="M19 24v-5a6 6 0 0 1 6-6h37a6 6 0 0 1 6 6v5Z" fill="currentColor" fill-opacity=".14"/>
    <path d="M52 50H25a6 6 0 0 1-6-6V19a6 6 0 0 1 6-6h37a6 6 0 0 1 6 6v10" stroke="currentColor" stroke-opacity=".74" stroke-width="2"/>
    <path d="M31 10v6m25-6v6" stroke="currentColor" stroke-width="3"/>
    <g fill="currentColor">
      <rect x="27" y="29" width="7" height="6" rx="2" opacity=".78"/>
      <rect x="39" y="30" width="6" height="4" rx="2" opacity=".38"/>
      <rect x="27" y="39" width="6" height="4" rx="2" opacity=".38"/>
      <rect x="39" y="39" width="6" height="4" rx="2" opacity=".38"/>
    </g>
    <circle cx="65" cy="43" r="11" fill="currentColor" fill-opacity=".18" stroke="currentColor" stroke-width="2"/>
    <path d="M65 37v6l4 3" stroke="currentColor" stroke-width="2"/>
  </svg>`;

  const titles = {
    railEmployees: "还没有员工",
    trash: "垃圾箱是空的",
    archive: "文件包里没有文件",
    documentsSearch: "\u6ca1\u6709\u5339\u914d\u7684\u6587\u6863",
    skillsSearch: "\u6ca1\u6709\u5339\u914d\u7684\u6280\u80fd",
    globalSearch: "未找到相关结果",
    skillAuthor: "你想创建什么技能？",
    employeeVersions: "尚无已发布版本",
    automations: "还没有自动化",
    documents: '还没有文档',
    skills: '还没有自己的技能',
    records: '还没有工作记录',
    channels: '还未连接模型渠道',
    responsibilities: '尚未选用工作技能'
  };
  function markup(kind, {hidden = false, title: titleOverride, titleKey} = {}) {
    if (!Object.hasOwn(titles,kind)) return '';
    const escape=value=>String(value).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const title=titleOverride===undefined?titles[kind]:escape(titleOverride);
    return `<div class="rt-empty-state rt-empty-state--${kind}" data-empty-state="${kind}"${kind === 'skills' ? ' data-skills-empty' : ''}${hidden ? ' hidden' : ''} role="status"><div class="rt-empty-state-art">${artwork(kind)}</div><div class="rt-empty-state-copy"><b${titleKey?` data-app-i18n="${escape(titleKey)}"`:""}>${title}</b></div></div>`;
  }
  function artwork(kind){return Object.hasOwn(art,kind)?art[kind]:'';}
  function register(entries){for(const [kind,value] of Object.entries(entries)){if(Object.hasOwn(titles,kind)||typeof value.title!=='string'||typeof value.art!=='string')throw Error('Invalid empty-state contribution: '+kind);titles[kind]=value.title;art[kind]=value.art;}}
  return Object.freeze({markup,artwork,register});
})();
