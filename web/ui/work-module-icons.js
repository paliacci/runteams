/* Canonical module icons shared by desktop and public asset views. */
window.RunTeamsModuleIcons=(()=>{
  const titles={calendar:"日历",customers:"客户",meetings:"会议记录",publishing:"内容发布",experiments:"网站实验"};
  function icon(id) {
  const shapes={
    calendar:`<path fill="var(--icon-blue)" d="M3 6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3Zm3 3v9h12V9Z" fill-rule="evenodd"/><path fill="var(--icon-amber)" d="M7 1.5a1.5 1.5 0 0 1 1.5 1.5v3a1.5 1.5 0 0 1-3 0V3A1.5 1.5 0 0 1 7 1.5Zm10 0A1.5 1.5 0 0 1 18.5 3v3a1.5 1.5 0 0 1-3 0V3A1.5 1.5 0 0 1 17 1.5Z"/><path fill="var(--icon-green)" d="M8 11h3v3H8Zm5 0h3v3h-3ZM8 16h8v2H8Z"/>`,
    customers:`<circle fill="var(--icon-blue)" cx="17" cy="7.5" r="3"/><path fill="var(--icon-blue)" d="M13 13h4.5a4.5 4.5 0 0 1 4.5 4.5V20h-9Z"/><circle fill="var(--icon-green)" cx="8.5" cy="7" r="4"/><path fill="var(--icon-green)" d="M2 19a6.5 6.5 0 0 1 13 0v1H2Z"/><circle fill="var(--icon-amber)" cx="20" cy="3" r="2"/>`,
    meeting:`<path fill="var(--icon-blue)" d="M5 2h10l5 5v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Zm1 7v2h9V9Zm0 5v2h6v-2Zm0 4v2h6v-2Z" fill-rule="evenodd"/><path fill="var(--icon-amber)" d="M15 2v5h5Z"/><circle fill="var(--icon-red)" cx="18" cy="18" r="4"/>`,
    content:`<path fill="var(--icon-violet)" d="M5 2h10l5 5v6h-3V9H6v10h7v3H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z"/><path fill="var(--icon-blue)" d="M15 2v5h5Z"/><path fill="var(--icon-green)" d="M8 11h6v2H8Zm0 4h4v2H8Z"/><path fill="var(--icon-amber)" d="m18 13 5 5h-3.5v5h-3v-5H13Z"/>`,
    site:`<path fill="var(--icon-blue)" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 3a7 7 0 1 1 0 14 7 7 0 0 1 0-14Z" fill-rule="evenodd"/><path fill="var(--icon-green)" d="M12 2c-3 0-5 4.5-5 10s2 10 5 10v-3c-1 0-2-3-2-7s1-7 2-7Z"/><path fill="var(--icon-amber)" d="M2 10.5h20v3H2Z"/><circle fill="var(--icon-red)" cx="19.5" cy="4.5" r="3"/>`,
    general:`<path fill="var(--icon-blue)" d="m12 1 10 5.5-10 5.7L2 6.5Z"/><path fill="var(--icon-green)" d="m2 8.5 8.5 4.9v9L2 17.5Z"/><path fill="var(--icon-amber)" d="m22 8.5-8.5 4.9v9l8.5-4.9Z"/>`
  };
    const key=({meetings:"meeting",publishing:"content",experiments:"site"})[id]||id;
    return `<svg aria-hidden="true" viewBox="0 0 24 24">${shapes[key]||shapes.general}</svg>`;
  }
  return {icon,title:id=>titles[id]||id};
})();
