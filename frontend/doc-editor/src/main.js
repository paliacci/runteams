/* RunTeams 文档编辑器：Milkdown Crepe（ProseMirror 内核）的薄封装。
   对外只暴露 mount()，产品里的调用方只管 markdown 进、markdown 出。
   样式变量在 web/runteams.css 里按我们自己的设计令牌覆盖。 */
import { CrepeBuilder } from "@milkdown/crepe/builder";
import { languages } from "@codemirror/language-data";
import { EditorView as CodeMirrorView } from "@codemirror/view";
import { commandsCtx, editorViewCtx, remarkStringifyOptionsCtx } from "@milkdown/kit/core";
import {
  addBlockTypeCommand,
  clearTextInCurrentBlockCommand,
  headingAttr,
  headingSchema,
  liftListItemCommand,
  linkSchema,
  paragraphSchema,
  paragraphAttr,
  setBlockTypeCommand,
  wrapInBlockTypeCommand,
} from "@milkdown/kit/preset/commonmark";
import { extendListItemSchemaForTask } from "@milkdown/kit/preset/gfm";
import { lift, toggleMark } from "@milkdown/kit/prose/commands";
import { TextSelection } from "@milkdown/kit/prose/state";
import { Plugin, PluginKey } from "@milkdown/kit/prose/state";
import { Decoration, DecorationSet } from "@milkdown/kit/prose/view";
import { $prose } from "@milkdown/kit/utils";
import { blockEdit } from "@milkdown/crepe/feature/block-edit";
import { codeMirror } from "@milkdown/crepe/feature/code-mirror";
import { imageBlock } from "@milkdown/crepe/feature/image-block";
import { listItem } from "@milkdown/crepe/feature/list-item";
import { placeholder } from "@milkdown/crepe/feature/placeholder";
import { table } from "@milkdown/crepe/feature/table";
import { trailingConfig } from "@milkdown/kit/plugin/trailing";
import { AlignLeft, Bold, Braces, Copy, Italic, Link, Link2, List, ListOrdered, ListTodo, Palette, Scissors, Strikethrough, Trash2, Type, Underline } from "lucide";
/* 只引我们真的开了的那几块样式：common/style.css 会把 latex.css 一起拖进来，
   而 latex.css @import 了 katex 的字体，我们没开公式功能，没必要背这个包。 */
import "@milkdown/crepe/theme/common/prosemirror.css";
import "@milkdown/crepe/theme/common/reset.css";
import "@milkdown/crepe/theme/common/block-edit.css";
import "@milkdown/crepe/theme/common/code-mirror.css";
import "@milkdown/crepe/theme/common/image-block.css";
import "@milkdown/crepe/theme/common/list-item.css";
import "@milkdown/crepe/theme/common/placeholder.css";
import "@milkdown/crepe/theme/common/table.css";
import "@milkdown/crepe/theme/frame.css";

const lucideInner = (icon) => icon.map(([tag, attrs]) => `<${tag} ${Object.entries(attrs).map(([key, value]) => `${key}="${value}"`).join(" ")}></${tag}>`).join("");
const lucideSvg = (icon) => `<svg class="runteams-lucide-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${lucideInner(icon)}</svg>`;

// Feishu-style list headings keep the list container and change the block
// inside each item. CommonMark's default list item requires a paragraph as
// its first child, which prevents `- ## heading` from being represented. Keep
// the GFM task-list attributes and serializers, but allow any block first.
const listItemBlockSchema = extendListItemSchemaForTask.extendSchema((prev) => (ctx) => {
  const base = prev(ctx);
  return {
    ...base,
    attrs: {
      ...base.attrs,
      align: { default: "left" },
      color: { default: "" },
      background: { default: "" },
      indent: { default: 0 },
    },
    content: "block+",
  };
});
const styledParagraphSchema = paragraphSchema.extendSchema((prev) => (ctx) => {
  const base = prev(ctx);
  return {
    ...base,
    attrs: {
      ...base.attrs,
      align: { default: "left" },
      color: { default: "" },
      background: { default: "" },
      indent: { default: 0 },
    },
    toDOM: (node) => {
      const attrs = ctx.get(paragraphAttr.key)(node);
      const style = [
        node.attrs.align && node.attrs.align !== "left" ? `text-align:${node.attrs.align}` : "",
        node.attrs.color ? `color:${node.attrs.color}` : "",
        node.attrs.background ? `background-color:${node.attrs.background}` : "",
        Number(node.attrs.indent) > 0 ? `--runteams-block-indent:${Number(node.attrs.indent) * 24}px` : "",
      ].filter(Boolean).join(";");
      return ["p", { ...attrs, ...(style ? { style: `${style};` } : {}) }, 0];
    },
  };
});
// Keep heading formatting in the ProseMirror node itself.  A DOM-only style
// is lost whenever Milkdown redraws a heading (for example when the block
// menu closes), while node attrs survive that redraw and are serialized back
// into the live view immediately.
const styledHeadingSchema = headingSchema.extendSchema((prev) => (ctx) => {
  const base = prev(ctx);
  return {
    ...base,
    attrs: {
      ...base.attrs,
      align: { default: "left" },
      color: { default: "" },
      background: { default: "" },
      indent: { default: 0 },
    },
    toDOM: (node) => {
      const attrs = ctx.get(headingAttr.key)(node);
      const style = [
        node.attrs.align && node.attrs.align !== "left" ? `text-align:${node.attrs.align}` : "",
        node.attrs.color ? `color:${node.attrs.color}` : "",
        node.attrs.background ? `background-color:${node.attrs.background}` : "",
        Number(node.attrs.indent) > 0 ? `--runteams-block-indent:${Number(node.attrs.indent) * 24}px` : "",
      ].filter(Boolean).join(";");
      return [`h${node.attrs.level || 1}`, { ...attrs, ...(style ? { style: `${style};` } : {}) }, 0];
    },
  };
});

const linkIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M9.4 14.6a1 1 0 0 1 0-1.4l3.8-3.8a1 1 0 1 1 1.4 1.4l-3.8 3.8a1 1 0 0 1-1.4 0Zm-2.1 2.1-1.2 1.2a2.2 2.2 0 0 1-3.1-3.1l3.5-3.5a2.2 2.2 0 0 1 3.1 0 1 1 0 1 1-1.4 1.4.2.2 0 0 0-.3 0l-3.5 3.5a.2.2 0 0 0 0 .3.2.2 0 0 0 .3 0l1.2-1.2a1 1 0 1 1 1.4 1.4Zm8.2-9.4 1.2-1.2a2.2 2.2 0 0 1 3.1 3.1l-3.5 3.5a2.2 2.2 0 0 1-3.1 0 1 1 0 1 1 1.4-1.4.2.2 0 0 0 .3 0l3.5-3.5a.2.2 0 0 0 0-.3.2.2 0 0 0-.3 0l-1.2 1.2a1 1 0 0 1-1.4-1.4Z"/>
  </svg>`;

const copyIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M8 8V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2h3Zm2-3v3h4a2 2 0 0 1 2 2v4h3V5h-9ZM5 10v9h8v-9H5Z"/>
  </svg>`;

const deleteIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M7 21a2 2 0 0 1-2-2V7h14v12a2 2 0 0 1-2 2H7ZM6 5V3h5l1 1h5v1H6Zm3 5v8h2v-8H9Zm4 0v8h2v-8h-2Z"/>
  </svg>`;

const cutIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="m7.2 8.2 6.1 3.3 3.1-3.1a3 3 0 1 1 1.4 1.4l-3.1 3.1 3.1 3.1a3 3 0 1 1-1.4 1.4l-3.1-3.1-6.1 3.3A3.5 3.5 0 1 1 6.4 16l5.5-3-5.5-3A3.5 3.5 0 1 1 7.2 8.2Zm-1.7-.7a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Zm0 7.9a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Zm11.6-7.9a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Zm0 7.9a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z"/>
  </svg>`;

const copyLinkIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M10.6 13.4a1 1 0 0 1 0-1.4l2.8-2.8a3 3 0 1 1 4.2 4.2l-2 2a3 3 0 0 1-4.2 0 1 1 0 0 1 1.4-1.4 1 1 0 0 0 1.4 0l2-2a1 1 0 1 0-1.4-1.4L12 13.4a1 1 0 0 1-1.4 0Zm2.8-2.8a1 1 0 0 1 0 1.4l-2.8 2.8a3 3 0 1 1-4.2-4.2l2-2a3 3 0 0 1 4.2 0 1 1 0 0 1-1.4 1.4 1 1 0 0 0-1.4 0l-2 2a1 1 0 1 0 1.4 1.4l2.8-2.8a1 1 0 0 1 1.4 0Z"/>
  </svg>`;

const alignIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M3 5h18v2H3V5Zm0 4h12v2H3V9Zm0 4h18v2H3v-2Zm0 4h12v2H3v-2Z"/>
  </svg>`;

const colorIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3a9 9 0 1 0 0 18h1.3a2.7 2.7 0 0 0 0-5.4H12a1 1 0 0 1 0-2h2.2A6.8 6.8 0 0 0 12 3Zm-4 8a1.4 1.4 0 1 1 0-2.8A1.4 1.4 0 0 1 8 11Zm3-3a1.4 1.4 0 1 1 0-2.8A1.4 1.4 0 0 1 11 8Zm4 0a1.4 1.4 0 1 1 0-2.8A1.4 1.4 0 0 1 15 8Zm2 3a1.4 1.4 0 1 1 0-2.8A1.4 1.4 0 0 1 17 11Z"/>
  </svg>`;

const boldIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M7 4h6.2a4 4 0 0 1 2.1 7.4A4.2 4.2 0 0 1 13.5 20H7V4Zm3 2.5v4h3a2 2 0 1 0 0-4h-3Zm0 6.5v4.5h3.5a2.25 2.25 0 1 0 0-4.5H10Z"/>
  </svg>`;

const italicIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M10 4h9v2.5h-3.1l-4.2 11H15V20H6v-2.5h3.1l4.2-11H10V4Z"/>
  </svg>`;

const lucideLinkIcon = lucideSvg(Link);
const lucideCopyLinkIcon = lucideSvg(Link2);
const lucideToolbarIcons = {
  text: lucideSvg(Type),
  align: lucideSvg(AlignLeft),
  bold: lucideSvg(Bold),
  strike: lucideSvg(Strikethrough),
  italic: lucideSvg(Italic),
  underline: lucideSvg(Underline),
  link: lucideLinkIcon,
  code: lucideSvg(Braces),
  color: lucideSvg(Palette),
};
const lucideMenuPaths = {
  Code: lucideInner(Braces),
  "Ordered List": lucideInner(ListOrdered),
  "Bullet List": lucideInner(List),
  "Task List": lucideInner(ListTodo),
};

/*
 * Milkdown's Markdown URL parser intentionally strips unknown protocols.  Keep
 * the product-facing link contract (`runteams://document/<id>`, with the old
 * `artifact://<id>` form accepted) while the editor is mounted by using the
 * same-origin route as a safe editing alias.  The conversion is reversible,
 * so saved Markdown and Agent tool output still have one canonical form.
 */
function toEditorMarkdown(value) {
  return String(value || "").replace(
    /\]\(((?:runteams:\/\/document\/\d+|artifact:\/\/\d+))((?:#[^\s)]+)?)(\s+[^)]*)?\)/gi,
    (_match, href, anchor = "", suffix = "") => {
      const id = href.match(/\d+/)?.[0];
      return id ? `](/docs?document=${id}${anchor}${suffix})` : _match;
    },
  );
}

function fromEditorMarkdown(value) {
  return String(value || "").replace(
    /\]\(\/docs\?document=(\d+)(#[^\s)]+)?(\s+[^)]*)?\)/gi,
    (_match, id, anchor = "", suffix = "") => `](runteams://document/${id}${anchor}${suffix})`,
  );
}

// ProseMirror anchors are created after the editor mounts and do not inherit
// the static reader's link attributes.  Mark real document/external links up
// front so a click always opens a separate tab; the host page also keeps a
// capture handler for links created later while editing.
function prepareEditorLinks(root) {
  root?.querySelectorAll?.("a[href]").forEach((link) => {
    const href = String(link.getAttribute("href") || "").trim();
    if (!href || href.startsWith("#")) return;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  });
}

// 块句柄的加号是一个轻量入口：悬停即可预览菜单，点击仍然走同一套原生事件。
// 通过宿主层委派事件实现，避免把产品交互绑定在 vendor 构建产物的局部实现上。
function bindBlockMenuHover(root, openMenuAt = null, getBlockLabel = null, openSubmenu = null) {
  if (!root?.addEventListener) return () => {};
  // Guard containment checks while Vue recycles the shared handle. A
  // transient non-DOM event target must not abort menu synchronisation.
  const isDomNode = (value) => !!value && typeof value === "object"
    && typeof value.nodeType === "number";
  const containsDomNode = (container, value) => isDomNode(value)
    && !!container?.contains?.(value);
  const delegatedSubmenuPointerUp = (event) => {
    const row = event.target?.closest?.(' .milkdown-slash-menu li[data-runteams-submenu="true"]'.trim());
    if (!row || !openSubmenu) return;
    const kind = row.textContent?.trim() === "颜色选项" ? "color" : "align";
    event.preventDefault();
    event.stopImmediatePropagation();
    openSubmenu(kind);
  };
  // Milkdown renders the slash menu in a document-level portal, outside the
  // editor root. Delegate from document so the handler receives portal
  // events, while keeping the ownership and cleanup inside this editor.
  document.addEventListener("pointerup", delegatedSubmenuPointerUp, true);
  let revealFrame = 0;
  let hoverTimer = 0;
  let leaveTimer = 0;
  let revealFallbackTimer = 0;
  let openingTarget = null;
  let lastTarget = null;
  // The block handle is a single recycled DOM node. A row change can happen
  // without changing `lastTarget`, so identity alone cannot invalidate the
  // previous menu's delayed reveal callbacks.
  let hoverGeneration = 0;
  let lastHoverBlockSignature = "";
  let menuActiveBlock = null;
  let menuRowHighlightLayer = null;
  // A style command is a short transaction: the menu provider may keep its
  // old DOM mounted while ProseMirror re-renders the block. Suppress the
  // independent row highlight during that hand-off so it cannot be painted
  // at the pre-alignment coordinates for one or more frames.
  let suppressMenuRowHighlight = false;
  let styleHighlightSuppressionTimer = null;
  let menuRowStackingBlock = null;
  let menuRowStackingPosition = "";
  let menuRowStackingZIndex = "";
  let pendingMenuBlock = null;
  let pendingMenuBlockSignature = "";
  // The compact button follows the mouse row even when the editor has not
  // received input focus. Keep the last block under the pointer so entering
  // the button/menu itself does not make the anchor disappear for one frame.
  let pointerBlock = null;
  // Resolving a block label through ProseMirror can briefly return the
  // fallback `T` while the caret/handle is being repositioned. Cache the
  // label for the same visual block so horizontal caret movement never makes
  // the compact button flash between two labels.
  let labelBlock = null;
  let stableBlockLabel = "";
  // Visibility is driven by the pointer being over the editor surface. This
  // prevents the last caret row from resurrecting the handle after the pointer
  // has moved into the header, outline, or another pane.
  let pointerInEditorSurface = false;
  let lastActivePosition = null;
  let lastActivePositionAt = 0;
  const scheduleFrame = typeof requestAnimationFrame === "function"
    ? requestAnimationFrame
    : (callback) => setTimeout(callback, 16);
  const cancelFrame = typeof cancelAnimationFrame === "function"
    ? cancelAnimationFrame
    : clearTimeout;
  const syncMenuLeft = (menu, anchor = null) => {
    if (!menu) return;
    const layout = root.closest?.(".doc-reader-layout");
    const outline = layout?.querySelector?.(".doc-reader-outline-slot");
    const milkdown = root.querySelector?.(".milkdown");
    if (!outline || !milkdown) return;
    const editorRect = milkdown.getBoundingClientRect();
    const anchorRect = anchor?.getBoundingClientRect?.() || root.querySelector?.(".milkdown-block-handle .operation-item")?.getBoundingClientRect?.();
    // A hidden handle reports a zero rectangle. Never use that transient
    // value to rewrite the menu coordinates, or the menu will jump to the
    // viewport's first pixel while the button is disappearing.
    if (!anchorRect || anchorRect.width <= 0 || anchorRect.height <= 0) return;
    const menuWidth = Number.parseFloat(getComputedStyle(menu).width) || 168;
    // Keep the floating menu to the left of the plus handle whenever the
    // outline rail has room. This prevents the menu from intercepting the
    // hover that opens it; narrow layouts are clamped to the main pane edge.
    // Paint the menu in the viewport so the outline rail cannot clip its
    // left edge. The anchor still determines the side: it always opens to
    // the left of the style button.
    const preferredLeft = anchorRect.left - menuWidth - 2;
    // Never let the menu cross the app rail boundary. The outline can be
    // wider than the remaining main pane on narrow layouts, so clamp to the
    // `.mid` edge as the final authority.
    // Keep the menu's right edge at or before the hovered button's left edge,
    // while keeping the whole surface outside the left rail's stacking area.
    const rail = document.getElementById?.("rgRail");
    const railRect = rail?.getBoundingClientRect?.();
    const minLeft = railRect ? railRect.right + 8 : 8;
    // The style menu is intentionally always placed to the left of the
    // hovered button. Never flip it to the button's right side.
    const left = preferredLeft;
    if (Number.isFinite(left)) {
      // Floating UI may recalculate after the provider's debounce. Keep the
      // product placement in a custom property so the important CSS rule wins
      // over subsequent inline `left` writes from the third-party provider.
      menu.dataset.runteamsOutlinePosition = "true";
      menu.style.setProperty("z-index", "10080", "important");
      menu.style.setProperty("--runteams-menu-left", `${Math.round(left)}px`);

      // Anchor the menu to the active row instead of trusting the provider's
      // previous top coordinate. The provider reuses one DOM node while the
      // document scrolls, so that coordinate can still be technically inside
      // the viewport while belonging to a different row. Keep the menu
      // vertically centered on the hovered style button.
      const viewportHeight = typeof innerHeight === "number" ? innerHeight : 0;
      // The provider uses `display:none` while it is switching rows, so both
      // measurements can briefly be zero. The menu has a fixed compact layout
      // in this surface; use its rendered height as a last-resort measurement
      // so the first frame is positioned beside the current row as well.
      const measuredMenuHeight = Number(menu.offsetHeight)
        || Number(menu.getBoundingClientRect?.().height)
        || 0;
      // During the provider's first frame the unstyled menu can report a
      // much larger height than its final compact layout. Do not make the
      // flip decision from that transient value; the rendered menu on this
      // surface is 225px tall (and scrolls internally if it ever grows).
      const menuHeight = measuredMenuHeight > 0 && measuredMenuHeight <= 400
        ? measuredMenuHeight
        : 225;
      if (viewportHeight > 0 && menuHeight > 0) {
        const gap = 8;
        let desiredTop = anchorRect.top + (anchorRect.height - menuHeight) / 2;
        const maxTop = Math.max(gap, viewportHeight - menuHeight - gap);
        desiredTop = Math.max(gap, Math.min(desiredTop, maxTop));
        if (Number.isFinite(desiredTop)) menu.style.setProperty("--runteams-menu-top", `${Math.round(desiredTop)}px`);
      }
    }
  };
  const clearHoverTimer = () => {
    if (!hoverTimer) return;
    clearTimeout(hoverTimer);
    hoverTimer = 0;
  };
  const cancelReveal = () => {
    if (!revealFrame) return;
    cancelFrame(revealFrame);
    revealFrame = 0;
  };
  const clearLeaveTimer = () => {
    if (!leaveTimer) return;
    clearTimeout(leaveTimer);
    leaveTimer = 0;
  };
  const clearRevealFallback = () => {
    if (!revealFallbackTimer) return;
    clearTimeout(revealFallbackTimer);
    revealFallbackTimer = 0;
  };
  const hideMenu = (menu) => {
    if (!menu) return;
    menu.classList.add("is-repositioning");
    menu.style.setProperty("visibility", "hidden", "important");
  };
  const closeMenu = (menu) => {
    if (!menu) return;
    // A document submenu is a sibling surface. Keep the parent menu mounted
    // while the pointer travels from the parent row into that surface.
    if (document.querySelector("#docBlockAlignMenu,#docBlockColorMenu")) return;
    menu.removeAttribute("data-runteams-force-open");
    menu.dataset.show = "false";
    hideMenu(menu);
    clearMenuRowHighlight();
  };
  // Dismiss the mounted menu before a content click reaches ProseMirror. The
  // shared Milkdown menu may remain visible while a submenu is open; leaving
  // it as a hit target makes the next paragraph click look like a stuck caret.
  const dismissMenusForEditorPointer = (event) => {
    const editor = root.querySelector?.(".ProseMirror");
    if (!editor?.contains?.(event?.target)) return;
    if (event.target?.closest?.(
      ".milkdown-block-handle,.milkdown-slash-menu,#docBlockAlignMenu,#docBlockColorMenu,.doc-block-submenu,.doc-style-panel"
    )) return;
    document.getElementById("docBlockAlignMenu")?.remove();
    document.getElementById("docBlockColorMenu")?.remove();
    const menu = root.querySelector?.(".milkdown-slash-menu");
    if (menu) {
      menu.removeAttribute("data-runteams-force-open");
      menu.dataset.show = "false";
      menu.classList.add("is-repositioning");
      menu.style.setProperty("visibility", "hidden", "important");
      menu.style.setProperty("pointer-events", "none");
    }
    clearHoverTimer();
    cancelReveal();
    clearLeaveTimer();
    clearRevealFallback();
    openingTarget = null;
    lastTarget = null;
    clearMenuRowHighlight();
  };
  const revealMenu = (menu) => {
    if (!menu) return;
    menu.classList.remove("is-repositioning");
    menu.style.removeProperty("visibility");
    // A previous editor-pointer dismissal may have disabled hit testing on
    // the reusable menu node.  Visibility alone makes the menu look open but
    // leaves every row inert; every reveal must restore pointer events too.
    menu.style.removeProperty("pointer-events");
  };
  // The slash provider keeps one menu node mounted and repopulates its groups
  // asynchronously.  During that hand-off the node can briefly have a box
  // but no menu items, which otherwise paints as the blank rounded pill users
  // see when moving between rows.  Treat item content as the readiness gate
  // for every reveal path (hover, pointer bridge, and caret re-anchor).
  const menuHasRenderableContent = (menu) => {
    const groups = menu?.querySelector?.(".menu-groups");
    if (!groups) return false;
    return [...groups.querySelectorAll(".menu-group li")].some((item) => (
      item.querySelector("svg, img") || item.textContent?.trim()
    ));
  };
  const menuCanPaint = (menu) => {
    if (!menuHasRenderableContent(menu)) return false;
    const groups = menu?.querySelector?.(".menu-groups");
    const rect = groups?.getBoundingClientRect?.();
    // A populated menu may still be display:none while the provider switches
    // rows.  Let the next positioning frame try again instead of revealing a
    // zero-height shell.
    return !!rect && rect.width > 0 && rect.height > 0;
  };
  const menuLabelForBlock = {
    "•": "Bullet List",
    "1.": "Ordered List",
    "☑": "Task List",
    "❝": "Quote",
    "<>": "Code",
    "Image": "Image",
    "▦": "Table",
    "—": "Divider",
  };
  // Keep the visual menu sequence independent from Milkdown's feature-group
  // registration order. Unknown/optional items are deliberately assigned a
  // larger order so they stay available at the end when a feature is enabled.
  const formatMenuOrder = [
    "Text", "H1", "H2", "H3", "Quote", "Ordered List", "Bullet List",
    "Task List", "Code", "链接", "Link", "Image", "Table",
  ];
  const formatMenuOrderIndex = (label) => {
    const index = formatMenuOrder.indexOf(label);
    return index >= 0 ? index : formatMenuOrder.length + 1;
  };
  let menuFormatObserver = null;
  const styleFormatMenu = (currentLabel = "") => {
    const menu = root.querySelector?.(".milkdown-slash-menu");
    if (!menu) return;
    if (!menuFormatObserver && typeof MutationObserver === "function") {
      menuFormatObserver = new MutationObserver(() => scheduleFrame(() => styleFormatMenu(currentLabel)));
      menuFormatObserver.observe(menu, { childList: true, subtree: true });
    }
    const items = [...menu.querySelectorAll?.(".menu-group li") || []];
    for (const item of items) {
      const labelNode = [...item.children].find((child) => (
        child.tagName === "SPAN" && !child.classList.contains("milkdown-icon")
      ));
      const value = labelNode?.textContent?.trim() || "";
      // The block menu is reserved for block level actions. Inline bold and
      // italic belong to the selection toolbar; dividers are not offered in
      // this document editor.
      const hidden = [
        "粗体", "斜体", "Bold", "Italic", "Divider", "分割线",
        "Image", "图片", "Table", "表格",
      ].includes(value);
      if (hidden) item.dataset.runteamsHiddenFormat = "true";
      else delete item.dataset.runteamsHiddenFormat;
      if (lucideMenuPaths[value]) {
        const icon = item.querySelector("svg");
        if (icon && icon.dataset.runteamsLucideValue !== value) {
          icon.dataset.runteamsLucideValue = value;
          icon.classList.add("runteams-lucide-icon");
          icon.setAttribute("fill", "none");
          icon.setAttribute("stroke", "currentColor");
          icon.setAttribute("stroke-width", "2");
          icon.setAttribute("stroke-linecap", "round");
          icon.setAttribute("stroke-linejoin", "round");
          icon.innerHTML = lucideMenuPaths[value];
        }
      }
      const headingMatch = /^H([1-3])$/.exec(value);
      if (headingMatch) {
        // Keep Vue's own icon/label children intact. The compact H + small
        // digit treatment is rendered with CSS pseudo-elements below, so a
        // hover re-render never removes and reinserts the button under the
        // pointer. Store the marker as data rather than a class because the
        // menu component replaces the class attribute on every hover.
        labelNode.dataset.runteamsHeading = headingMatch[1];
      }
      if (["Text", "H1", "H2", "H3", "Quote"].includes(value)) item.dataset.runteamsTopFormat = "true";
      else delete item.dataset.runteamsTopFormat;
      // These rows open a sibling panel. Keep the marker on the row itself so
      // the host can style the affordance without replacing Milkdown's
      // children (which would make the pointer jump during hover).
      if (value === "对齐与缩进" || value === "颜色选项") {
        item.dataset.runteamsSubmenu = "true";
        item.setAttribute("aria-haspopup", "menu");
        if (openSubmenu && !item.dataset.runteamsSubmenuEventsBound) {
          item.dataset.runteamsSubmenuEventsBound = "true";
          const submenuKind = value === "颜色选项" ? "color" : "align";
          const open = (event) => {
            event.preventDefault();
            event.stopPropagation();
            openSubmenu(submenuKind);
          };
          item.addEventListener("pointerenter", open);
          item.addEventListener("mousedown", open);
          item.addEventListener("click", open);
          // The provider may insert the row underneath an already stationary
          // pointer. Reconcile that render without a document-level observer.
          setTimeout(() => {
            if (item.isConnected && item.matches(":hover")) openSubmenu(submenuKind);
          }, 0);
        }
      } else {
        delete item.dataset.runteamsSubmenu;
      }
      item.dataset.runteamsMenuOrder = String(formatMenuOrderIndex(value));
      item.style.order = item.dataset.runteamsMenuOrder;
      const matches = (menuLabelForBlock[currentLabel] || currentLabel) === value;
      if (matches) item.dataset.runteamsCurrentStyle = "true";
      else delete item.dataset.runteamsCurrentStyle;
    }
    // Keep every item under the feature-group that Milkdown created it in.
    // Moving a Vue/Milkdown menu item into another <ul> preserves its pixels
    // but breaks the delegated command listener owned by the original group,
    // leaving a menu that looks clickable yet does nothing. CSS flattens the
    // style groups visually; DOM ownership stays stable for pointer actions.
  };
  const syncBlockStyleButton = (target, labelTarget = target) => {
    if (!target) return;
    let label = "";
    if (labelTarget && labelTarget !== target && labelTarget === labelBlock && stableBlockLabel) {
      label = stableBlockLabel;
    } else if (labelTarget && labelTarget !== target) {
      label = String(getBlockLabel?.(labelTarget) || target.dataset.runteamsBlockLabel || "T");
      labelBlock = labelTarget;
      stableBlockLabel = label;
    } else {
      // No pointer block means the editor is outside the content surface (or
      // the provider is between updates). Keep the last resolved label instead
      // of asking the transient handle rectangle for a new value.
      label = stableBlockLabel || String(target.dataset.runteamsBlockLabel || "T");
    }
    const labelChanged = target.dataset.runteamsBlockLabel !== label;
    if (labelChanged) target.dataset.runteamsBlockLabel = label;
    // The compact capsule always represents the active block style. Keep this
    // as a data attribute (rather than a class) so Vue's menu/handle rerenders
    // cannot reset the selected color for one frame.
    target.dataset.runteamsBlockStyleSelected = "true";
    // The block handle is reused for whichever row the pointer is over. The
    // compact button mirrors that active row, whether or not the editor has
    // received input focus yet.
    const handle = target.closest?.(".milkdown-block-handle");
    const focused = handle?.dataset.runteamsCaretAnchor === "true"
      || target.dataset.runteamsCaretAnchor === "true"
      || getBlockLabel?.isFocused?.(target) === true;
    const focusedValue = focused ? "true" : "false";
    if (target.dataset.runteamsBlockFocused !== focusedValue) {
      target.dataset.runteamsBlockFocused = focusedValue;
    }
    if (labelChanged || target.getAttribute("aria-label") !== `当前块样式 ${label}，打开格式菜单`) {
      target.setAttribute("aria-label", `当前块样式 ${label}，打开格式菜单`);
    }
    // The compact handle already exposes its action visually and through
    // aria-label. Remove Milkdown's native title so hovering it never opens
    // a second tooltip over the format menu.
    target.removeAttribute("title");
    target.classList.add("runteams-block-style-button");
    // Keep the compact handle's label and dot grip as real nodes so the
    // control can share the same icon/text treatment as menu items. Splitting
    // the level digit into its own span also lets H1/H2 stay legible without
    // making the whole capsule wider than necessary.
    styleFormatMenu(label);
    const menuIconLabel = menuLabelForBlock[label] || "";
    let labelNode = target.querySelector?.(".runteams-block-style-label");
    let iconNode = target.querySelector?.(".runteams-block-style-icon");
    if (!labelNode) {
      labelNode = document.createElement("span");
      labelNode.className = "runteams-block-style-label";
      iconNode = document.createElement("span");
      iconNode.className = "runteams-block-style-icon";
      const dotsNode = document.createElement("span");
      dotsNode.className = "runteams-block-style-dots";
      target.append(labelNode, iconNode, dotsNode);
    }
    if (!iconNode) {
      iconNode = document.createElement("span");
      iconNode.className = "runteams-block-style-icon";
      labelNode.after(iconNode);
    }
    // List/quote/code/table entries use the exact SVG already rendered by
    // the format menu. Cloning that menu item keeps the compact button and
    // menu on one icon source, so an ordered list can never turn into a
    // textual “1.” button while the menu shows a numbered-list glyph.
    const menuItem = menuIconLabel
      ? [...root.querySelectorAll?.(".milkdown-slash-menu .menu-group li") || []]
        .find((item) => item.textContent?.trim() === menuIconLabel)
      : null;
    const menuSvg = menuItem?.querySelector?.("svg");
    const iconValue = menuIconLabel && menuSvg ? menuIconLabel : "";
    if (iconNode.dataset.value !== iconValue) {
      iconNode.replaceChildren();
      if (menuSvg) iconNode.append(menuSvg.cloneNode(true));
      iconNode.dataset.value = iconValue;
    }
    if (labelNode.dataset.value !== label || labelNode.dataset.iconValue !== iconValue) {
      labelNode.replaceChildren();
      const levelMatch = /^H([1-6])$/.exec(label);
      if (levelMatch) {
        const prefix = document.createElement("span");
        prefix.textContent = "H";
        const level = document.createElement("small");
        level.className = "runteams-block-style-level";
        level.textContent = levelMatch[1];
        labelNode.append(prefix, level);
      } else if (!iconValue) {
        labelNode.textContent = label;
      }
      labelNode.dataset.value = label;
      labelNode.dataset.iconValue = iconValue;
    }
  };
  const openMenuImmediately = (target, options = {}) => {
    if (!target || !containsDomNode(root, target)) return;
    const transaction = ++hoverGeneration;
    const existingMenu = root.querySelector?.(".milkdown-slash-menu");
    const existingVisible = existingMenu?.dataset.show === "true"
      && !existingMenu.classList.contains("is-repositioning")
      && existingMenu.style.visibility !== "hidden";
    // `openingTarget` is only a debounce marker. If the previous provider
    // update failed to paint the menu, allow the same button to retry instead
    // of leaving hover permanently stuck until a different row is entered.
    if (openingTarget === target && existingVisible) return;
    // Pointermove may arrive just after pointerenter. Cancel that pending
    // hover callback before opening directly, otherwise both paths compete
    // to toggle the provider and the menu flashes.
    clearHoverTimer();
    cancelReveal();
    clearRevealFallback();
    openingTarget = target;
    // Capture the row before the provider moves the reusable handle to its
    // transient origin while opening the menu.
    const openingBlock = resolveMenuBlock(target);
    if (openingBlock) rememberPendingMenuBlock(openingBlock);
    openMenuAt?.(target, options);
    const reveal = () => {
      const menu = root.querySelector(".milkdown-slash-menu");
      if (transaction !== hoverGeneration || !menu || lastTarget !== target || !menuHasRenderableContent(menu)) return;
      // The provider may leave the mounted node at data-show=false while it
      // changes rows. Turn on the populated node first so its groups can be
      // measured, then reveal it only after it has a real layout box.
      if (menu.dataset.show !== "true") menu.dataset.show = "true";
      if (!menuCanPaint(menu)) {
        hideMenu(menu);
        return;
      }
      menu.dataset.runteamsForceOpen = "true";
      menu.dataset.show = "true";
      hideMenu(menu);
      syncMenuLeft(menu, target);
      revealMenu(menu);
      syncMenuRowHighlight(target, true, pendingMenuBlock);
    };
    // Reveal on the same turn and once more after the provider's own update;
    // neither pass changes document content or scroll position.
    reveal();
    setTimeout(reveal, 16);
    setTimeout(reveal, 80);
    setTimeout(reveal, 160);
    setTimeout(reveal, 320);
    setTimeout(reveal, 600);
    setTimeout(() => {
      if (transaction === hoverGeneration && openingTarget === target) openingTarget = null;
    }, 240);
  };
  const onViewportChange = () => {
    const menu = root.querySelector(".milkdown-slash-menu");
    const anchor = root.querySelector(".milkdown-block-handle .operation-item");
    if (menu?.dataset.show === "true" && anchor) syncMenuLeft(menu, anchor);
    // The caret is the source of truth for the compact handle. Recompute its
    // row after scrolling/resizing instead of asking the hover target, which
    // can be stale while Milkdown reuses the same DOM handle.
    syncFocusedButton();
    if (menu?.dataset.show === "true" && menuActiveBlock) renderMenuRowHighlight(menuActiveBlock);
  };
  let focusedSyncFrame = 0;
  const blockTags = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "PRE", "BLOCKQUOTE", "HR", "TABLE"]);
  const codeBlockFromNode = (node, editor) => {
    const codeBlock = node?.closest?.(".milkdown-code-block, .milkdown-image-block");
    return codeBlock && containsDomNode(editor, codeBlock) ? codeBlock : null;
  };
  const normalizePointerBlock = (node, editor) => {
    const codeBlock = codeBlockFromNode(node, editor);
    if (codeBlock) return codeBlock;
    const listItemBlock = node?.closest?.(".milkdown-list-item-block");
    if (listItemBlock && containsDomNode(editor, listItemBlock)) return listItemBlock;
    while (node && node !== editor && !blockTags.has(node.tagName)) node = node.parentElement;
    // List items and blockquotes contain a paragraph element. Normalize both
    // hit targets to their visual container so moving across the text and the
    // small gap around it cannot switch between two different heights.
    if (node?.tagName === "P") {
      const container = node.closest?.("li, blockquote");
      if (container && containsDomNode(editor, container)) node = container;
    }
    return node && node !== editor ? node : null;
  };
  const listItemBlockFromPoint = (node, editor, clientY) => {
    let list = node?.closest?.("ul, ol") || null;
    if (!list) {
      list = [...editor.querySelectorAll("ul, ol")].find((candidate) => {
        const rect = candidate.getBoundingClientRect?.();
        return rect && clientY >= rect.top && clientY <= rect.bottom;
      }) || null;
    }
    if (!list) return null;
    const items = [...list.children].filter((child) => child.classList?.contains("milkdown-list-item-block"));
    if (!items.length) return null;
    let nearest = null;
    let nearestDistance = Infinity;
    for (const item of items) {
      const rect = item.getBoundingClientRect?.();
      if (!rect || rect.height <= 0) continue;
      if (clientY >= rect.top && clientY <= rect.bottom) return item;
      const distance = clientY < rect.top ? rect.top - clientY : clientY - rect.bottom;
      if (distance < nearestDistance) {
        nearest = item;
        nearestDistance = distance;
      }
    }
    return nearest;
  };
  const blockFromPointer = (event) => {
    const editor = root.querySelector?.(".ProseMirror");
    if (!editor || !event) return null;
    const editorRect = editor.getBoundingClientRect?.();
    const pointInsideEditor = editorRect
      && event.clientX >= editorRect.left && event.clientX <= editorRect.right
      && event.clientY >= editorRect.top && event.clientY <= editorRect.bottom;
    // The whitespace separating two list rows is visually part of the editor,
    // but its hit target can be the editor's wrapper rather than ProseMirror
    // itself. Use geometry as a fallback so the active row is not dropped at
    // that boundary.
    if (!containsDomNode(editor, event.target) && !pointInsideEditor) return null;
    let node = event.target?.nodeType === 1 ? event.target : event.target?.parentElement;
    // Pointer events over a text node's whitespace can target the editor root;
    // elementFromPoint gives us the actual rendered block in that case.
    if (!node || node === editor) {
      node = document.elementFromPoint?.(event.clientX, event.clientY) || node;
    }
    const direct = normalizePointerBlock(node, editor)
      || listItemBlockFromPoint(node, editor, event.clientY);
    const current = containsDomNode(editor, pointerBlock) ? pointerBlock : null;
    if (current && direct && direct !== current) {
      const currentRect = current.getBoundingClientRect?.();
      // Keep the previous row through the tiny margin between adjacent rows.
      // Without this hysteresis, elementFromPoint can alternate between the
      // two rows while the pointer is stationary on their shared boundary.
      const boundaryPadding = 8;
      if (currentRect && event.clientY >= currentRect.top - boundaryPadding
        && event.clientY <= currentRect.bottom + boundaryPadding) return current;
    }
    if (direct) return direct;
    // Do not keep a stale row when the pointer moved to a distant blank area
    // of a long list. That stale rectangle can be thousands of pixels away
    // after scrolling and was the source of the missing bottom-half menu.
    const currentRect = current?.getBoundingClientRect?.();
    if (currentRect && event.clientY >= currentRect.top - 8 && event.clientY <= currentRect.bottom + 8) return current;
    return null;
  };
  const clearMenuRowHighlightLayer = () => {
    menuRowHighlightLayer?.remove?.();
    menuRowHighlightLayer = null;
  };
  const restoreMenuRowStacking = () => {
    if (!menuRowStackingBlock) return;
    menuRowStackingBlock.style.position = menuRowStackingPosition;
    menuRowStackingBlock.style.zIndex = menuRowStackingZIndex;
    menuRowStackingBlock = null;
    menuRowStackingPosition = "";
    menuRowStackingZIndex = "";
  };
  const ensureMenuRowStacking = (block) => {
    if (!block) return;
    if (menuRowStackingBlock && menuRowStackingBlock !== block) restoreMenuRowStacking();
    if (menuRowStackingBlock !== block) {
      menuRowStackingBlock = block;
      menuRowStackingPosition = block.style.position;
      menuRowStackingZIndex = block.style.zIndex;
    }
    // Keep the text above the independent highlight layer. These inline
    // properties do not change layout and survive ProseMirror class updates.
    block.style.position = "relative";
    block.style.zIndex = "1";
  };
  const renderMenuRowHighlight = (block) => {
    clearMenuRowHighlightLayer();
    if (suppressMenuRowHighlight) {
      restoreMenuRowStacking();
      return;
    }
    if (!containsDomNode(root, block)) return;
    ensureMenuRowStacking(block);
    const milkdown = root.querySelector?.(".milkdown");
    if (!milkdown) return;
    // List blocks contain a non-editable bullet label. Measure only the
    // content DOM so the temporary background follows the text, not the
    // bullet or the full flex row.
    const content = block.matches?.("li")
      ? block.querySelector?.(".content-dom") || block
      // CodeMirror's toolbar and gutter live inside the NodeView too. Only
      // measure the editor content so the temporary mark cannot paint a
      // toolbar-sized strip above the card or include the line-number gutter.
      : block.matches?.(".milkdown-code-block")
        ? block.querySelector?.(".cm-content") || block
        : block;
    const walker = document.createTreeWalker?.(
      content,
      typeof NodeFilter === "undefined" ? 4 : NodeFilter.SHOW_TEXT,
    );
    const rects = [];
    if (walker) {
      let node = walker.nextNode();
      while (node) {
        if (String(node.textContent || "").trim()) {
          const range = document.createRange();
          range.selectNodeContents(node);
          for (const rect of range.getClientRects()) {
            if (rect.width > 0 && rect.height > 0) rects.push(rect);
          }
        }
        node = walker.nextNode();
      }
    }
    if (!rects.length) return;
    const milkdownRect = milkdown.getBoundingClientRect?.();
    if (!milkdownRect) return;
    const lines = [];
    for (const rect of rects.sort((a, b) => a.top - b.top || a.left - b.left)) {
      const existing = lines.find((line) => Math.abs(line.top - rect.top) <= 2);
      if (existing) {
        existing.left = Math.min(existing.left, rect.left);
        existing.right = Math.max(existing.right, rect.right);
        existing.top = Math.min(existing.top, rect.top);
        existing.bottom = Math.max(existing.bottom, rect.bottom);
      } else {
        lines.push({ left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom });
      }
    }
    const layer = document.createElement("div");
    layer.className = "runteams-menu-row-highlight-layer";
    layer.setAttribute("aria-hidden", "true");
    layer.setAttribute("contenteditable", "false");
    for (const line of lines) {
      const mark = document.createElement("span");
      mark.className = "runteams-menu-row-highlight-mark";
      mark.style.left = `${line.left - milkdownRect.left - 3}px`;
      mark.style.top = `${line.top - milkdownRect.top - 2}px`;
      mark.style.width = `${line.right - line.left + 6}px`;
      mark.style.height = `${line.bottom - line.top + 4}px`;
      layer.append(mark);
    }
    milkdown.append(layer);
    menuRowHighlightLayer = layer;
  };
  const clearMenuRowHighlight = () => {
    menuActiveBlock?.classList?.remove("runteams-menu-active-row");
    menuActiveBlock = null;
    clearMenuRowHighlightLayer();
    restoreMenuRowStacking();
  };
  const rememberPendingMenuBlock = (block) => {
    const editor = root.querySelector?.(".ProseMirror");
    // Menu rows are also <li> elements. Never let a hover event from the
    // floating menu overwrite the real editor block captured at the handle.
    if (block && editor && !editor.contains(block)) return;
    pendingMenuBlock = block || null;
    pendingMenuBlockSignature = block
      ? `${block.tagName}|${String(block.textContent || "").trim().slice(0, 500)}`
      : "";
    const handle = root.querySelector?.(".milkdown-block-handle .operation-item.runteams-block-style-button");
    if (handle) handle.dataset.runteamsMenuTargetSignature = pendingMenuBlockSignature;
    if (root.dataset) root.dataset.runteamsMenuTargetSignature = pendingMenuBlockSignature;
  };
  const recoverPendingMenuBlock = (editor) => {
    if (!editor || !pendingMenuBlockSignature) return null;
    const divider = pendingMenuBlockSignature.indexOf("|");
    const tag = pendingMenuBlockSignature.slice(0, divider);
    const text = pendingMenuBlockSignature.slice(divider + 1);
    const selector = "h1,h2,h3,h4,h5,h6,p,pre,blockquote,li,table,.milkdown-code-block,.milkdown-image-block,.milkdown-list-item-block";
    return [...editor.querySelectorAll(selector)].find((node) => (
      node.tagName === tag && String(node.textContent || "").trim().slice(0, 500) === text
    )) || null;
  };
  const resolveMenuBlock = (target) => {
    const editor = root.querySelector?.(".ProseMirror");
    if (!editor) return null;
    const editorRect = editor.getBoundingClientRect?.();
    const targetRect = target?.getBoundingClientRect?.();
    const handleTarget = target?.closest?.(".milkdown-block-handle") || null;
    // The reusable handle is positioned from the visual row, so its vertical
    // midpoint is the most reliable target when the caret is elsewhere. This
    // matters after keyboard navigation: the pointer may still be over the
    // old row while the user opens the menu on the newly focused row.
    if (handleTarget && editorRect && targetRect?.height > 0) {
      const centerY = targetRect.top + targetRect.height / 2;
      const listRow = listItemBlockFromPoint(null, editor, centerY);
      if (listRow) return listRow;
      const rowCandidates = [...editor.querySelectorAll?.(
        "p,h1,h2,h3,h4,h5,h6,pre,blockquote,table,.milkdown-code-block,.milkdown-image-block,.milkdown-list-item-block"
      ) || []].map((node) => ({ node, rect: node.getBoundingClientRect?.() }))
        .filter(({ rect }) => rect && rect.width > 0 && rect.height > 0)
        .sort((a, b) => Math.abs((a.rect.top + a.rect.height / 2) - centerY)
          - Math.abs((b.rect.top + b.rect.height / 2) - centerY));
      const row = rowCandidates.find(({ rect }) => centerY >= rect.top && centerY <= rect.bottom)
        || rowCandidates[0];
      const rowBlock = normalizePointerBlock(row?.node, editor);
      if (rowBlock) return rowBlock;
      const geometric = document.elementFromPoint?.(
        editorRect.left + Math.min(editorRect.width / 2, 12),
        centerY,
      );
      const geometricBlock = normalizePointerBlock(geometric, editor)
        || listItemBlockFromPoint(geometric, editor, centerY);
      if (geometricBlock) return geometricBlock;
    }
    const pointer = containsDomNode(editor, pointerBlock) ? pointerBlock : recoverPendingMenuBlock(editor);
    const focused = getBlockLabel?.getFocusedBlock?.();
    const editorHasFocus = document.activeElement === editor || editor.contains(document.activeElement);
    // Once the editor owns focus, keyboard navigation is authoritative unless
    // the handle itself supplied a concrete geometric row above.
    if (editorHasFocus && containsDomNode(editor, focused)) return focused;
    if (pointer) {
      const pointerRect = pointer.getBoundingClientRect?.();
      // While the pointer crosses from the text to the outside-positioned
      // button, Milkdown may move the reusable handle to its transient top
      // position before the menu finishes opening. The last block resolved
      // under the pointer is the reliable row identity in that interval.
      if (pointerRect?.height > 0) return pointer;
    }
    if (containsDomNode(editor, focused)) return focused;
    if (!editorRect || !targetRect || targetRect.height <= 0) return null;
    const node = document.elementFromPoint?.(
      editorRect.left + Math.min(editorRect.width / 2, 12),
      targetRect.top + targetRect.height / 2,
    );
    return normalizePointerBlock(node, editor) || listItemBlockFromPoint(node, editor, targetRect.top + targetRect.height / 2);
  };
  const syncMenuRowHighlight = (target, active = true, blockOverride = null) => {
    if (suppressMenuRowHighlight) {
      clearMenuRowHighlight();
      return;
    }
    if (!active) {
      clearMenuRowHighlight();
      return;
    }
    const block = containsDomNode(root, blockOverride)
      ? blockOverride
      : resolveMenuBlock(target);
    if (!block) return;
    if (menuActiveBlock && menuActiveBlock !== block) {
      menuActiveBlock.classList.remove("runteams-menu-active-row");
    }
    menuActiveBlock = block;
    block.classList.add("runteams-menu-active-row");
    renderMenuRowHighlight(block);
  };
  // ProseMirror may reconcile a paragraph's class attribute after the menu
  // provider updates its selection. Re-apply only our transient marker when
  // that happens; the observer stays inert while the menu is closed.
  const menuRowHighlightObserver = typeof MutationObserver === "function"
    ? new MutationObserver(() => {
      if (suppressMenuRowHighlight) {
        clearMenuRowHighlight();
        return;
      }
      if (!containsDomNode(root, menuActiveBlock)) return;
      const menu = root.querySelector(".milkdown-slash-menu");
      if (menu?.dataset.show === "true" && !menuActiveBlock.classList.contains("runteams-menu-active-row")) {
        menuActiveBlock.classList.add("runteams-menu-active-row");
        renderMenuRowHighlight(menuActiveBlock);
      }
    })
    : null;
  menuRowHighlightObserver?.observe(root, { subtree: true, attributes: true, attributeFilter: ["class"] });
  const isHandleMenuBridge = (clientX, clientY) => {
    const anchor = root.querySelector?.(".milkdown-block-handle .operation-item");
    const menu = root.querySelector?.(".milkdown-slash-menu");
    if (!anchor || !menu || menu.dataset.show !== "true") return false;
    const anchorRect = anchor.getBoundingClientRect?.();
    const menuRect = menu.getBoundingClientRect?.();
    if (!anchorRect || !menuRect || anchorRect.width <= 0 || anchorRect.height <= 0
      || menuRect.width <= 0 || menuRect.height <= 0) return false;
    const horizontal = clientX >= Math.min(anchorRect.left, menuRect.left) - 6
      && clientX <= Math.max(anchorRect.right, menuRect.right) + 6;
    const verticalGap = clientY >= Math.min(anchorRect.bottom, menuRect.bottom) - 6
      && clientY <= Math.max(anchorRect.top, menuRect.top) + 6;
    return horizontal && verticalGap
      && !(clientY >= anchorRect.top && clientY <= anchorRect.bottom)
      && !(clientY >= menuRect.top && clientY <= menuRect.bottom);
  };
  const isHandleBridgePoint = (clientX, clientY) => {
    const editor = root.querySelector?.(".ProseMirror");
    const handle = root.querySelector?.(".milkdown-block-handle");
    const anchor = handle?.querySelector?.(".operation-item");
    const editorRect = editor?.getBoundingClientRect?.();
    const handleRect = handle?.getBoundingClientRect?.();
    const anchorRect = anchor?.getBoundingClientRect?.();
    const rect = anchorRect && anchorRect.width > 0 && anchorRect.height > 0
      ? anchorRect
      : handleRect;
    if (!editorRect || !rect || rect.width <= 0 || rect.height <= 0) return false;
    // The handle is positioned just outside the editor's border. Treat the
    // tiny horizontal corridor between them as part of the same hover target;
    // otherwise the first pointermove over that gap hides the button before
    // the pointer can reach it.
    const horizontal = clientX >= Math.min(editorRect.left, rect.left) - 10
      && clientX <= Math.max(editorRect.right, rect.right) + 10;
    const vertical = clientY >= rect.top - 10 && clientY <= rect.bottom + 10;
    return horizontal && vertical;
  };
  const keepMenuSurfaceOpen = (menu) => {
    if (!menu) return;
    clearLeaveTimer();
    if (!menuHasRenderableContent(menu)) {
      menu.removeAttribute("data-runteams-force-open");
      menu.dataset.show = "false";
      hideMenu(menu);
      clearMenuRowHighlight();
      return;
    }
    // Keep a populated menu in the opening transaction while its provider is
    // still switching display state. Resetting data-show here made the hover
    // surface lose the only signal that should trigger the next layout frame.
    if (!menuCanPaint(menu)) {
      menu.dataset.runteamsForceOpen = "true";
      menu.dataset.show = "true";
      hideMenu(menu);
      return;
    }
    // The provider may hide its menu while the pointer is crossing the
    // outside-positioned handle. Keep our explicit hover surface authoritative
    // until the pointer leaves both the bridge and the menu.
    menu.dataset.runteamsForceOpen = "true";
    menu.dataset.show = "true";
    revealMenu(menu);
    syncMenuRowHighlight(lastTarget, true, pendingMenuBlock);
  };
  const positionForBlock = (block) => {
    if (!block) return null;
    const editor = root.querySelector?.(".ProseMirror");
    const editorRect = editor?.getBoundingClientRect?.();
    let visualBlock = block;
    if (block.tagName === "P") {
      const container = block.closest?.("li, blockquote");
      if (container && editor?.contains?.(container)) visualBlock = container;
    }
    const rawRect = block.getBoundingClientRect?.();
    const visualRect = visualBlock.getBoundingClientRect?.();
    // When both the inner paragraph and its outer container are available,
    // deliberately use the taller rectangle. This keeps the handle centered
    // on the full visual row instead of changing height at the boundary.
    const blockRect = visualRect?.height >= rawRect?.height ? visualRect : rawRect;
    if (!editorRect || !blockRect || !Number.isFinite(blockRect.height)) return null;
    const handleHeight = 30;
    // Use the taller rectangle to identify the visual row, but anchor the
    // button near that row's first line rather than centering it in the
    // container. For `li > p` this moves the button up by the container's
    // extra padding and keeps it aligned with the bullet/text baseline.
    const firstLineHeight = Math.min(Number(rawRect?.height) || blockRect.height, 34);
    const topOffset = Math.max(0, (firstLineHeight - handleHeight) / 2);
    return {
      top: blockRect.top - editorRect.top + topOffset,
      height: blockRect.height,
    };
  };
  const syncFocusedButton = (block = pointerBlock, {
    allowCaretFallback = pointerInEditorSurface,
    preferPointer = false,
  } = {}) => {
    const editor = root.querySelector?.(".ProseMirror");
    const editorHasFocus = !!editor && (document.activeElement === editor || editor.contains(document.activeElement));
    const target = root.querySelector(".milkdown-block-handle .operation-item");
    const handle = target?.closest?.(".milkdown-block-handle");
    const menu = root.querySelector(".milkdown-slash-menu");
    // Keyboard selection remains authoritative during normal editor updates.
    // A pointer-driven call explicitly opts into the row under the pointer so
    // the block menu can be opened on another row without first moving the
    // caret there.
    const focusedBlock = allowCaretFallback && editorHasFocus ? getBlockLabel?.getFocusedBlock?.() : null;
    // A focused editor always owns the handle. If its block DOM is transiently
    // unavailable, use the caret position directly instead of falling back to
    // the pointer block and making the handle jump between two rows.
    const pointerBlockInDom = containsDomNode(editor, block) ? block : null;
    const pendingBlockInDom = pointerInEditorSurface && containsDomNode(editor, pendingMenuBlock)
      ? pendingMenuBlock
      : null;
    const menuIsOpen = menu?.dataset.show === "true" || menu?.dataset.runteamsForceOpen === "true";
    const pointerDrivenBlock = preferPointer && pointerBlockInDom ? pointerBlockInDom : null;
    if (pointerDrivenBlock) rememberPendingMenuBlock(pointerDrivenBlock);
    // The pointer row wins whenever it is actually over a block, including
    // the 50ms position-sync pass. Otherwise that timer re-applies the caret
    // row between mousemove events and makes the handle visibly flash between
    // two paragraphs. When the pointer is over empty editor space, fall back
    // to the focused caret row as the stable secondary anchor.
    const pointerRow = pointerInEditorSurface && pointerBlockInDom ? pointerBlockInDom : null;
    const activeBlock = pointerDrivenBlock
      || pointerRow
      || (editorHasFocus ? focusedBlock
      : pointerBlockInDom || pendingBlockInDom || (menuIsOpen
        ? (containsDomNode(editor, menuActiveBlock) ? menuActiveBlock : recoverPendingMenuBlock(editor))
        : null));
    const measuredPosition = positionForBlock(activeBlock)
      || (allowCaretFallback && editorHasFocus ? getBlockLabel?.getFocusedPosition?.() : null);
    let position = measuredPosition;
    if (measuredPosition) {
      lastActivePosition = measuredPosition;
      lastActivePositionAt = Date.now();
    } else if (allowCaretFallback && pointerInEditorSurface && lastActivePosition
      && Date.now() - lastActivePositionAt < 180) {
      // Arrow-key selection updates can briefly leave ProseMirror without a
      // resolvable DOM position while the view redraws. Keep the previous
      // anchor for that single frame so the button does not blink.
      position = lastActivePosition;
    } else if (!pointerInEditorSurface) {
      lastActivePosition = null;
      lastActivePositionAt = 0;
    }
    if (handle) {
      const active = !!position;
      handle.dataset.runteamsCaretAnchor = active ? "true" : "false";
      if (active) {
        handle.dataset.show = "true";
        handle.style.setProperty("--runteams-handle-top", `${Math.round(position.top)}px`);
        // Milkdown reuses one menu node while the caret moves between blocks.
        // Re-anchor the already-open menu immediately after moving the handle;
        // otherwise it remains painted beside the previous row and the next
        // provider update can leave it hidden with no new hover event.
        if (menu && menuCanPaint(menu)
          && (menu.dataset.show === "true" || menu.dataset.runteamsForceOpen === "true")
          // While the pointer is over a real block, the hover transaction is
          // the only owner allowed to reveal the shared menu. Re-showing it
          // here during the 50ms sync pass briefly paints the previous row
          // when the recycled handle moves to a new row.
          && pointerInEditorSurface && !pointerBlockInDom) {
          syncMenuLeft(menu, target);
          menu.dataset.runteamsForceOpen = "true";
          menu.dataset.show = "true";
          revealMenu(menu);
          syncMenuRowHighlight(target, true, pendingMenuBlock);
        }
      } else {
        handle.dataset.show = "false";
        handle.style.removeProperty("--runteams-handle-top");
      }
      // Once the pointer leaves the editor, close the floating menu before
      // its provider can measure the now-hidden handle. This preserves the
      // last valid position and prevents a one-frame jump to the top.
      if (!active && !document.querySelector("#docBlockAlignMenu,#docBlockColorMenu")) {
        const menu = root.querySelector(".milkdown-slash-menu");
        if (menu?.dataset.show === "true") closeMenu(menu);
      }
    }
    syncBlockStyleButton(target, activeBlock || target);
  };
  const scheduleFocusedButtonSync = () => {
    if (focusedSyncFrame) return;
    const schedule = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (callback) => setTimeout(callback, 0);
    focusedSyncFrame = schedule(() => {
      focusedSyncFrame = 0;
      syncFocusedButton();
    });
  };
  const onPointerMove = (event) => {
    const editor = root.querySelector?.(".ProseMirror");
    const editorRect = editor?.getBoundingClientRect?.();
    const menuTarget = event.target?.closest?.(".milkdown-slash-menu") || null;
    const anchor = event.target?.closest?.(".milkdown-block-handle .operation-item") || null;
    const menu = root.querySelector(".milkdown-slash-menu");
    const menuBridge = isHandleMenuBridge(event.clientX, event.clientY);
    const isEditorPointer = !!editor && (containsDomNode(editor, event.target)
      || (editorRect && event.clientX >= editorRect.left && event.clientX <= editorRect.right
        && event.clientY >= editorRect.top && event.clientY <= editorRect.bottom));
    if (isEditorPointer) {
      pointerInEditorSurface = true;
      const nextPointerBlock = blockFromPointer(event);
      const nextPointerSignature = nextPointerBlock
        ? `${nextPointerBlock.tagName}|${String(nextPointerBlock.textContent || "").trim().slice(0, 500)}`
        : "";
      const pointerRowChanged = !!nextPointerSignature
        && nextPointerSignature !== pendingMenuBlockSignature;
      // Milkdown can repaint its shared slash menu from the native pointer
      // handler before the custom hover transaction runs. Invalidate and
      // hide the old surface at the capture boundary so it never flashes
      // beside the newly hovered row.
      if (pointerRowChanged) {
        hoverGeneration += 1;
        clearHoverTimer();
        cancelReveal();
        clearRevealFallback();
        // Alignment/color panels belong to the previous row as well. Remove
        // them at the same capture boundary as the primary menu so a fast
        // move to another block cannot leave the child panel behind for one
        // extra hover interval.
        document.getElementById("docBlockAlignMenu")?.remove();
        document.getElementById("docBlockColorMenu")?.remove();
        const staleMenu = root.querySelector(".milkdown-slash-menu");
        if (staleMenu) {
          staleMenu.removeAttribute("data-runteams-force-open");
          staleMenu.dataset.show = "false";
          hideMenu(staleMenu);
        }
      }
      pointerBlock = nextPointerBlock;
      if (pointerBlock) rememberPendingMenuBlock(pointerBlock);
      // Pointer movement explicitly owns the hovered row; keyboard events use
      // the caret path below, so the two interaction modes do not overwrite
      // one another.
      syncFocusedButton(pointerBlock, { preferPointer: true });
    } else if (!menuTarget && !anchor && !menuBridge
      && !isHandleBridgePoint(event.clientX, event.clientY)) {
      // Do not leave a stale caret anchor visible while the pointer is over
      // the document header, outline, sidebar, or any other non-content area.
      pointerInEditorSurface = false;
      pointerBlock = null;
      syncFocusedButton(null, { allowCaretFallback: false });
    } else if (!menuTarget && !anchor && !menuBridge) {
      // Keep the active row while the pointer crosses the physical gap
      // between the editor text and the outside-positioned compact button.
      pointerInEditorSurface = true;
      syncFocusedButton(pointerBlock, { preferPointer: true });
    }
    if (menuTarget || menuBridge) {
      // The trigger and menu are one hover surface. Keep a pending close from
      // firing while the pointer crosses the small visual gap between them.
      keepMenuSurfaceOpen(menu);
      return;
    }
    if (!anchor || !containsDomNode(root, anchor)) return;
    pointerInEditorSurface = true;
    syncFocusedButton(pointerBlock, { preferPointer: true });
    // Some embedded webviews expose mousemove but not pointerenter for the
    // absolutely positioned block handle. Route the first mousemove through
    // the same immediate-open path so hover is reliable there as well.
    const menuIsVisible = menu?.dataset.show === "true"
      && !menu.classList.contains("is-repositioning")
      && menu.style.visibility !== "hidden";
    // The same DOM handle is reused while the document scrolls, so a new
    // row may keep the old `lastTarget` identity. Let the first pointermove
    // claim the same hover transaction as pointerenter; starting an immediate
    // transaction as well would make the provider toggle the menu twice and
    // produce a visible flash before it settles.
    const forceOpenHover = menu?.dataset.runteamsForceOpen === "true"
      && anchor.matches?.(":hover");
    const pointerSignature = pointerBlock
      ? `${pointerBlock.tagName}|${String(pointerBlock.textContent || "").trim().slice(0, 500)}`
      : "";
    if (lastTarget !== anchor || (pointerSignature && pointerSignature !== lastHoverBlockSignature)) {
      onPointerEnter(event);
      openMenuImmediately(anchor);
    } else if (!menuIsVisible && !forceOpenHover && !hoverTimer) {
      openMenuImmediately(anchor);
    }
    if (menu?.dataset.show === "true") syncMenuLeft(menu, anchor);
  };
  // The handle is intentionally positioned outside the editor's border box,
  // so the transparent gap between it and the menu does not bubble events to
  // this root. Listen at document level solely to keep that bridge alive while
  // the pointer crosses it.
  const onDocumentPointerMove = (event) => {
    const menu = root.querySelector?.(".milkdown-slash-menu");
    if (!menu || menu.dataset.show !== "true") {
      if (isHandleBridgePoint(event.clientX, event.clientY)) {
        pointerInEditorSurface = true;
        syncFocusedButton(pointerBlock, { preferPointer: true });
      }
      return;
    }
    const anchor = root.querySelector?.(".milkdown-block-handle .operation-item");
    const menuRect = menu.getBoundingClientRect?.();
    const anchorRect = anchor?.getBoundingClientRect?.();
    const inside = (rect) => rect && rect.width > 0 && rect.height > 0
      && event.clientX >= rect.left && event.clientX <= rect.right
      && event.clientY >= rect.top && event.clientY <= rect.bottom;
    if (isHandleMenuBridge(event.clientX, event.clientY)
      || menu.contains?.(event.target) || anchor?.contains?.(event.target)
      || inside(menuRect) || inside(anchorRect)) keepMenuSurfaceOpen(menu);
  };
  // The stock plus handler inserts an empty paragraph and calls
  // scrollIntoView before opening the menu. This surface uses the plus as a
  // pure formatting-menu affordance, so intercept its pointerup and open the
  // menu at the active row without mutating the document or scrolling it.
  const onAddPointerUp = (event) => {
    const target = event.target?.closest?.(".milkdown-block-handle .operation-item") || null;
    const addButton = target?.parentElement?.querySelector?.(".operation-item");
    if (!target || target !== addButton || !containsDomNode(root, target)) return;
    event.preventDefault();
    event.stopPropagation();
    openMenuImmediately(target, { focus: true });
  };
  // The stock handle hides itself on pointerdown before pointerup when the
  // pointer is over the outside-positioned capsule. Capture the real press
  // first so the provider cannot turn the trigger into a zero-sized target;
  // synthetic hover events are intentionally left for Milkdown's own opener.
  const onAddPointerDown = (event) => {
    if (event.isTrusted === false) return;
    const target = event.target?.closest?.(".milkdown-block-handle .operation-item") || null;
    const addButton = target?.parentElement?.querySelector?.(".operation-item");
    if (!target || target !== addButton || !containsDomNode(root, target)) return;
    event.preventDefault();
    event.stopPropagation();
    openMenuImmediately(target, { focus: true });
  };
  // The editor reuses the same handle element while scrolling and some
  // webviews do not emit a pointer event when that element moves under a
  // stationary cursor. A lightweight polling guard closes that gap and keeps
  // the visible menu attached to the current row in every viewport position.
  const positionSyncTimer = setInterval(() => {
    const menu = root.querySelector(".milkdown-slash-menu");
    const anchor = root.querySelector(".milkdown-block-handle .operation-item");
    syncFocusedButton();
    // Some embedded webviews expose :hover but drop the corresponding
    // pointerenter/pointermove event. Use the already-running position guard
    // as a single fallback opener, so hover still opens once without starting
    // a second transaction when the normal event path is active.
    const hovered = anchor?.matches?.(":hover");
    const menuVisible = menu?.dataset.show === "true"
      && !menu.classList.contains("is-repositioning")
      && menu.style.visibility !== "hidden";
    if (hovered && !menuVisible && menu?.dataset.runteamsForceOpen !== "true") {
      lastTarget = anchor;
      openMenuImmediately(anchor);
    }
    if (menu?.dataset.runteamsForceOpen === "true" && anchor?.matches?.(":hover")
      && !pointerBlock) {
      if (menuCanPaint(menu)) {
        menu.dataset.show = "true";
        revealMenu(menu);
        syncMenuRowHighlight(anchor, true, pendingMenuBlock);
      } else if (!menuHasRenderableContent(menu)) {
        menu.removeAttribute("data-runteams-force-open");
        menu.dataset.show = "false";
        hideMenu(menu);
        clearMenuRowHighlight();
      } else {
        // The populated node is temporarily display:none while the provider
        // recalculates. Keep it forced open but hidden until the next tick so
        // the menu cannot disappear permanently or paint an empty shell.
        menu.dataset.show = "true";
        hideMenu(menu);
      }
    }
    if (menu?.dataset.show === "true" && anchor) {
      syncMenuLeft(menu, anchor);
      if (menuCanPaint(menu)) syncMenuRowHighlight(anchor, true, pendingMenuBlock);
    }
  }, 50);
  const scrollContainer = root.closest?.(".doc-reader-page");
  scrollContainer?.addEventListener("scroll", onViewportChange, { passive: true });
  window.addEventListener("resize", onViewportChange);
  const onPointerEnter = (event) => {
    const menuTarget = event.target?.closest?.(".milkdown-slash-menu") || null;
    if (menuTarget) {
      clearLeaveTimer();
      return;
    }
    const target = event.target?.closest?.(".milkdown-block-handle .operation-item") || null;
    if (!target || !containsDomNode(root, target)) return;
    // Entering the handle itself is still part of the content interaction
    // surface. Mark it active before syncing so the periodic guard cannot
    // close a menu immediately when the editor already has keyboard focus.
    pointerInEditorSurface = true;
    syncBlockStyleButton(target);
    const hoverBlock = resolveMenuBlock(target);
    const hoverSignature = hoverBlock
      ? `${hoverBlock.tagName}|${String(hoverBlock.textContent || "").trim().slice(0, 500)}`
      : "";
    const rowChanged = !!hoverSignature && hoverSignature !== lastHoverBlockSignature;
    if (hoverBlock) rememberPendingMenuBlock(hoverBlock);
    if (rowChanged) {
      lastHoverBlockSignature = hoverSignature;
      hoverGeneration += 1;
      // The provider reuses one menu node while switching rows. Hide it now;
      // delayed callbacks from the previous row are rejected by the new
      // generation, so they cannot flash at the new row's coordinates.
      clearHoverTimer();
      cancelReveal();
      clearRevealFallback();
      const staleMenu = root.querySelector(".milkdown-slash-menu");
      if (staleMenu) hideMenu(staleMenu);
    }
    const menu = root.querySelector(".milkdown-slash-menu");
    // pointerenter may be observed for the item's nested icon as well. Avoid
    // re-anchoring repeatedly while the pointer stays on the same row.
    const menuIsVisible = menu && menu.dataset.show === "true"
      && !menu.classList.contains("is-repositioning")
      && menu.style.visibility !== "hidden";
    if (lastTarget === target && hoverTimer) return;
    // The same DOM handle is reused as the document scrolls. Re-anchor an
    // already visible menu on re-entry instead of keeping a stale top value.
    if (lastTarget === target && menuIsVisible && !rowChanged) {
      syncMenuLeft(menu, target);
      return;
    }
    clearHoverTimer();
    cancelReveal();
    clearLeaveTimer();
    clearRevealFallback();
    openingTarget = null;
    lastTarget = target;
    if (menu) {
      // Floating UI asynchronously computes the new coordinates.  Hide the
      // existing menu while the pointer settles and until that calculation
      // completes so the old row never flashes while moving between handles.
      hideMenu(menu);
      clearMenuRowHighlight();
      syncMenuLeft(menu, target);
    }
    // Open immediately on hover. Positioning remains guarded below so the
    // provider can settle without flashing the previous row.
    hoverTimer = setTimeout(() => {
      hoverTimer = 0;
      if (lastTarget !== target) return;
      const transaction = ++hoverGeneration;
      openingTarget = target;
      let activeMenu = root.querySelector(".milkdown-slash-menu");
      hideMenu(activeMenu);
      const previousLeft = activeMenu?.style.left || "";
      const previousTop = activeMenu?.style.top || "";
      const init = {
        bubbles: true,
        cancelable: true,
        pointerType: event.pointerType || "mouse",
        isPrimary: true,
        button: 0,
      };
      const dispatchPointer = (type) => {
        let synthetic;
        if (typeof PointerEvent === "function") {
          synthetic = new PointerEvent(type, init);
        } else if (typeof MouseEvent === "function") {
          synthetic = new MouseEvent(type, init);
        } else if (typeof document?.createEvent === "function") {
          // Some embedded webviews expose neither constructor. createEvent
          // keeps hover preview working without coupling to one event API.
          synthetic = document.createEvent("Event");
          synthetic.initEvent(type, true, true);
        }
        if (synthetic) target.dispatchEvent(synthetic);
        return Boolean(synthetic);
      };
      let lastDispatchAt = 0;
      let forcedOpen = false;
      const dispatchOpen = () => {
        const dispatched = dispatchPointer("pointerdown");
        dispatchPointer("pointerup");
        // Embedded webviews can expose neither PointerEvent nor createEvent.
        // The native block handle still responds to click, so keep hover
        // preview functional there instead of silently abandoning the request.
        if (!dispatched && typeof target.click === "function") target.click();
        lastDispatchAt = Date.now();
      };
      dispatchOpen();
      const startedAt = Date.now();
      const revealWhenPositioned = () => {
        if (transaction !== hoverGeneration || lastTarget !== target) {
          revealFrame = 0;
          return;
        }
        // The provider may append the menu asynchronously after pointerup.
        // Re-query it on every frame instead of capturing null from the first
        // pass; this is what previously left the menu hidden forever.
        activeMenu ||= root.querySelector(".milkdown-slash-menu");
        if (!activeMenu) {
          if (Date.now() - startedAt >= 1200) {
            revealFrame = 0;
            return;
          }
          if (Date.now() - lastDispatchAt >= 180) dispatchOpen();
          revealFrame = scheduleFrame(revealWhenPositioned);
          return;
        }
        if (!menuHasRenderableContent(activeMenu)) {
          activeMenu.removeAttribute("data-runteams-force-open");
          activeMenu.dataset.show = "false";
          hideMenu(activeMenu);
          if (Date.now() - startedAt >= 1200) {
            revealFrame = 0;
            openingTarget = null;
            return;
          }
          revealFrame = scheduleFrame(revealWhenPositioned);
          return;
        }
        // BlockProvider updates its active node on a throttled pointermove.
        // If the first synthetic click arrived before that update, retry a
        // few times inside this same hover transaction instead of requiring a
        // second hover from the user.
        if (activeMenu.dataset.show !== "true" && Date.now() - lastDispatchAt >= 180) {
          dispatchOpen();
        }
        hideMenu(activeMenu);
        syncMenuLeft(activeMenu, target);
        let renderedHeight = Number(activeMenu.getBoundingClientRect?.().height)
          || Number(activeMenu.offsetHeight)
          || 0;
        // Milkdown intentionally hides its slash provider for list rows. The
        // plus handle is an explicit block-menu action, so list rows must use
        // the same menu as every other row. If the provider's shouldShow guard
        // immediately hides the menu after the click, reveal the already
        // mounted menu ourselves and let the positioning pass run again.
        if (activeMenu.dataset.show !== "true" && menuHasRenderableContent(activeMenu)) {
          activeMenu.dataset.show = "true";
          forcedOpen = true;
          renderedHeight = Number(activeMenu.getBoundingClientRect?.().height)
            || Number(activeMenu.offsetHeight)
            || 0;
          syncMenuLeft(activeMenu, target);
        }
        // The product placement is carried by CSS custom properties rather
        // than the provider's inline left/top. Read both forms so the first
        // frame can be revealed as soon as our anchor coordinates exist.
        const left = activeMenu.style.left
          || activeMenu.style.getPropertyValue("--runteams-menu-left")
          || "";
        const top = activeMenu.style.top
          || activeMenu.style.getPropertyValue("--runteams-menu-top")
          || "";
        const positionChanged = left !== previousLeft || top !== previousTop;
        const providerReady = activeMenu.dataset.show === "true"
          && menuCanPaint(activeMenu) && left && top && renderedHeight > 0;
        // SlashProvider debounces updates by 200ms; wait for its coordinate
        // write instead of revealing after a fixed number of frames.
        if ((providerReady && (positionChanged || forcedOpen || Date.now() - startedAt >= 240)) || Date.now() - startedAt >= 1200) {
          revealMenu(activeMenu);
          syncMenuRowHighlight(target, true, pendingMenuBlock);
          openingTarget = null;
          clearRevealFallback();
          revealFrame = 0;
          return;
        }
        revealFrame = scheduleFrame(revealWhenPositioned);
      };
      revealFrame = scheduleFrame(revealWhenPositioned);
      // A provider update can fire a transient pointerleave and cancel the
      // animation loop. Keep a final, bounded fallback so a menu that has
      // already been opened can never remain hidden indefinitely.
      revealFallbackTimer = setTimeout(() => {
        revealFallbackTimer = 0;
        if (transaction !== hoverGeneration || openingTarget !== target) return;
        const fallbackMenu = root.querySelector(".milkdown-slash-menu");
        if (fallbackMenu?.dataset.show === "true" && menuCanPaint(fallbackMenu)) {
          revealMenu(fallbackMenu);
          syncMenuRowHighlight(target, true, pendingMenuBlock);
        }
        openingTarget = null;
      }, 1250);
    }, 0);
  };
  const onPointerLeave = (event) => {
    const menuTarget = event.target?.closest?.(".milkdown-slash-menu") || null;
    const target = event.target?.closest?.(".milkdown-block-handle .operation-item") || null;
    const editor = root.querySelector?.(".ProseMirror");
    const related = event.relatedTarget;
    const relatedAnchor = related?.closest?.(".milkdown-block-handle .operation-item") || null;
    const relatedMenu = related?.closest?.(".milkdown-slash-menu") || null;
    const relatedDocumentSubmenu = related?.closest?.(".doc-block-submenu,.doc-style-panel") || null;
    if (!target && !menuTarget) {
      // Moving from a content block onto its button/menu is one continuous
      // hover transaction. Preserve the row so opening the menu does not
      // fall back to the last focused block (which made it appear at the top).
      if (relatedAnchor || relatedMenu || relatedDocumentSubmenu) return;
      // `pointerleave` is delivered during transitions between nested editor
      // nodes as well as when the pointer truly leaves the editor. If the
      // related node is still inside the editor, keep the active row; clearing
      // it here made the handle disappear in the gap between two list items.
      const editorRect = editor?.getBoundingClientRect?.();
      const eventInsideEditor = editorRect
        && event.clientX >= editorRect.left && event.clientX <= editorRect.right
        && event.clientY >= editorRect.top && event.clientY <= editorRect.bottom;
      if (editor?.contains?.(related) || eventInsideEditor
        || isHandleMenuBridge(event.clientX, event.clientY)
        || isHandleBridgePoint(event.clientX, event.clientY)) return;
      if (editor?.contains?.(event.target)) {
        pointerInEditorSurface = false;
        pointerBlock = null;
        syncFocusedButton(null, { allowCaretFallback: false });
      }
      return;
    }
    const nextTarget = related?.closest?.(".milkdown-block-handle .operation-item") || null;
    const menu = root.querySelector(".milkdown-slash-menu");
    if (nextTarget || (related && menu?.contains?.(related)) || relatedDocumentSubmenu) {
      clearLeaveTimer();
      return;
    }
    if (menuTarget) {
      // Leaving the menu is only a close request. Give the pointer a chance
      // to land back on the trigger before hiding the shared hover surface.
      clearLeaveTimer();
      leaveTimer = setTimeout(() => {
        leaveTimer = 0;
        const stillHovering = lastTarget?.matches?.(":hover") || menu?.matches?.(":hover");
        if (stillHovering) return;
        clearHoverTimer();
        cancelReveal();
        clearRevealFallback();
        openingTarget = null;
        lastTarget = null;
        closeMenu(menu);
      }, 120);
      return;
    }
    if (target !== lastTarget) return;
    // A few embedded webviews emit a spurious pointerleave while the
    // provider repositions its popover even though the cursor is still over
    // the plus button. Never hide an active menu in that case.
    if (target.matches?.(":hover")) return;
    if (!document.querySelector("#docBlockAlignMenu,#docBlockColorMenu")) menu?.removeAttribute("data-runteams-force-open");
    if (openingTarget === target) return;
    // Showing the provider can briefly move the pointer out of the handle
    // while its popover is inserted. Do not cancel the opening transaction in
    // that transient frame; only hide after a short grace period if the
    // pointer really left both the handle and the menu.
    if (menu?.dataset.show === "true" && menu.classList.contains("is-repositioning")) {
      clearLeaveTimer();
      leaveTimer = setTimeout(() => {
        leaveTimer = 0;
        const stillHovering = target.matches?.(":hover") || menu.matches?.(":hover");
        if (stillHovering) return;
        clearHoverTimer();
        cancelReveal();
        if (lastTarget === target) lastTarget = null;
        hideMenu(menu);
      }, 140);
      return;
    }
    // Keep the menu alive while the pointer crosses the gap to its trigger or
    // back to the menu. It closes only after both surfaces are no longer
    // hovered.
    clearLeaveTimer();
    leaveTimer = setTimeout(() => {
      leaveTimer = 0;
      const activeMenu = root.querySelector(".milkdown-slash-menu");
      const stillHovering = target.matches?.(":hover") || activeMenu?.matches?.(":hover");
      if (stillHovering) return;
      clearHoverTimer();
      cancelReveal();
      clearRevealFallback();
      openingTarget = null;
      if (lastTarget === target) lastTarget = null;
      closeMenu(activeMenu);
    }, 120);
  };
  root.addEventListener("pointerenter", onPointerEnter, true);
  root.addEventListener("pointerleave", onPointerLeave, true);
  root.addEventListener("pointermove", onPointerMove, true);
  root.addEventListener("pointerdown", onAddPointerDown, true);
  root.addEventListener("pointerup", onAddPointerUp, true);
  // Milkdown's block provider still tracks rows from `mousemove` (rather than
  // pointer events) in some embedded webviews. Mirror the re-anchor hook so a
  // menu that is already open follows the row under the native mouse too.
  root.addEventListener("mousemove", onPointerMove, true);
  root.addEventListener("pointerdown", dismissMenusForEditorPointer, true);
  document.addEventListener("pointermove", onDocumentPointerMove, true);
  document.addEventListener("mousemove", onDocumentPointerMove, true);
  root.addEventListener("focusin", syncFocusedButton, true);
  root.addEventListener("focusout", scheduleFocusedButtonSync, true);
  const onEditorSelectionChange = () => {
    const editor = root.querySelector?.(".ProseMirror");
    if (editor && (document.activeElement === editor || editor.contains(document.activeElement))) syncFocusedButton();
  };
  // Selection updates are already coalesced by ProseMirror. Sync directly for
  // zero-latency feedback; the 50ms guard below only covers webviews that do
  // not emit one of these native events.
  root.addEventListener("keydown", syncFocusedButton, true);
  root.addEventListener("keyup", syncFocusedButton, true);
  root.addEventListener("input", syncFocusedButton, true);
  root.addEventListener("mouseup", syncFocusedButton, true);
  root.addEventListener("compositionend", syncFocusedButton, true);
  root.addEventListener("click", syncFocusedButton, true);
  document.addEventListener("selectionchange", onEditorSelectionChange, true);
  return () => {
    menuRowHighlightObserver?.disconnect();
    if (styleHighlightSuppressionTimer) clearTimeout(styleHighlightSuppressionTimer);
    styleHighlightSuppressionTimer = null;
    suppressMenuRowHighlight = false;
    clearHoverTimer();
    cancelReveal();
    clearLeaveTimer();
    clearRevealFallback();
    openingTarget = null;
    pointerInEditorSurface = false;
    pointerBlock = null;
    lastActivePosition = null;
    lastActivePositionAt = 0;
    labelBlock = null;
    stableBlockLabel = "";
    const menu = root.querySelector(".milkdown-slash-menu");
    revealMenu(menu);
    clearMenuRowHighlight();
    pendingMenuBlock = null;
    pendingMenuBlockSignature = "";
    menu?.removeAttribute("data-runteams-outline-position");
    menu?.removeAttribute("data-runteams-force-open");
    lastTarget = null;
    root.removeEventListener("pointerenter", onPointerEnter, true);
    root.removeEventListener("pointerleave", onPointerLeave, true);
    root.removeEventListener("pointermove", onPointerMove, true);
    root.removeEventListener("pointerdown", dismissMenusForEditorPointer, true);
    document.removeEventListener("pointerup", delegatedSubmenuPointerUp, true);
    root.removeEventListener("pointerdown", onAddPointerDown, true);
    root.removeEventListener("pointerup", onAddPointerUp, true);
    root.removeEventListener("mousemove", onPointerMove, true);
    document.removeEventListener("pointermove", onDocumentPointerMove, true);
    document.removeEventListener("mousemove", onDocumentPointerMove, true);
    root.removeEventListener("focusin", syncFocusedButton, true);
    root.removeEventListener("focusout", scheduleFocusedButtonSync, true);
    root.removeEventListener("keydown", syncFocusedButton, true);
    root.removeEventListener("keyup", syncFocusedButton, true);
    root.removeEventListener("input", syncFocusedButton, true);
    root.removeEventListener("mouseup", syncFocusedButton, true);
    root.removeEventListener("compositionend", syncFocusedButton, true);
    root.removeEventListener("click", syncFocusedButton, true);
    document.removeEventListener("selectionchange", onEditorSelectionChange, true);
    clearInterval(positionSyncTimer);
    scrollContainer?.removeEventListener("scroll", onViewportChange);
    window.removeEventListener("resize", onViewportChange);
  };
}

export function mount(root, options = {}) {
  let openMenuAt = null;
  let getBlockLabel = null;
  let isBlockFocused = null;
  let live = false;
  let gone = false;
  const getBlockHandleRect = (target) => {
    const buttonRect = target?.getBoundingClientRect?.();
    if (buttonRect && buttonRect.width > 0 && buttonRect.height > 0) return buttonRect;
    // The compact button is intentionally display:none while the editor is
    // not focused. The parent handle still carries the provider's row
    // coordinates, so use it for hit-testing instead of getting stuck at a
    // zero-sized rectangle.
    const handleRect = target?.closest?.(".milkdown-block-handle")?.getBoundingClientRect?.();
    return handleRect && Number.isFinite(handleRect.top) ? {
      left: handleRect.left,
      top: handleRect.top,
      width: Math.max(handleRect.width, 1),
      height: Math.max(handleRect.height, 1),
      right: handleRect.right,
      bottom: handleRect.bottom,
    } : buttonRect;
  };
  const blockLabelResolver = (target) => getBlockLabel?.(target);
  blockLabelResolver.isFocused = (target) => isBlockFocused?.(target) === true;
  const unbindBlockMenuHover = bindBlockMenuHover(
    root,
    (target, options) => openMenuAt?.(target, options),
    blockLabelResolver,
    (kind) => options.onOpenBlockSubmenu?.(kind),
  );
  const blockStyleMemory = Object.create(null);
  const isVisibleEditorNode = (node) => {
    const rect = node?.getBoundingClientRect?.();
    return !!rect && rect.width > 0 && rect.height > 0;
  };
  if (options.blockStyles && typeof options.blockStyles === "object") {
    Object.assign(blockStyleMemory, options.blockStyles);
  }
  const blockStylePluginKey = new PluginKey("runteams-block-styles");
  const buildBlockStyleDecorations = (doc) => {
    const decorations = [];
    doc.descendants((node, pos) => {
      // List containers are layout scaffolding, not independently formatted
      // blocks. Persisting an alignment on both UL/OL and list_item creates
      // two competing authorities: an old container value can repaint a new
      // item value during hydration. List-item attrs/decorations are the sole
      // durable source; the container is only touched for the live multi-row
      // presentation path.
      if (!node.isBlock || node.type.name === "bullet_list" || node.type.name === "ordered_list") return;
      const resolved = doc.resolve(pos);
      const topIndex = resolved.index(0);
      // Crepe renders a list item's visible paragraph as a nested block. The
      // list_item is the durable formatting owner; a paragraph's historical
      // attrs must never override the current item value during hydration.
      let listItemDepth = 0;
      for (let depth = resolved.depth; depth > 0; depth -= 1) {
        if (resolved.node(depth).type.name === "list_item") {
          listItemDepth = depth;
          break;
        }
      }
      let anchor = `block-${topIndex}`;
      if (node.type.name === "list_item") {
        anchor = `block-${topIndex}-${resolved.index(Math.max(0, resolved.depth - 1))}`;
      }
      const inheritedListItem = listItemDepth && node.type.name !== "list_item"
        ? resolved.node(listItemDepth)
        : null;
      const styleSource = inheritedListItem || node;
      const styleAnchor = inheritedListItem
        ? `block-${topIndex}-${resolved.index(Math.max(0, listItemDepth - 1))}`
        : anchor;
      const level = node.attrs?.level;
      const nodeTag = node.type.name === "paragraph" ? "P"
        : node.type.name === "heading" ? `H${level || 1}`
        : node.type.name === "blockquote" ? "BLOCKQUOTE"
        : node.type.name === "code_block" ? "PRE"
        // Crepe renders a list_item through a DIV node view which contains
        // the semantic LI. Keep the signature on that stable wrapper so the
        // floating block handle can resolve it after the menu opens.
        : node.type.name === "list_item" ? "DIV" : "";
      const signature = nodeTag ? `sig:${nodeTag}|${node.textContent.trim().slice(0, 500)}` : "";
      // Formatting is keyed by the captured block identity. Numeric DOM
      // indexes are intentionally not used here: widgets can appear between
      // document blocks and would shift the style onto the following node.
      // Prefer the stable ProseMirror block anchor when restoring a style.
      // Signatures remain as a backwards-compatible fallback, but matching
      // only by text means duplicate/edited headings can silently lose (or
      // inherit) another block's formatting.
      const saved = blockStyleMemory[styleAnchor]
        || (node.type.name === "list_item" ? null : (signature ? blockStyleMemory[signature] : null))
        || {};
      // Formatting is part of the ProseMirror node for all styled blocks,
      // including list_item NodeViews. The memory bucket remains a migration
      // fallback for documents created before the attrs were introduced.
      const memoryFirst = !!inheritedListItem || node.type.name === "list_item";
      const listAlign = saved.align || (styleSource.attrs?.align !== "left" ? styleSource.attrs?.align : "");
      const listColor = saved.color || styleSource.attrs?.color || "";
      const listBackground = saved.background || styleSource.attrs?.background || "";
      const listIndent = Number(saved.indent) || Number(styleSource.attrs?.indent) || 0;
      const value = {
        align: memoryFirst
          ? (listAlign || (node.attrs?.align !== "left" ? node.attrs?.align : "") || "left")
          : (node.attrs?.align && node.attrs.align !== "left" ? node.attrs.align : (saved.align || "left")),
        color: memoryFirst ? (listColor || node.attrs?.color || "") : (node.attrs?.color || saved.color || ""),
        background: memoryFirst ? (listBackground || node.attrs?.background || "") : (node.attrs?.background || saved.background || ""),
        indent: memoryFirst
          ? (listIndent || Number(node.attrs?.indent) || 0)
          : (Number(node.attrs?.indent) > 0 ? Number(node.attrs.indent) : (Number(saved.indent) || 0)),
      };
      if (!value) return;
      const rules = [];
      // List items are rendered through a NodeView wrapper, but the node
      // decoration remains the durable source of truth across that wrapper's
      // redraws.  Keep alignment on the list_item as well as the paragraph so
      // a command cannot be erased by the next NodeView update.
      if (value.align && value.align !== "left") rules.push(`text-align:${value.align}`);
      if (Number(value.indent) > 0) rules.push(`--runteams-block-indent:${Number(value.indent) * 24}px`);
      if (value.color) rules.push(`color:${value.color}`);
      if (value.background) rules.push(`background-color:${value.background}`);
      if (rules.length) decorations.push(Decoration.node(pos, pos + node.nodeSize, { style: `${rules.join(";")};` }));
    });
    return DecorationSet.create(doc, decorations);
  };
  const blockStylePlugin = new Plugin({
    key: blockStylePluginKey,
    state: {
      init: () => DecorationSet.empty,
      apply: (tr, set, _old, next) => {
        if (tr.getMeta(blockStylePluginKey)) return buildBlockStyleDecorations(next.doc);
        return tr.docChanged
          ? (Object.keys(blockStyleMemory).length ? buildBlockStyleDecorations(next.doc) : set.map(tr.mapping, tr.doc))
          : set;
      },
    },
    props: { decorations: (state) => blockStylePluginKey.getState(state) || DecorationSet.empty },
  });
  // A long document can expose the ProseMirror surface a little before
  // `crepe.create()` resolves. Capture a real pointer-down during that short
  // window so the first user click is restored after the view is ready instead
  // of silently falling back to Milkdown's default first-block selection.
  let earlyPointerPosition = null;
  let latestEditorPointerDown = null;
  const captureEarlyPointer = (event) => {
    if (!Number.isFinite(event?.clientX) || !Number.isFinite(event?.clientY)) return;
    const editor = root.querySelector?.(".ProseMirror");
    if (editor?.contains?.(event.target) && !event.target?.closest?.(
      ".milkdown-block-handle,.milkdown-slash-menu,#docBlockAlignMenu,#docBlockColorMenu,.doc-block-submenu,.doc-style-panel"
    )) {
      const point = { left: event.clientX, top: event.clientY, at: Date.now() };
      latestEditorPointerDown = point;
      if (!earlyPointerPosition) earlyPointerPosition = point;
    }
  };
  root.addEventListener("pointerdown", captureEarlyPointer, true);
  root.addEventListener("mousedown", captureEarlyPointer, true);
  const crepe = new CrepeBuilder({ root, defaultValue: toEditorMarkdown(options.value) });
  // ProseMirror normally translates a mouse press into a caret transaction.
  // The outside-positioned Milkdown handle and the document style surface can
  // consume that press first, however, leaving the editor focused while its
  // selection stays on the old block. Resolve the press coordinates directly
  // as a safety net; this keeps normal drag-selection behavior intact because
  // ProseMirror still receives the same event immediately afterwards.
  let pointerSelectionFrame = 0;
  const pointerBlockEndPosition = (view, block) => {
    if (!view || !block) return null;
    const textBlock = block.matches?.("p,h1,h2,h3,h4,h5,h6,pre,blockquote")
      ? block
      : block.querySelector?.("p,h1,h2,h3,h4,h5,h6,pre,blockquote") || block;
    try {
      // Resolve the DOM end, not the block start. `posAtDOM(block, 0) + 1`
      // was the old workaround and placed the caret at the second character.
      const end = view.posAtDOM(textBlock, textBlock.childNodes?.length || 0);
      const resolvedEnd = view.state.doc.resolve(end);
      if (resolvedEnd.parent?.isTextblock) return end;
      // NodeViews can expose a wrapper boundary instead of the textblock.
      // Derive the textblock's true content end from its PM node in that case.
      const start = view.posAtDOM(textBlock, 0);
      const resolvedStart = view.state.doc.resolve(start);
      for (let depth = resolvedStart.depth; depth > 0; depth -= 1) {
        const node = resolvedStart.node(depth);
        if (node.isTextblock) return resolvedStart.start(depth) + node.content.size;
      }
    } catch (error) { /* fall through to the coordinate mapper */ }
    return null;
  };
  const ensurePointerSelection = (event) => {
    // One capture-phase pointerdown is enough to resolve the clicked block.
    // Handling mousedown/click as well made one physical click dispatch the
    // selection three times and visibly bounced the caret between DOM ranges.
    if (gone || event?.type !== "pointerdown" || event?.button !== 0) return;
    const editor = root.querySelector?.(".ProseMirror");
    if (!editor?.contains?.(event.target) || event.target?.closest?.(
      ".milkdown-block-handle,.milkdown-slash-menu,#docBlockAlignMenu,#docBlockColorMenu,.doc-block-submenu,.doc-style-panel"
    )) return;
    // A fresh pointer gesture starts a new selection transaction. Do not let
    // a list captured by an earlier drag stay authoritative for a later
    // single-row click; mouseup/selectionchange will capture the new drag if
    // this gesture really becomes a multi-row selection.
    if (!event.shiftKey) {
      lastNativeListTargets = [];
      lastNativeListSelectionAt = 0;
    }
    const applySelection = () => { try {
      crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        // ProseMirror has already produced a non-empty drag selection by the
        // time this animation frame runs. Preserve it instead of collapsing
        // the range back to the pointer-down character.
        if (!view.state.selection.empty) return;
        let resolvedPos = null;
        // Preserve a click inside the text itself.  The browser caret range
        // carries the exact character offset; forcing the block end here made
        // every click in a paragraph jump to its last character.
        try {
          const range = document.caretRangeFromPoint?.(event.clientX, event.clientY);
          if (range?.startContainer && editor.contains(range.startContainer)) {
            resolvedPos = view.posAtDOM(range.startContainer, range.startOffset);
          }
        } catch (error) { /* use the coordinate mapper below */ }
        try {
          if (typeof resolvedPos !== "number") {
            const hit = view.posAtCoords({ left: event.clientX, top: event.clientY });
            resolvedPos = hit?.pos;
          }
        } catch (error) { /* fall back to the block boundary below */ }
        if (typeof resolvedPos !== "number") {
          try {
            const block = event.target?.closest?.("p,h1,h2,h3,h4,h5,h6,li,blockquote,pre")
              || event.target;
            if (block && editor.contains(block)) {
              resolvedPos = pointerBlockEndPosition(view, block);
            }
          } catch (error) { /* let ProseMirror keep its native selection */ }
        }
        if (typeof resolvedPos !== "number") return;
        let selection = null;
        try {
          const resolved = view.state.doc.resolve(resolvedPos);
          selection = resolved.parent?.isTextblock
            ? TextSelection.create(view.state.doc, resolvedPos)
            : TextSelection.near(resolved);
        } catch (error) { selection = TextSelection.near(view.state.doc.resolve(resolvedPos)); }
        view.focus();
        if (selection.from !== view.state.selection.from || selection.to !== view.state.selection.to) {
          view.dispatch(view.state.tr.setSelection(selection));
        }
      });
    } catch (error) { /* 编辑器重绘期间交给 ProseMirror 原生处理 */ } };
    // Let ProseMirror finish its native pointer transaction first. A single
    // frame is enough; repeated timers fight the browser's active caret.
    if (pointerSelectionFrame) cancelAnimationFrame(pointerSelectionFrame);
    pointerSelectionFrame = requestAnimationFrame(() => {
      pointerSelectionFrame = 0;
      applySelection();
    });
  };
  root.addEventListener("pointerdown", ensurePointerSelection, true);
  crepe.editor.use(styledParagraphSchema);
  crepe.editor.use(styledHeadingSchema);
  crepe.editor.use($prose(() => blockStylePlugin));
  // Register after Crepe's CommonMark/GFM presets so this extension replaces
  // only the list-item content expression while retaining task-list support.
  crepe.editor.use(listItemBlockSchema);
  // ProseMirror can emit focusin before its native mouse handler has finished
  // translating a click into a document position. Re-apply the most recent
  // click coordinate on the next turn so the first click after refresh wins,
  // instead of leaving the default first-block caret in place.
  const restorePointerSelection = () => {
    const point = latestEditorPointerDown;
    // This coordinate only repairs the initial focus-in race. Reusing it on
    // a later focus transition can move the caret back to the previous row
    // after the user has already clicked somewhere else.
    latestEditorPointerDown = null;
    // Once the editor is live, the normal pointer-selection reconciler owns
    // focus transitions. This mount-time repair must not remap a real user
    // click through the old coordinate mapper and pull the caret to block 1.
    if (live) return;
    if (!point || Date.now() - point.at > 450 || gone) return;
    setTimeout(() => {
      if (gone) return;
      try {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          if (!view.hasFocus()) return;
          const target = document.elementFromPoint?.(point.left, point.top);
          const block = target?.closest?.("p,h1,h2,h3,h4,h5,h6,li,blockquote,pre");
          const end = block ? pointerBlockEndPosition(view, block) : null;
          const hit = typeof end === "number" ? { pos: end } : view.posAtCoords(point);
          if (!hit || typeof hit.pos !== "number") return;
          const resolved = view.state.doc.resolve(hit.pos);
          const selection = resolved.parent?.isTextblock
            ? TextSelection.create(view.state.doc, hit.pos)
            : TextSelection.near(resolved);
          if (selection.from !== view.state.selection.from || selection.to !== view.state.selection.to) {
            view.dispatch(view.state.tr.setSelection(selection));
          }
        });
      } catch (error) { /* 编辑器重绘期间坐标暂时不可用，交给原生选区处理 */ }
    }, 0);
  };
  root.addEventListener("focusin", restorePointerSelection, true);
  crepe
    .addFeature(listItem)
    .addFeature(imageBlock)
    .addFeature(blockEdit, {
      // The document menu only exposes the three heading levels used by our
      // reader. Keep the labels in the same compact H+small-digit language as
      // the block-style capsule; deeper levels remain readable in imported
      // documents but are not offered as new choices.
      textGroup: {
        h1: { label: "H1" },
        h2: { label: "H2" },
        h3: { label: "H3" },
        h4: null,
        h5: null,
        h6: null,
      },
      // 块菜单是正文编辑的主入口；链接也放进这里，避免再占用文档顶栏。
      buildMenu: (builder) => {
        builder.getGroup("text").addItem("link", {
          label: "链接",
          icon: lucideLinkIcon,
          onRun: () => {
            if (typeof options.onInsertLink === "function") options.onInsertLink();
          },
        });
        const actions = builder.addGroup("actions", "");
        actions.addItem("align", {
          label: "对齐与缩进",
          icon: lucideSvg(AlignLeft),
          onRun: () => {
            if (typeof options.onOpenBlockSubmenu === "function") options.onOpenBlockSubmenu("align");
          },
        });
        actions.addItem("color", {
          label: "颜色选项",
          icon: lucideSvg(Palette),
          onRun: () => {
            if (typeof options.onOpenBlockSubmenu === "function") options.onOpenBlockSubmenu("color");
          },
        });
        actions.addItem("cut", {
          label: "剪切",
          icon: lucideSvg(Scissors),
          onRun: (ctx) => {
            const view = ctx.get(editorViewCtx);
            const text = currentBlockInfo(view)?.node?.textContent || "";
            if (typeof options.onCutBlock === "function") options.onCutBlock(text);
            if (deleteCurrentBlock(view, ctx) && typeof options.onDeleteBlock === "function") options.onDeleteBlock();
          },
        });
        actions.addItem("copy", {
          label: "复制",
          icon: lucideSvg(Copy),
          onRun: (ctx) => {
            const view = ctx.get(editorViewCtx);
            const text = view.state.selection.$from.parent.textContent || "";
            if (typeof options.onCopyBlock === "function") options.onCopyBlock(text);
          },
        });
        actions.addItem("delete", {
          label: "删除",
          icon: lucideSvg(Trash2),
          onRun: (ctx) => {
            const view = ctx.get(editorViewCtx);
            if (deleteCurrentBlock(view, ctx) && typeof options.onDeleteBlock === "function") options.onDeleteBlock();
          },
        });
        actions.addItem("copy-link", {
          label: "复制链接",
          icon: lucideCopyLinkIcon,
          onRun: (ctx) => {
            const view = ctx.get(editorViewCtx);
            const info = currentBlockInfo(view);
            if (typeof options.onCopyLink === "function") options.onCopyLink(info?.anchor || "");
          },
        });
      },
    })
    // CrepeBuilder 手动加载 feature 时不会自动合并 Crepe 的默认配置。
    // 显式传入 CodeMirror 的语言数据，语言选择器才能提供完整且可搜索的语言集合；
    // lineWrapping 则让长行按代码块宽度折行，同时保留原始换行和缩进。
    .addFeature(codeMirror, {
      languages,
      extensions: [CodeMirrorView.lineWrapping],
      searchPlaceholder: "搜索语言",
      noResultText: "未找到语言",
      copyText: "复制",
      onCopy: (text) => {
        // CodeMirror 已经完成复制，这个回调只负责把结果交给宿主的
        // toast 层，避免再次写入剪贴板或在编辑器里重复维护通知样式。
        if (typeof options.onCopyCodeBlock === "function") options.onCopyCodeBlock(text);
      },
    })
    .addFeature(table)
    .addFeature(placeholder, { text: options.placeholder || "写点什么…" });

  /* 存回去的 markdown 要和 AI 员工写出来的长一个样：无序列表用 "-"，
     分隔线用 "---"，代码块用围栏——不然人一编辑就产生一堆无谓的 diff。 */
  crepe.editor.config((ctx) => {
    ctx.set(remarkStringifyOptionsCtx, {
      bullet: "-",
      rule: "-",
      fences: true,
      emphasis: "*",
      strong: "*",
      listItemIndent: "one",
    });
    // Crepe's trailing plugin appends an empty paragraph after every list so
    // a caret always has somewhere to land. In this editor the block handle
    // is already the insertion affordance, and that sentinel becomes a
    // visible extra row immediately after applying a list or quote (the
    // reported "自动换行"). Keep the fallback for other block types, but do
    // not create a synthetic row after list/quote containers. A user-entered
    // Enter still creates a real paragraph through ProseMirror's normal exit
    // flow.
    ctx.update(trailingConfig.key, (previous) => ({
      ...previous,
      shouldAppend: (lastNode, state) => {
        if (lastNode && ["bullet_list", "ordered_list", "blockquote"].includes(lastNode.type.name)) {
          return false;
        }
        return previous.shouldAppend(lastNode, state);
      },
    }));
  });

  // Read the current block type from the editor document so the compact
  // handle can mirror the same style label shown by the format menu (e.g. H2).
  // This is deliberately derived from ProseMirror state instead of DOM text,
  // keeping the label correct for empty paragraphs, lists and code blocks.
  getBlockLabel = (target) => {
    if (!target) return "T";
    // NodeView containers are the authoritative style identity. Coordinate
    // hit-testing can land on the editor surface around an atom-like code or
    // image block and incorrectly fall back to plain text, even though the
    // current block is already known from the DOM.
    if (target.closest?.(".milkdown-code-block")) return "<>";
    if (target.closest?.(".milkdown-image-block")) return "Image";
    try {
      return crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        const editorRect = view.dom.getBoundingClientRect();
        const targetRect = getBlockHandleRect(target);
        if (!targetRect) return "T";
        const hit = view.posAtCoords({
          left: editorRect.left + editorRect.width / 2,
          top: targetRect.top + targetRect.height / 2,
        });
        if (!hit || typeof hit.pos !== "number") return "T";
        const $pos = view.state.doc.resolve(hit.pos);
        for (let depth = $pos.depth; depth > 0; depth -= 1) {
          const node = $pos.node(depth);
          if (node.type.name === "heading") return `H${Number(node.attrs.level) || 1}`;
          if (node.type.name === "code_block") return "<>";
          if (node.type.name === "image-block") return "Image";
          if (node.type.name === "blockquote") return "❝";
          if (node.type.name === "list_item" && node.attrs.checked != null) return "☑";
          if (node.type.name === "bullet_list") return "•";
          if (node.type.name === "ordered_list") return "1.";
          if (node.type.name === "horizontal_rule") return "—";
          if (node.type.name === "table") return "▦";
        }
        return "T";
      });
    } catch (error) {
      return "T";
    }
  };

  // A hovered block handle is not the same thing as the editor's focused
  // input block. Keep the compact style button tied to the latter so moving
  // the pointer over another row never makes that row look active.
  isBlockFocused = (target) => {
    if (!target || gone || !live) return false;
    try {
      return crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        if (!view.hasFocus()) return false;
        const editorRect = view.dom.getBoundingClientRect();
        const targetRect = getBlockHandleRect(target);
        if (!targetRect) return false;
        const hit = view.posAtCoords({
          left: editorRect.left + editorRect.width / 2,
          top: targetRect.top + targetRect.height / 2,
        });
        if (!hit || typeof hit.pos !== "number") return false;
        const blockAt = ($pos) => {
          for (let depth = $pos.depth; depth > 0; depth -= 1) {
            const node = $pos.node(depth);
            if (node.isTextblock) return $pos.before(depth);
          }
          return null;
        };
        const targetBlock = blockAt(view.state.doc.resolve(hit.pos));
        const selectionBlock = blockAt(view.state.selection.$from);
        return targetBlock !== null && targetBlock === selectionBlock;
      });
    } catch (error) {
      return false;
    }
  };

  // Keep the compact handle anchored to the editor selection, not to the
  // pointer. Milkdown reuses one handle node and normally moves it on hover;
  // deriving this position from the selected text block makes keyboard
  // navigation and pointer movement share one stable source of truth.
  blockLabelResolver.getFocusedBlock = () => getBlockLabel?.getFocusedBlock?.() || null;
  getBlockLabel.getFocusedBlock = () => {
    if (gone || !live) return null;
    try {
      return crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        // CodeMirror and image NodeViews can own native focus while editing a
        // block, so the outer ProseMirror view may report hasFocus() === false.
        // The active DOM node is still an unambiguous block anchor; honor it
        // before applying the normal ProseMirror focus guard.
        const activeNodeViewBlock = document.activeElement?.closest?.(".milkdown-code-block, .milkdown-image-block");
        if (activeNodeViewBlock && view.dom.contains(activeNodeViewBlock)) return activeNodeViewBlock;
        if (!view.hasFocus()) return null;
        const { $from } = view.state.selection;
        let node = view.domAtPos($from.pos)?.node || null;
        if (node?.nodeType === 3) node = node.parentElement;
        const codeBlock = node?.closest?.(".milkdown-code-block, .milkdown-image-block");
        if (codeBlock && view.dom.contains(codeBlock)) return codeBlock;
        const blockTags = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "PRE", "BLOCKQUOTE", "HR", "TABLE"]);
        while (node && node !== view.dom && !blockTags.has(node.tagName)) node = node.parentElement;
        if (node?.tagName === "P") {
          const container = node.closest?.("li, blockquote");
          if (container && view.dom.contains(container)) node = container;
        }
        return node && node !== view.dom ? node : null;
      });
    } catch (error) {
      return null;
    }
  };
  blockLabelResolver.getFocusedPosition = () => {
    if (gone || !live) return null;
    try {
      return crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        const activeNodeViewBlock = document.activeElement?.closest?.(".milkdown-code-block, .milkdown-image-block");
        if (activeNodeViewBlock && view.dom.contains(activeNodeViewBlock)) {
          const codeRect = activeNodeViewBlock.getBoundingClientRect?.();
          const editorRect = view.dom.getBoundingClientRect?.();
          if (!codeRect || !editorRect) return null;
          const handleHeight = 30;
          return {
            top: codeRect.top - editorRect.top + Math.max(0, (codeRect.height - handleHeight) / 2),
            height: codeRect.height,
          };
        }
        if (!view.hasFocus()) return null;
        const { $from } = view.state.selection;
        const editorRect = view.dom.getBoundingClientRect();
        // domAtPos is stable for top-level and nested blocks alike. Walking
        // to the nearest block element avoids nodeDOM(0) returning the editor
        // root, which used to send the handle thousands of pixels off-screen
        // after keyboard navigation scrolled a long document.
        let node = view.domAtPos($from.pos)?.node || null;
        if (node?.nodeType === 3) node = node.parentElement;
        const codeBlock = node?.closest?.(".milkdown-code-block, .milkdown-image-block");
        if (codeBlock && view.dom.contains(codeBlock)) {
          const codeRect = codeBlock.getBoundingClientRect?.();
          if (!codeRect || !editorRect) return null;
          const handleHeight = 30;
          return {
            top: codeRect.top - editorRect.top + Math.max(0, (codeRect.height - handleHeight) / 2),
            height: codeRect.height,
          };
        }
        const blockTags = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "PRE", "BLOCKQUOTE", "HR", "TABLE"]);
        while (node && node !== view.dom && !blockTags.has(node.tagName)) node = node.parentElement;
        if (node?.tagName === "P") {
          const container = node.closest?.("li, blockquote");
          if (container && view.dom.contains(container)) node = container;
        }
        if (!node || node === view.dom) return null;
        const blockRect = node.getBoundingClientRect?.();
        if (!blockRect || !editorRect) return null;
        const handleHeight = 30;
        return {
          top: blockRect.top - editorRect.top + Math.max(0, (blockRect.height - handleHeight) / 2),
          height: blockRect.height,
        };
      });
    } catch (error) {
      return null;
    }
  };

  openMenuAt = (target, options = {}) => {
    if (gone || !target) return;
    try {
      crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        const editorRect = view.dom.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const hit = view.posAtCoords({
          left: editorRect.left + editorRect.width / 2,
          top: targetRect.top + targetRect.height / 2,
        });
        if (!hit || typeof hit.pos !== "number") return;
        const selection = TextSelection.near(view.state.doc.resolve(hit.pos));
        menuTargetPos = selection.from;
        const activeSelection = view.state.selection;
        if (activeSelection.from !== activeSelection.to) {
          menuSelectionRange = { from: activeSelection.from, to: activeSelection.to };
          lastNonEmptySelectionRange = menuSelectionRange;
        } else if (!lastNonEmptySelectionRange) {
          menuSelectionRange = null;
        }
        // Opening the compact menu from hover must not steal the editor's
        // focus. On a freshly loaded document the reusable Milkdown handle
        // starts on the first block; calling focus() here made that transient
        // row become the real caret and keyboard input appeared locked there
        // for the first moments after refresh. Preserve focus only when the
        // editor was already focused (or the user explicitly focused it).
        const editorHadFocus = view.hasFocus();
        const shouldSelectTarget = editorHadFocus || options.focus === true;
        // A hover preview is allowed to position the menu, but it must not
        // mutate ProseMirror's real selection while the editor is unfocused.
        // Otherwise the first block (Milkdown's initial handle) becomes the
        // hidden selection and the first click in the document can appear to
        // stay stuck there. Explicit button activation, or an editor that is
        // already focused, still selects the target block for menu commands.
        // When the editor already owns focus, its real selection is the
        // authoritative row/caret. Replacing it with a coordinate-derived
        // selection at the horizontal center of the row can land after the
        // block; wrapping a heading from there then appears as an automatic
        // line break. Only seed a selection for an unfocused explicit open.
        if (!editorHadFocus && options.focus === true) view.dispatch(view.state.tr.setSelection(selection));
        if (options.focus === true) view.focus();
        ctx.get("menuAPICtx").show(shouldSelectTarget ? view.state.selection.from : selection.from);
      });
    } catch (error) { /* 编辑器尚未就绪时忽略 */ }
  };

  let savedSelection = null;
  // Preserve the block resolved when the floating menu opened. The reusable
  // Milkdown handle can move while the submenu is hovered; without this
  // snapshot a click may fall back to the initial first-block selection.
  let menuTargetPos = null;
  let menuSelectionRange = null;
  let lastNonEmptySelectionRange = null;
  let lastNativeListTargets = [];
  let lastNativeListSelectionAt = 0;
  const nativeSelection = () => {
    try {
      return window.getSelection?.() || document.getSelection?.() || null;
    } catch (_) {
      return null;
    }
  };
  const rememberNativeListSelection = () => {
    try {
      const selection = nativeSelection();
      const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
      if (!range || !root.contains(range.commonAncestorContainer)) {
        // Opening the row menu moves focus out of the editor and briefly
        // collapses the browser range. Keep the captured list targets alive
        // for the same bounded command window instead of erasing them before
        // the submenu action runs.
        if (selection?.isCollapsed && Date.now() - lastNativeListSelectionAt >= 15000) lastNativeListTargets = [];
        return;
      }
      if (selection.isCollapsed) {
        if (Date.now() - lastNativeListSelectionAt >= 15000) lastNativeListTargets = [];
        return;
      }
      const proseMirror = root.querySelector?.(".ProseMirror");
      if (!proseMirror || !proseMirror.contains(range.commonAncestorContainer)) return;

      // The browser selection is the source of truth while the user is
      // dragging.  Previously we kept a snapshot of every intersecting UL/OL
      // and later reapplied the command by walking the entire list.  That
      // snapshot was a second, DOM-only selection model: opening the menu
      // collapsed the browser range, while ProseMirror still had a caret, so
      // the command could target one row or repaint the whole list and then
      // be overwritten by the next NodeView update.
      //
      // Convert the native endpoints to ProseMirror positions immediately,
      // before the menu can steal focus.  The normal range transaction below
      // then selects list_item nodes exactly like a keyboard selection.  No
      // DOM list snapshot is needed for the command path.
      crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        const toPM = (container, offset) => {
          if (!container || !view.dom.contains(container)) return null;
          try {
            const position = view.posAtDOM(container, offset);
            return Number.isFinite(position) ? position : null;
          } catch (_) {
            return null;
          }
        };
        const from = toPM(range.startContainer, range.startOffset);
        const to = toPM(range.endContainer, range.endOffset);
        if (from == null || to == null || from === to) return;
        const normalized = from < to ? { from, to } : { from: to, to: from };
        lastNonEmptySelectionRange = normalized;
        menuSelectionRange = normalized;
        lastNativeListSelectionAt = Date.now();
      });

      // Keep the legacy array empty.  It remains declared for compatibility
      // with old persisted sessions, but it must never outrank the mapped PM
      // range or turn a partial list selection into a whole-list operation.
      lastNativeListTargets = [];
    } catch (_) { /* native selection can be transient while the menu moves focus */ }
  };
  document.addEventListener("selectionchange", rememberNativeListSelection, true);
  root.addEventListener("mouseup", rememberNativeListSelection, true);
  const rememberEditorSelectionRange = () => {
    try {
      crepe.editor.action((ctx) => {
        const selection = ctx.get(editorViewCtx).state.selection;
        if (selection.from !== selection.to) {
          const range = { from: selection.from, to: selection.to };
          menuSelectionRange = range;
          lastNonEmptySelectionRange = range;
        } else if (document.activeElement?.closest?.(".ProseMirror")
          && !root.querySelector?.(".milkdown-slash-menu,#docBlockAlignMenu,#docBlockColorMenu")
          // A native drag can leave ProseMirror's own selection collapsed for
          // one event loop turn.  Do not erase the freshly mapped PM range in
          // that gap; the menu command is about to consume it.
          && Date.now() - lastNativeListSelectionAt >= 15000
          && nativeSelection()?.isCollapsed !== false) {
          menuSelectionRange = null;
          lastNonEmptySelectionRange = null;
          // A collapsed caret inside the editor is a new command context.
          // Drop any previous native list range immediately; keeping it alive
          // for seconds made a later single-row command inherit an old drag.
          lastNativeListTargets = [];
          lastNativeListSelectionAt = 0;
        }
      });
    } catch (error) { /* editor may be between transactions */ }
  };
  root.addEventListener("mouseup", rememberEditorSelectionRange, true);
  root.addEventListener("keyup", rememberEditorSelectionRange, true);
  document.addEventListener("selectionchange", rememberEditorSelectionRange, true);
  let selectionToolbar = null;
  let selectionToolbarCleanup = () => {};
  const installSelectionToolbar = () => {
    if (selectionToolbar) return;
    const toolbar = document.createElement("div");
    toolbar.className = "runteams-selection-toolbar";
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-label", "文本格式工具");
    toolbar.innerHTML = `<button type="button" data-action="text" aria-label="文本样式">${lucideToolbarIcons.text}<span class="runteams-selection-chevron"></span></button><span class="runteams-selection-divider"></span><button type="button" data-action="align" aria-label="对齐">${lucideToolbarIcons.align}<span class="runteams-selection-chevron"></span></button><span class="runteams-selection-divider"></span><button type="button" data-mark="strong" aria-label="粗体">${lucideToolbarIcons.bold}</button><button type="button" data-mark="strike_through" aria-label="删除线">${lucideToolbarIcons.strike}</button><button type="button" data-mark="emphasis" aria-label="斜体">${lucideToolbarIcons.italic}</button><button type="button" data-mark="underline" aria-label="下划线">${lucideToolbarIcons.underline}</button><button type="button" data-action="link" aria-label="链接">${lucideToolbarIcons.link}</button><button type="button" data-mark="inlineCode" aria-label="代码">${lucideToolbarIcons.code}</button><button type="button" data-action="color" aria-label="文字颜色" class="is-color">${lucideToolbarIcons.color}<span class="runteams-selection-chevron"></span></button>`;
    document.body.appendChild(toolbar);
    selectionToolbar = toolbar;
    let savedRange = null;
    const getRange = () => {
      const selection = window.getSelection?.();
      const editor = root.querySelector?.(".ProseMirror");
      if (!selection || !selection.rangeCount || selection.isCollapsed || !editor) return null;
      const range = selection.getRangeAt(0);
      return editor.contains(range.startContainer) && editor.contains(range.endContainer) ? range : null;
    };
    const position = () => {
      const range = getRange();
      if (!range) { toolbar.classList.remove("is-visible"); return; }
      savedRange = range.cloneRange();
      const rect = range.getBoundingClientRect();
      if (!rect.width && !rect.height) return;
      const width = toolbar.offsetWidth || 604, height = toolbar.offsetHeight || 54;
      const left = Math.max(8, Math.min(rect.left + (rect.width - width) / 2, innerWidth - width - 8));
      const top = rect.top - height - 10 >= 8 ? rect.top - height - 10 : rect.bottom + 10;
      toolbar.style.left = `${Math.round(left)}px`;
      toolbar.style.top = `${Math.round(Math.max(8, Math.min(top, innerHeight - height - 8)))}px`;
      toolbar.classList.add("is-visible");
    };
    const restoreRange = (view) => {
      if (!savedRange) return;
      try {
        const from = view.posAtDOM(savedRange.startContainer, savedRange.startOffset);
        const to = view.posAtDOM(savedRange.endContainer, savedRange.endOffset);
        view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, Math.min(from, to), Math.max(from, to))));
      } catch (_) {}
    };
    const runBlockCommand = (name) => {
      try {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          restoreRange(view);
          const commands = ctx.get(commandsCtx);
          const [nodeName, levelText] = String(name).split(":");
          const nodeType = view.state.schema.nodes[nodeName];
          if (!nodeType) return;
          const slice = name === "blockquote" ? wrapInBlockTypeCommand.key : setBlockTypeCommand.key;
          commands.call(slice, { nodeType, attrs: levelText ? { level: Number(levelText) } : undefined });
          view.focus();
        });
      } catch (_) {}
    };
    const openChoice = (anchor, items) => {
      toolbar.querySelector(".runteams-selection-popover")?.remove();
      const popover = document.createElement("div");
      popover.className = "runteams-selection-popover";
      popover.innerHTML = items.map(item => `<button type="button" class="${item.selected ? "is-selected" : ""}" data-choice="${item.value}"><span class="choice-icon">${item.icon || ""}</span><span>${item.label}</span>${item.selected ? "<span class=choice-check>✓</span>" : ""}</button>`).join("");
      toolbar.appendChild(popover);
      popover.addEventListener("click", (event) => {
        const choice = event.target.closest("button")?.dataset.choice;
        if (!choice) return;
        if (anchor.dataset.action === "text") runBlockCommand(choice);
        if (anchor.dataset.action === "color") {
          try { crepe.editor.action((ctx) => { const view = ctx.get(editorViewCtx); restoreRange(view); const mark = view.state.schema.marks.textStyle || view.state.schema.marks.color; if (mark && !view.state.selection.empty) { const tr = view.state.tr.removeMark(view.state.selection.from, view.state.selection.to, mark); if (choice !== "reset") tr.addMark(view.state.selection.from, view.state.selection.to, mark.create({ color: choice })); view.dispatch(tr); view.focus(); } }); } catch (_) {}
        }
        if (anchor.dataset.action === "align") {
          try { crepe.editor.action((ctx) => { const view = ctx.get(editorViewCtx); restoreRange(view); const tr = view.state.tr; view.state.doc.nodesBetween(view.state.selection.from, view.state.selection.to, (node, pos) => { if (node.isBlock && node.attrs && Object.prototype.hasOwnProperty.call(node.attrs, "align")) tr.setNodeMarkup(pos, undefined, { ...node.attrs, align: choice }); }); if (tr.docChanged) view.dispatch(tr); view.focus(); }); } catch (_) {}
        }
        popover.remove(); requestAnimationFrame(position);
      });
    };
    const onMouseDown = (event) => { if (event.target.closest("button")) event.preventDefault(); };
    const onClick = (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      const markName = button.dataset.mark;
      if (markName) {
        try { crepe.editor.action((ctx) => { const view = ctx.get(editorViewCtx); restoreRange(view); const mark = view.state.schema.marks[markName]; if (mark && !view.state.selection.empty) { toggleMark(mark)(view.state, view.dispatch); view.focus(); } }); } catch (_) {}
      } else if (["text", "align", "color"].includes(button.dataset.action)) {
        openSelectionSubmenu(button);
      } else if (button.dataset.action === "link" && typeof options.onInsertLink === "function") {
        options.captureSelection?.(); options.onInsertLink();
      }
      requestAnimationFrame(position);
    };
    let submenuTimer = 0;
    let submenuCloseTimer = 0;
    let activeSubmenuButton = null;
    let sharedSubmenu = null;
    const closeSelectionSubmenu = () => {
      clearTimeout(submenuTimer);
      clearTimeout(submenuCloseTimer);
      submenuCloseTimer = 0;
      sharedSubmenu?.close?.();
      sharedSubmenu = null;
      toolbar.querySelector(".runteams-selection-popover")?.remove();
      activeSubmenuButton?.setAttribute("aria-expanded", "false");
      activeSubmenuButton = null;
    };
    const openSelectionSubmenu = (button) => {
      const kind = button.dataset.action;
      if (activeSubmenuButton === button
        && (toolbar.querySelector(".runteams-selection-popover") || sharedSubmenu?.menu?.isConnected)) return;
      closeSelectionSubmenu();
      activeSubmenuButton = button;
      button.setAttribute("aria-expanded", "true");
      if (kind === "text") {
        openChoice(button, [{value:"paragraph",label:"正文",icon:"T"},{value:"heading:1",label:"标题 1",icon:"H1"},{value:"heading:2",label:"标题 2",icon:"H2"},{value:"heading:3",label:"标题 3",icon:"H3"}]);
      } else {
          sharedSubmenu = options.onOpenBlockSubmenu?.(kind, button, toolbar);
        // The host reuses the mature submenu surface. Keep a local retry
        // trigger for the first render while the host editor is still
        // settling; this prevents a silent no-op without changing the left
        // block menu itself.
        setTimeout(() => {
          if (activeSubmenuButton !== button || document.getElementById(kind === "align" ? "docBlockAlignMenu" : "docBlockColorMenu")) return;
          if (kind === "align") openChoice(button, [{value:"left",label:"左对齐",icon:"☰",selected:true},{value:"center",label:"居中对齐",icon:"☰"},{value:"right",label:"右对齐",icon:"☰"}]);
          else openChoice(button, [{value:"reset",label:"默认文本",icon:"A"},{value:"#dc2626",label:"红色",icon:"A"},{value:"#ea580c",label:"橙色",icon:"A"},{value:"#16a34a",label:"绿色",icon:"A"},{value:"#2563eb",label:"蓝色",icon:"A"}]);
        }, 120);
      }
    };
    const onPointerOver = (event) => {
      const button = event.target.closest?.("button[data-action]");
      if (!button || button.parentElement !== toolbar || button.contains(event.relatedTarget)) return;
      if (!["text", "align", "color"].includes(button.dataset.action)) {
        closeSelectionSubmenu();
        return;
      }
      clearTimeout(submenuTimer);
      clearTimeout(submenuCloseTimer);
      submenuCloseTimer = 0;
      submenuTimer = setTimeout(() => openSelectionSubmenu(button), 40);
    };
    const onMenuPointerMove = (event) => {
      if (!activeSubmenuButton) return;
      // The host reuses the existing alignment/color surface and may mount it
      // one task after the hover event. Resolve it from the DOM on every move
      // so crossing the gap from the toolbar never looks like a true leave.
      const panel = sharedSubmenu?.menu
        || toolbar.querySelector(".runteams-selection-popover")
        || document.getElementById(activeSubmenuButton.dataset.action === "align" ? "docBlockAlignMenu" : "docBlockColorMenu");
      if (activeSubmenuButton.contains(event.target) || panel?.contains(event.target)) {
        clearTimeout(submenuCloseTimer);
      submenuCloseTimer = 0;
      } else if (!submenuCloseTimer) {
        submenuCloseTimer = setTimeout(() => { submenuCloseTimer = 0; closeSelectionSubmenu(); }, 120);
      }
    };
    const refresh = () => requestAnimationFrame(() => {
      position();
      if (!toolbar.classList.contains("is-visible")) closeSelectionSubmenu();
    });
    toolbar.addEventListener("mousedown", onMouseDown);
    toolbar.addEventListener("click", onClick);
    toolbar.addEventListener("pointerover", onPointerOver);
    document.addEventListener("pointermove", onMenuPointerMove, true);
    root.addEventListener("mouseup", refresh, true);
    root.addEventListener("keyup", refresh, true);
    document.addEventListener("selectionchange", refresh, true);
    window.addEventListener("resize", refresh);
    selectionToolbarCleanup = () => {
      closeSelectionSubmenu();
      toolbar.removeEventListener("mousedown", onMouseDown);
      toolbar.removeEventListener("click", onClick);
      toolbar.removeEventListener("pointerover", onPointerOver);
      document.removeEventListener("pointermove", onMenuPointerMove, true);
      root.removeEventListener("mouseup", refresh, true);
      root.removeEventListener("keyup", refresh, true);
      document.removeEventListener("selectionchange", refresh, true);
      window.removeEventListener("resize", refresh);
      toolbar.remove(); selectionToolbar = null;
    };
    refresh();
  };
  installSelectionToolbar();
  let linkPrepTimer = 0;
  let linkPrepPasses = 0;

  // Milkdown may finish parsing a large document in a few transactions after
  // `create()` resolves.  A short, bounded retry window catches those late
  // anchors without a MutationObserver (which would wake up on every editor
  // transaction and make long documents feel sluggish).
  const prepareEditorLinksUntilSettled = () => {
    if (gone) return;
    prepareEditorLinks(root);
    if (linkPrepPasses++ < 20) linkPrepTimer = setTimeout(prepareEditorLinksUntilSettled, 100);
  };

  const currentBlockInfo = (view) => {
    const state = view?.state;
    const selection = state?.selection;
    if (!state || !selection) return null;
    // Hovering the block handle intentionally does not focus ProseMirror, so
    // its real selection may still point at the first block. Resolve the
    // hovered handle row geometrically for presentation-only commands; this
    // keeps alignment/color applied to the row the user is looking at without
    // stealing focus or mutating the editor selection.
    let effectiveFrom = selection.$from;
    let targetDomHint = null;
    let targetAnchorHint = "";
    const targetSignature = root.dataset?.runteamsMenuTargetSignature
      || root.querySelector?.(".milkdown-block-handle .operation-item.runteams-block-style-button")?.dataset.runteamsMenuTargetSignature
      || "";
    if (targetSignature) {
      const divider = targetSignature.indexOf("|");
      const targetTag = targetSignature.slice(0, divider);
      const targetText = targetSignature.slice(divider + 1);
      const targetDom = [...view.dom.querySelectorAll?.("p,h1,h2,h3,h4,h5,h6,pre,blockquote,li,table,.milkdown-code-block,.milkdown-image-block,.milkdown-list-item-block") || []]
        .find(node => node.tagName === targetTag && String(node.textContent || "").trim().slice(0, 500) === targetText && isVisibleEditorNode(node));
      targetDomHint = targetDom || null;
      const targetRect = targetDom?.getBoundingClientRect?.();
      const editorRectForTarget = view.dom.getBoundingClientRect?.();
      if (targetRect && editorRectForTarget && targetRect.height > 0) {
        const hit = view.posAtCoords?.({left: editorRectForTarget.left + editorRectForTarget.width / 2, top: targetRect.top + targetRect.height / 2});
        if (hit && typeof hit.pos === "number") effectiveFrom = state.doc.resolve(hit.pos);
      }
    }
    if (effectiveFrom === selection.$from && typeof menuTargetPos === "number") effectiveFrom = state.doc.resolve(menuTargetPos);
    const handle = root.querySelector?.('.milkdown-block-handle .operation-item.runteams-block-style-button');
    const handleRect = handle?.getBoundingClientRect?.();
    const editorRect = view.dom.getBoundingClientRect?.();
    if (typeof menuTargetPos !== "number" && handleRect && editorRect && handleRect.width > 0 && handleRect.height > 0) {
      const hit = view.posAtCoords?.({
        left: editorRect.left + editorRect.width / 2,
        top: handleRect.top + handleRect.height / 2,
      });
      if (hit && typeof hit.pos === "number") effectiveFrom = state.doc.resolve(hit.pos);
    }
    const $from = effectiveFrom;
    let blockDepth = $from.depth;
    while (blockDepth > 0 && !$from.node(blockDepth).isBlock) blockDepth -= 1;
    if (blockDepth <= 0) return null;
    const blockPos = $from.before(blockDepth);
    let dom = view.nodeDOM(blockPos);
    if (dom?.nodeType !== 1) dom = dom?.parentElement;
    // Milkdown inserts a zero-width widget for the block handle immediately
    // before some top-level nodes. It is not the editable block itself; using
    // it here makes alignment/color appear to do nothing while styling an
    // empty widget instead of the paragraph the caret is in.
    if (dom?.classList?.contains("ProseMirror-widget")
      || dom?.closest?.(".milkdown-block-handle")) dom = null;
    if (targetDomHint) dom = targetDomHint;
    if (!dom || dom === view.dom) {
      let cursorDom = view.domAtPos?.($from.pos)?.node;
      if (cursorDom?.nodeType !== 1) cursorDom = cursorDom?.parentElement;
      const blockTags = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "PRE", "BLOCKQUOTE", "LI"]);
      while (cursorDom && cursorDom !== view.dom && !blockTags.has(cursorDom.tagName)) cursorDom = cursorDom.parentElement;
      if (cursorDom && cursorDom !== view.dom) dom = cursorDom;
    }
    let topIndex = $from.index(0);
    if (targetDomHint) {
      let topNode = targetDomHint;
      while (topNode.parentElement && topNode.parentElement !== view.dom) topNode = topNode.parentElement;
      const directIndex = [...view.dom.children].indexOf(topNode);
      if (directIndex >= 0) {
        topIndex = directIndex;
        targetAnchorHint = `block-${directIndex}`;
      }
    }
    const listDepth = (() => {
      for (let depth = blockDepth; depth > 0; depth -= 1) {
        if ($from.node(depth).type.name === "list_item") return depth;
      }
      return 0;
    })();
    const itemIndex = listDepth ? $from.index(listDepth - 1) : null;
    const anchor = targetAnchorHint || (listDepth ? `block-${topIndex}-${itemIndex}` : `block-${topIndex}`);
    if (dom?.dataset) dom.dataset.runteamsAnchor = anchor;
    return { anchor, dom, node: $from.node(blockDepth), pos: blockPos };
  };
  const presentationBlockInfo = (view) => {
    const signature = root.dataset?.runteamsMenuTargetSignature || "";
    if (!signature || !view?.dom) return null;
    const divider = signature.indexOf("|");
    const tag = signature.slice(0, divider);
    const text = signature.slice(divider + 1);
    const dom = [...view.dom.querySelectorAll?.("p,h1,h2,h3,h4,h5,h6,pre,blockquote,li,table,.milkdown-code-block,.milkdown-image-block,.milkdown-list-item-block") || []]
      .find(node => node.tagName === tag && String(node.textContent || "").trim().slice(0, 500) === text && isVisibleEditorNode(node));
    if (!dom) return null;
    let top = dom;
    while (top.parentElement && top.parentElement !== view.dom) top = top.parentElement;
    const topIndex = [...view.dom.children].indexOf(top);
    if (topIndex < 0) return null;
    const listItem = dom.closest?.(".milkdown-list-item-block,li");
    const list = listItem?.parentElement;
    const itemIndex = listItem && list && /^(UL|OL)$/.test(list.tagName)
      ? [...list.children].indexOf(listItem)
      : -1;
    const anchor = itemIndex >= 0 ? `block-${topIndex}-${itemIndex}` : `block-${topIndex}`;
    dom.dataset.runteamsAnchor = anchor;
    return { anchor, dom };
  };
  // Resolve the block captured when the floating handle opened the menu. This
  // lookup intentionally bypasses ProseMirror's coordinate selection: the
  // handle itself is rendered through a zero-width widget, so a coordinate
  // lookup can otherwise resolve that widget instead of the visible paragraph.
  const capturedMenuBlockInfo = (view) => {
    const editor = view?.dom;
    const signature = root.dataset?.runteamsMenuTargetSignature
      || root.querySelector?.(".milkdown-block-handle .operation-item.runteams-block-style-button")?.dataset?.runteamsMenuTargetSignature
      || "";
    if (!editor || !signature) return null;
    const divider = signature.indexOf("|");
    if (divider <= 0) return null;
    const tag = signature.slice(0, divider);
    const text = signature.slice(divider + 1);
    const selector = "p,h1,h2,h3,h4,h5,h6,pre,blockquote,li,table,.milkdown-code-block,.milkdown-image-block,.milkdown-list-item-block";
    // The hover helper owns its captured pointer node in a separate closure;
    // do not reach across that scope here. The active-row marker is the
    // shared DOM handoff and, unlike a text signature, distinguishes repeated
    // list rows reliably.
    const candidates = [...editor.querySelectorAll(selector)].filter((node) => (
      node.tagName === tag && String(node.textContent || "").trim().slice(0, 500) === text
    ));
    const dom = candidates.find((node) => node.classList?.contains("runteams-menu-active-row") && isVisibleEditorNode(node))
      || candidates.find((node) => isVisibleEditorNode(node))
      || candidates[0];
    if (!dom) return null;
    let top = dom;
    while (top.parentElement && top.parentElement !== editor) top = top.parentElement;
    const topIndex = [...editor.children].indexOf(top);
    if (topIndex < 0) return null;
    const listItem = dom.closest?.(".milkdown-list-item-block,li");
    const list = listItem?.parentElement;
    const itemIndex = listItem && list && /^(UL|OL)$/.test(list.tagName)
      ? [...list.children].indexOf(listItem)
      : -1;
    const anchor = itemIndex >= 0 ? `block-${topIndex}-${itemIndex}` : `block-${topIndex}`;
    dom.dataset.runteamsAnchor = anchor;
    return { anchor, dom, node: null, pos: null };
  };
  // posAtDOM(block, 0) points at the beginning of the block's content for
  // ProseMirror block nodes (rather than before the node itself). Normalize
  // that position back to the nearest block boundary before nodeAt/setNodeMarkup,
  // otherwise a style command can land on the next sibling block.
  const blockPositionFromDom = (view, dom) => {
    if (!view || !dom || !view.state?.doc || typeof view.posAtDOM !== "function") return null;
    // List-item NodeViews expose a DIV wrapper around the semantic LI. Resolve
    // that wrapper through the list-item boundary first; generic text/DOM
    // matching cannot distinguish repeated rows with identical text.
    if (dom.matches?.(".milkdown-list-item-block,li")) {
      const listPos = listItemPositionFromDom(view, dom);
      if (Number.isFinite(listPos)) return listPos;
    }
    // Text/tag identity is more reliable than coordinates around Milkdown's
    // widget nodes. Resolve it first, before trying the DOM position mapping.
    const tag = String(dom.tagName || "").toUpperCase();
    const text = String(dom.textContent || "").trim().slice(0, 500);
    let textMatch = null;
    view.state.doc.descendants((node, pos) => {
      if (textMatch != null || !node.isBlock) return;
      const level = node.attrs?.level;
      const nodeTag = node.type.name === "paragraph" ? "P"
        : node.type.name === "heading" ? `H${level || 1}`
        : node.type.name === "blockquote" ? "BLOCKQUOTE"
        : node.type.name === "code_block" ? "PRE"
        : "";
      if (nodeTag === tag && node.textContent.trim().slice(0, 500) === text) textMatch = pos;
    });
    if (textMatch != null) return textMatch;
    // Prefer ProseMirror's own node-to-DOM mapping. This is exact even when
    // Milkdown has inserted non-editable widgets between blocks; coordinate
    // conversion alone can otherwise resolve the heading after the target.
    let mapped = null;
    view.state.doc.descendants((node, pos) => {
      if (mapped != null || !node.isBlock) return;
      const candidate = view.nodeDOM?.(pos);
      if (candidate === dom || candidate?.contains?.(dom) || dom.contains?.(candidate)) mapped = pos;
    });
    if (mapped != null) return mapped;
    const max = view.state.doc.content.size;
    const probes = dom.firstChild ? [dom.firstChild, dom] : [dom];
    for (const probe of probes) {
      const raw = view.posAtDOM(probe, 0);
      if (!Number.isFinite(raw)) continue;
      const $pos = view.state.doc.resolve(Math.max(0, Math.min(raw, max)));
      let depth = $pos.depth;
      while (depth > 0 && !$pos.node(depth).isBlock) depth -= 1;
      if (depth > 0) return $pos.before(depth);
    }
    return null;
  };
  const blockAnchorFromPosition = (view, pos) => {
    if (!view?.state?.doc || !Number.isFinite(pos)) return "";
    const $pos = view.state.doc.resolve(pos);
    const topIndex = $pos.index(0);
    for (let depth = $pos.depth; depth > 0; depth -= 1) {
      if ($pos.node(depth).type.name !== "list_item") continue;
      return `block-${topIndex}-${$pos.index(depth - 1)}`;
    }
    return `block-${topIndex}`;
  };
  const listItemPositionFromDom = (view, dom) => {
    if (!view?.state?.doc || !dom || typeof view.posAtDOM !== "function") return null;
    const probe = dom.querySelector?.("li") || dom;
    try {
      const raw = view.posAtDOM(probe, 0);
      if (!Number.isFinite(raw)) return null;
      const resolved = view.state.doc.resolve(Math.max(0, Math.min(raw, view.state.doc.content.size)));
      for (let depth = resolved.depth; depth > 0; depth -= 1) {
        if (resolved.node(depth).type.name === "list_item") return resolved.before(depth);
      }
    } catch (_) { /* the NodeView may be between redraws */ }
    return null;
  };
  const blockAnchorFromDom = (view, dom) => {
    if (!view?.state?.doc || !dom) return "";
    const tag = String(dom.tagName || "").toUpperCase();
    const text = String(dom.textContent || "").trim().slice(0, 500);
    const matches = (node) => {
      const level = node.attrs?.level;
      const nodeTag = node.type.name === "paragraph" ? "P"
        : node.type.name === "heading" ? `H${level || 1}`
        : node.type.name === "blockquote" ? "BLOCKQUOTE"
        : node.type.name === "code_block" ? "PRE" : "";
      return nodeTag === tag && node.textContent.trim().slice(0, 500) === text;
    };
    let found = "";
    view.state.doc.forEach((node, _offset, index) => {
      if (found || !matches(node)) return;
      found = `block-${index}`;
    });
    return found;
  };
  const deleteCurrentBlock = (view, ctx) => {
    const info = currentBlockInfo(view);
    if (!info) return false;
    const { state } = view;
    const from = info.pos;
    const to = info.pos + info.node.nodeSize;
    const tr = state.doc.childCount <= 1
      ? state.tr.replaceWith(from, to, paragraphSchema.type(ctx).create())
      : state.tr.delete(from, to);
    view.dispatch(tr.scrollIntoView());
    view.focus();
    return true;
  };
  const applyDomBlockStyle = (style = {}) => {
    if (gone) return null;
    let result = null;
    try {
      crepe.editor.action((ctx) => {
        const view = ctx.get(editorViewCtx);
        const info = capturedMenuBlockInfo(view) || presentationBlockInfo(view) || currentBlockInfo(view);
        let dom = info?.dom;
        let explicitDomTarget = false;
        // Menu clicks can arrive after the floating handle has released its
        // selection. When the host supplies the target signature, resolve the
        // block directly so the style update still lands on the clicked node.
        const explicitSignature = String(style.signature || "");
        if (explicitSignature) {
          const divider = explicitSignature.indexOf("|");
          const tag = explicitSignature.slice(0, divider);
          const text = explicitSignature.slice(divider + 1);
          const matchesSignature = (node) => node?.tagName === tag
            && String(node.textContent || "").trim().slice(0, 500) === text;
          // The captured handle DOM is authoritative.  A text signature is
          // only a persistence fallback and is ambiguous for repeated list
          // rows (for example many rows containing “产品：jira”).
          const captured = dom && matchesSignature(dom) && isVisibleEditorNode(dom)
            ? dom
            : null;
          const candidates = [...root.querySelectorAll?.(".ProseMirror p,.ProseMirror h1,.ProseMirror h2,.ProseMirror h3,.ProseMirror h4,.ProseMirror h5,.ProseMirror h6,.ProseMirror blockquote,.ProseMirror pre,.ProseMirror ul,.ProseMirror ol,.ProseMirror li,.ProseMirror .milkdown-list-item-block") || []]
            .filter(node => matchesSignature(node) && isVisibleEditorNode(node));
          const candidate = candidates.find(node => node.classList?.contains("runteams-menu-active-row"))
            || captured
            || candidates[0];
          if (candidate) {
            dom = candidate;
            explicitDomTarget = true;
          }
        }
        if (!dom) {
          const fallback = root.querySelector?.(".ProseMirror")?.children?.[view.state.selection.$from.index(0)];
          dom = fallback || null;
        }
        if (!dom) return;
        // Style commands are patches. A color/background/indent command does
        // not carry an alignment field and must not clear the existing one.
        // Keep `null` for an omitted field; use an empty string only for an
        // explicit but invalid/clearing alignment value.
        const align = style.align == null
          ? null
          : (["left", "center", "right"].includes(style.align) ? style.align : "");
        const indent = Math.max(0, Math.min(6, Number(style.indent) || 0));
        // Seed the in-memory decoration state before touching the DOM. List
        // item NodeViews can be reconciled during the menu transaction; if an
        // older decoration still says `right`, it would immediately repaint
        // the visible wrapper after a left/center command. The captured
        // ProseMirror anchor and signature are both updated up front so the
        // next decoration pass cannot resurrect that stale value.
        const earlyAnchor = info?.anchor || "";
        const earlySignature = explicitSignature || `${dom.tagName}|${String(dom.textContent || "").trim().slice(0, 500)}`;
        if (align && earlyAnchor) {
          blockStyleMemory[earlyAnchor] = {
            ...(blockStyleMemory[earlyAnchor] || {}),
            align,
          };
        }
        if (align && earlySignature) {
          blockStyleMemory[`sig:${earlySignature}`] = {
            ...(blockStyleMemory[`sig:${earlySignature}`] || {}),
            align,
          };
        }
        // A text selection can span several blocks.  The floating handle is
        // anchored to the first visible row, but alignment/color commands
        // must apply to every paragraph/heading intersecting that selection.
        const activeRange = menuSelectionRange || lastNonEmptySelectionRange;
        // List items are real ProseMirror blocks too, but their visible text is
        // nested in a paragraph inside the LI. Apply the presentation style
        // to both nodes so list alignment cannot be swallowed by the nested
        // paragraph's default rule or by a recreated list-item view.
        const styleTargetsForDom = (target) => {
          if (!target?.querySelectorAll) return target ? [target] : [];
          const list = target.matches?.("UL,OL") ? target : target.closest?.("ul,ol");
          if (!list) return [target];
          if (target.matches?.("UL,OL")) {
            return [list, ...[...list.children].flatMap((item) => [item, ...item.querySelectorAll?.("p") || []])];
          }
          const item = target.closest?.(".milkdown-list-item-block,li") || target;
          // The list-item NodeView is a DIV wrapper with a nested semantic LI
          // and paragraph. Keep the target local; range/native-list branches
          // are responsible for explicitly expanding a multi-row selection.
          return [item, ...item.querySelectorAll?.("li,p,.content-dom") || []];
        };
        const setDomStyle = (target, value) => {
          styleTargetsForDom(target).forEach((node) => {
            if (value.align) node.style.setProperty("text-align", value.align, "important");
            else if (value.align === "") node.style.removeProperty("text-align");
            if (value.indent != null) {
              node.dataset.runteamsIndent = String(value.indent);
              node.style.setProperty("--runteams-block-indent", `${value.indent * 24}px`);
            }
            if (value.color === "reset") node.style.removeProperty("color");
            else if (value.color) node.style.setProperty("color", value.color, "important");
            if (value.background === "reset") node.style.removeProperty("background-color");
            else if (value.background) node.style.setProperty("background-color", value.background, "important");
          });
        };
        const styleAttrs = (node, value) => {
          if (!node?.attrs) return null;
          const attrs = { ...node.attrs };
          if (value.align != null) attrs.align = value.align || "left";
          if (value.color != null) attrs.color = value.color === "reset" ? "" : String(value.color || "");
          if (value.background != null) attrs.background = value.background === "reset" ? "" : String(value.background || "");
          if (value.indent != null) attrs.indent = Math.max(0, Math.min(6, Number(value.indent) || 0));
          return Object.keys(attrs).some((key) => attrs[key] !== node.attrs[key]) ? attrs : null;
        };
        // A list item is a structural node whose visible text lives in a
        // direct paragraph/heading child. Formatting both layers is required:
        // the wrapper controls list layout, while the child node's attrs are
        // what Milkdown uses when it recreates the paragraph DOM. Updating
        // only one layer is the reason an alignment could appear briefly and
        // then snap back after a redraw.
        const collectStyleAttrUpdates = (updates, pos, node, value) => {
          if (!node || pos == null) return;
          const add = (targetPos, targetNode) => {
            const attrs = styleAttrs(targetNode, value);
            if (attrs) updates.push({ pos: targetPos, node: targetNode, attrs });
          };
          add(pos, node);
          if (node.type?.name !== "list_item" || !node.content?.size) return;
          node.forEach((child, offset) => {
            if (["paragraph", "heading", "blockquote", "code_block"].includes(child.type?.name)) {
              add(pos + 1 + offset, child);
            }
          });
        };
        // The native browser range was converted to `menuSelectionRange` in
        // rememberNativeListSelection(). Do not keep a second DOM-list
        // command path here: it cannot distinguish a partial list selection
        // from the whole UL/OL and is exactly what caused alignment/color to
        // flash and then snap back after Milkdown reconciled the view.
        if (activeRange && activeRange.from < activeRange.to) {
          const selected = [];
          const blockNames = new Set(["paragraph", "heading", "blockquote", "code_block", "list_item"]);
          const addSelectedBlock = (node, pos) => {
            if (!node?.isBlock || !blockNames.has(node.type.name)) return;
            // A list item's paragraph is represented by the list_item block;
            // styling both would create duplicate anchors and make a range
            // appear to skip or affect the neighbouring row.
            if (node.type.name === "paragraph") {
              const $resolved = view.state.doc.resolve(pos);
              for (let depth = $resolved.depth; depth > 0; depth -= 1) {
                if ($resolved.node(depth).type.name === "list_item") return;
              }
            }
            const candidate = view.nodeDOM?.(pos);
            if (!candidate || candidate.nodeType !== 1) return;
            if (selected.some((item) => item.pos === pos)) return;
            selected.push({ node, pos, dom: candidate });
          };
          view.state.doc.nodesBetween(activeRange.from, activeRange.to, (node, pos) => {
            addSelectedBlock(node, pos);
          });
          // ProseMirror's nodesBetween excludes a block when a selection
          // starts/ends exactly at its boundary. Include the blocks touched
          // by both endpoints so a keyboard/mouse selection never drops the
          // first or last selected row.
          const addBoundaryBlock = (position) => {
            const bounded = Math.max(0, Math.min(position, view.state.doc.content.size));
            const resolved = view.state.doc.resolve(bounded);
            for (let depth = resolved.depth; depth > 0; depth -= 1) {
              const node = resolved.node(depth);
              if (!blockNames.has(node.type.name)) continue;
              addSelectedBlock(node, resolved.before(depth));
              break;
            }
          };
          addBoundaryBlock(activeRange.from);
          addBoundaryBlock(Math.max(activeRange.from, activeRange.to - 1));
          selected.sort((a, b) => a.pos - b.pos);
          if (selected.length > 1) {
            const attrUpdates = [];
            const targets = selected.map(({ node, pos, dom: target }) => {
              const targetAnchor = blockAnchorFromDom(view, target) || blockAnchorFromPosition(view, pos);
              collectStyleAttrUpdates(attrUpdates, pos, node, {
                align,
                indent: style.indent != null ? indent : null,
                color: style.color,
                background: style.background,
              });
              setDomStyle(target, { align, indent: style.indent != null ? indent : null, color: style.color, background: style.background });
              // Keep every selected block's decoration memory in sync with
              // the command. List NodeViews can be reconciled after the menu
              // closes; without a per-target update, an older centered row
              // is painted back over the newly aligned paragraph.
              const targetSignature = target.tagName + "|" + String(target.textContent || "").trim().slice(0, 500);
              if (align && targetAnchor) {
                blockStyleMemory[targetAnchor] = {
                  ...(blockStyleMemory[targetAnchor] || {}),
                  align,
                };
              }
              if (align && targetSignature) {
                blockStyleMemory[`sig:${targetSignature}`] = {
                  ...(blockStyleMemory[`sig:${targetSignature}`] || {}),
                  align,
                };
              }
              const listContainer = target.closest?.("ul,ol");
              if (listContainer && align) {
                listContainer.style.setProperty("text-align", align, "important");
                [...listContainer.children].forEach((sibling) => {
                  sibling.style.setProperty("text-align", align, "important");
                  sibling.querySelectorAll?.("li,p,.content-dom").forEach((node) => node.style.setProperty("text-align", align, "important"));
                });
              }
              return {
                anchor: targetAnchor,
                dom: target,
                signature: `${target.tagName}|${String(target.textContent || "").trim().slice(0, 500)}`,
                align: target.style.textAlign || "left",
                indent: Number(target.dataset.runteamsIndent || 0),
                color: target.style.color || "",
                background: target.style.backgroundColor || "",
              };
            });
            if (attrUpdates.length) {
              let tr = view.state.tr;
              attrUpdates.forEach(({ pos, node: targetNode, attrs }) => {
                tr = tr.setNodeMarkup(pos, targetNode.type, attrs, targetNode.marks);
              });
              if (tr.docChanged) view.dispatch(tr);
            }
            result = { ...targets[0], targets };
            return;
          }
        }
        // If the menu supplied an explicit DOM signature, the captured
        // selection position may belong to the block that happened to own the
        // caret when the floating handle opened. Recompute the ProseMirror
        // position from the resolved target instead of dispatching attrs to
        // that stale position (which made the visible command appear to do
        // nothing, especially for lists and adjacent paragraphs).
        const domPos = explicitDomTarget
          ? blockPositionFromDom(view, dom)
          : (info?.pos == null ? blockPositionFromDom(view, dom) : info.pos);
        // Keep the style in the presentation decoration memory. Mutating the
        // document with a position guessed from a DOM node is unsafe here:
        // Milkdown's widget nodes make that position point at the following
        // block in some layouts. The decoration is applied using the exact
        // ProseMirror block anchor below, so the clicked row remains the one
        // that changes without changing the markdown document structure.
        const domAnchor = (() => {
          let top = dom;
          while (top?.parentElement && top.parentElement !== view.dom) top = top.parentElement;
          const topIndex = top ? [...view.dom.children].indexOf(top) : -1;
          const listItem = dom?.closest?.(".milkdown-list-item-block,li");
          const list = listItem?.parentElement;
          const itemIndex = listItem && list && /^(UL|OL)$/.test(list.tagName)
            ? [...list.children].indexOf(listItem)
            : -1;
          return topIndex >= 0 && itemIndex >= 0
            ? `block-${topIndex}-${itemIndex}`
            : (topIndex >= 0 ? `block-${topIndex}` : "");
        })();
        const pmAnchor = domAnchor || info?.anchor || blockAnchorFromDom(view, dom) || blockAnchorFromPosition(view, domPos);
        const targetInfo = pmAnchor ? { ...info, anchor: pmAnchor } : info;
        if (pmAnchor && dom?.dataset) dom.dataset.runteamsAnchor = pmAnchor;
        // Persist supported styles as node attrs as well as applying them to
        // the current DOM node.  Milkdown may recreate that DOM node while a
        // menu closes; node attrs are part of the editor state and therefore
        // survive the redraw for headings and paragraphs alike.
        const nodePos = Number.isFinite(domPos) ? domPos : null;
        const node = nodePos == null ? null : view.state.doc.nodeAt(nodePos);
        if (node && ["paragraph", "heading", "list_item"].includes(node.type.name)) {
          const attrUpdates = [];
          collectStyleAttrUpdates(attrUpdates, nodePos, node, {
            align,
            indent: style.indent != null ? indent : null,
            color: style.color,
            background: style.background,
          });
          if (attrUpdates.length) {
            let tr = view.state.tr;
            attrUpdates.forEach(({ pos, node: targetNode, attrs }) => {
              tr = tr.setNodeMarkup(pos, targetNode.type, attrs, targetNode.marks);
            });
            if (tr.docChanged) view.dispatch(tr);
            dom = view.nodeDOM?.(nodePos) || dom;
          }
        }
        setDomStyle(dom, { align, indent: style.indent != null ? indent : null, color: style.color, background: style.background });
        // A single list-item command must stay on the clicked row. Multi-row
        // selections are handled explicitly by the range/native-list paths
        // above; applying every sibling here made one-row clicks fan out.
        result = { ...targetInfo, signature: `${dom.tagName}|${String(dom.textContent || "").trim().slice(0, 500)}`, align: dom.style.textAlign || "left", indent, color: dom.style.color || "", background: dom.style.backgroundColor || "" };
      });
    } catch (error) { /* editor may be between transactions */ }
    // Last-resort DOM reconciliation for submenu focus transitions. Some
    // Milkdown releases return from editor.action with only the handle row
    // even though the browser range still spans the whole list. Re-read that
    // live range after the action and make every intersecting list item
    // authoritative before the decoration pass runs.
    try {
      const selection = nativeSelection();
      const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
      const area = root.querySelector?.(".ProseMirror");
      const lists = range && !selection.isCollapsed
        ? [...area?.querySelectorAll?.("ul,ol") || []].filter((list) => { try { return range.intersectsNode(list); } catch (_) { return false; } })
        : [];
      if ((style.align || style.color != null || style.background != null) && lists.length) {
        const align = style.align == null
          ? null
          : (["left", "center", "right"].includes(style.align) ? style.align : "");
        const records = [];
        lists.forEach((list) => {
          const topIndex = area ? [...area.children].indexOf(list) : -1;
          list.style.setProperty("text-align", align || "left", "important");
          [...list.children].forEach((item, itemIndex) => {
            const targets = [item, ...item.querySelectorAll?.("li,p,.content-dom") || []];
            targets.forEach((node) => {
              if (align) node.style.setProperty("text-align", align, "important");
              if (style.color === "reset") node.style.removeProperty("color");
              else if (style.color) node.style.setProperty("color", style.color, "important");
              if (style.background === "reset") node.style.removeProperty("background-color");
              else if (style.background) node.style.setProperty("background-color", style.background, "important");
            });
            const anchor = topIndex >= 0 ? `block-${topIndex}-${itemIndex}` : "";
            const signature = `${item.tagName}|${String(item.textContent || "").trim().slice(0, 500)}`;
            const memory = {
              ...(align ? { align } : {}),
              ...(style.color != null ? { color: style.color === "reset" ? "" : String(style.color || "") } : {}),
              ...(style.background != null ? { background: style.background === "reset" ? "" : String(style.background || "") } : {}),
            };
            if (anchor) blockStyleMemory[anchor] = { ...(blockStyleMemory[anchor] || {}), ...memory };
            blockStyleMemory[`sig:${signature}`] = { ...(blockStyleMemory[`sig:${signature}`] || {}), ...memory };
            records.push({
              anchor,
              dom: item,
              signature,
              align: align || getComputedStyle(item).textAlign || "left",
              indent: Number(item.dataset.runteamsIndent || 0),
              color: item.style.color || "",
              background: item.style.backgroundColor || "",
            });
          });
        });
        result = { dom: lists[0], align: align || "left", targets: records };
      }
    } catch (_) { /* native selection may disappear during teardown */ }
    // A menu provider can briefly make the editor action unavailable while
    // it is tearing down its floating view. Keep the user-visible operation
    // reliable by applying the captured signature directly in that window;
    // the host persistence layer will hydrate it again after the redraw.
    if (!result && style.signature) {
      const divider = String(style.signature).indexOf("|");
      const tag = String(style.signature).slice(0, divider);
      const text = String(style.signature).slice(divider + 1);
      const fallbackCandidates = [...root.querySelectorAll?.(".ProseMirror p,.ProseMirror h1,.ProseMirror h2,.ProseMirror h3,.ProseMirror h4,.ProseMirror h5,.ProseMirror h6,.ProseMirror blockquote,.ProseMirror pre,.ProseMirror ul,.ProseMirror ol,.ProseMirror li,.ProseMirror .milkdown-list-item-block") || []]
        .filter(node => node.tagName === tag && String(node.textContent || "").trim().slice(0, 500) === text && isVisibleEditorNode(node));
      const candidate = fallbackCandidates.find(node => node.classList?.contains("runteams-menu-active-row")) || fallbackCandidates[0];
      if (candidate) {
        const align = style.align == null
          ? null
          : (["left", "center", "right"].includes(style.align) ? style.align : "left");
        if (style.align != null) {
          const list = candidate.matches?.("UL,OL") ? candidate : candidate.closest?.("ul,ol");
          const item = candidate.closest?.(".milkdown-list-item-block,li") || candidate;
          const targets = list
            ? (candidate.matches?.("UL,OL") ? [list, ...[...list.children].flatMap((sibling) => [sibling, ...sibling.querySelectorAll?.("p") || []])]
              : [item, ...item.querySelectorAll?.("p") || []])
            : [candidate];
          targets.forEach((node) => node.style.setProperty("text-align", align, "important"));
        }
        if (style.color === "reset") candidate.style.removeProperty("color");
        else if (style.color) candidate.style.setProperty("color", style.color, "important");
        if (style.background === "reset") candidate.style.removeProperty("background-color");
        else if (style.background) candidate.style.setProperty("background-color", style.background, "important");
        const anchor = candidate.dataset.runteamsAnchor || "";
        result = { anchor, dom: candidate, signature: style.signature, align, indent: 0, color: candidate.style.color || "", background: candidate.style.backgroundColor || "" };
      }
    }
    if (result) {
      const results = Array.isArray(result.targets) ? result.targets : [result];
      const resultAnchors = new Set(results.map((item) => String(item?.anchor || "")).filter(Boolean));
      const syncResultListAlignment = () => {
        if (!style.align) return;
        const currentItems = [...root.querySelectorAll?.(".ProseMirror .milkdown-list-item-block") || []]
          .filter((item) => resultAnchors.has(String(item.dataset?.runteamsAnchor || "")));
        const lists = new Set();
        results.forEach((item) => {
          const dom = item?.dom;
          if (!dom?.isConnected) return;
          const list = dom.matches?.("UL,OL") ? dom : dom.closest?.("ul,ol");
          if (list) lists.add(list);
        });
        currentItems.forEach((item) => {
          const list = item.closest?.("ul,ol");
          if (list) lists.add(list);
          item.style.setProperty("text-align", style.align, "important");
          item.querySelectorAll?.("li,p,.content-dom").forEach((node) => node.style.setProperty("text-align", style.align, "important"));
        });
        // A single-row command must not move unselected siblings through the
        // parent list. Multi-row results (or an explicit list target) do need
        // the container rewritten to prevent stale inherited alignment.
        if (currentItems.length > 1 || results.some((item) => item?.dom?.matches?.("UL,OL"))) {
          lists.forEach((list) => {
            list.style.setProperty("text-align", style.align, "important");
            [...list.children].forEach((item) => item.style.setProperty("text-align", style.align, "important"));
          });
        }
      };
      syncResultListAlignment();
      results.forEach((item) => {
        if (!item?.anchor) return;
        blockStyleMemory[item.anchor] = {
          align: item.align,
          indent: item.indent,
          color: item.color,
          background: item.background,
        };
        if (item.dom) {
          const signature = `${item.dom.tagName}|${String(item.dom.textContent || "").trim().slice(0, 500)}`;
          if (!/^DIV\|/.test(signature)) blockStyleMemory[`sig:${signature}`] = blockStyleMemory[item.anchor];
        }
      });
      try {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          view.dispatch(view.state.tr.setMeta(blockStylePluginKey, true));
        });
      } catch (error) { /* ignore transient editor state */ }
      if (typeof options.onBlockStyleChange === "function") results.forEach((item) => options.onBlockStyleChange(item));
      // Menu activation moves focus away from ProseMirror.  Restore the
      // editor's current selection immediately after the style transaction,
      // then remeasure the active row after its alignment/background has
      // changed.  Without this handoff the caret and the independent row
      // highlight stay at their pre-style geometry until the next mouse
      // click causes a selection/viewport refresh.
      const refreshStyleInteraction = () => {
        if (gone) return;
        suppressMenuRowHighlight = true;
        if (styleHighlightSuppressionTimer) clearTimeout(styleHighlightSuppressionTimer);
        clearMenuRowHighlight();
        // The provider normally closes the menu immediately, but some
        // transactions leave it mounted for a few ticks. Keep the old row
        // highlight suppressed through that window, then restore it only if
        // a genuinely open menu still needs one.
        styleHighlightSuppressionTimer = setTimeout(() => {
          styleHighlightSuppressionTimer = null;
          suppressMenuRowHighlight = false;
          if (gone) return;
          const menu = root.querySelector(".milkdown-slash-menu");
          if (menu?.dataset.show !== "true" && menu?.dataset.runteamsForceOpen !== "true") {
            clearMenuRowHighlight();
            return;
          }
          const target = root.querySelector(".milkdown-block-handle .operation-item");
          const focused = getBlockLabel?.getFocusedBlock?.();
          if (focused) syncMenuRowHighlight(target, true, focused);
          else if (menuActiveBlock) renderMenuRowHighlight(menuActiveBlock);
        }, 450);
        try {
          crepe.editor.action((ctx) => {
            const view = ctx.get(editorViewCtx);
            view.focus();
          });
        } catch (_) { /* editor may be between provider transactions */ }
        const refresh = () => {
          if (gone) return;
          if (suppressMenuRowHighlight) {
            clearMenuRowHighlight();
            return;
          }
          syncFocusedButton();
          const menu = root.querySelector(".milkdown-slash-menu");
          if (menu?.dataset.show !== "true" && menu?.dataset.runteamsForceOpen !== "true") {
            // The row mark is a menu-only affordance.  A style command closes
            // the provider menu after updating the node; clear the old layer
            // in that same refresh so it cannot remain painted at the
            // pre-alignment coordinates until the next pointer event.
            clearMenuRowHighlight();
            return;
          }
          const target = root.querySelector(".milkdown-block-handle .operation-item");
          const focused = getBlockLabel?.getFocusedBlock?.();
          if (focused) syncMenuRowHighlight(target, true, focused);
          else if (menuActiveBlock) renderMenuRowHighlight(menuActiveBlock);
        };
        requestAnimationFrame(refresh);
        setTimeout(refresh, 0);
        setTimeout(refresh, 80);
      };
      refreshStyleInteraction();
      // Milkdown may refresh a NodeView while closing the menu. Reapply the
      // presentation-only style on the next frame so a submenu click cannot
      // appear to do nothing.
      let passes = 0;
      const reapply = () => {
        if (gone || passes++ > 3) return;
        syncResultListAlignment();
        handle.hydrateBlockStyles?.(blockStyleMemory);
        const menu = root.querySelector(".milkdown-slash-menu");
        if (suppressMenuRowHighlight) {
          clearMenuRowHighlight();
        } else if (menu?.dataset.show === "true" || menu?.dataset.runteamsForceOpen === "true") {
          if (menuActiveBlock) renderMenuRowHighlight(menuActiveBlock);
        } else {
          clearMenuRowHighlight();
        }
        requestAnimationFrame(reapply);
      };
      requestAnimationFrame(reapply);
      // The floating block menu closes through a second provider transaction
      // which can land after the animation frames above. Re-dispatch the
      // decoration state after that transaction window as well.
      [0, 50, 150, 300, 600, 1000].forEach((delay) => {
        setTimeout(() => { syncResultListAlignment(); handle.hydrateBlockStyles?.(blockStyleMemory); }, delay);
      });
    }
    return result;
  };
  crepe.on((listener) => {
    listener.markdownUpdated((ctx, markdown, previous) => {
      if (!live || gone || markdown === previous) return;
      if (typeof options.onChange === "function") options.onChange(fromEditorMarkdown(markdown));
    });
  });

  const handle = {
    getMarkdown: () => (gone ? "" : fromEditorMarkdown(crepe.getMarkdown())),
    setReadonly: (value) => {
      if (!gone) crepe.setReadonly(!!value);
      return handle;
    },
    focus: () => {
      const area = root && root.querySelector ? root.querySelector(".ProseMirror") : null;
      if (area) area.focus();
      return handle;
    },
    // 由宿主在打开外部插入控件前保存编辑器选区，避免点击控件后选区丢失。
    captureSelection: () => {
      if (gone || !live) return handle;
      try {
        const { selection, doc } = crepe.editor.action((ctx) => {
          const state = ctx.get(editorViewCtx).state;
          return { selection: state.selection, doc: state.doc };
        });
        savedSelection = {
          from: selection.from,
          to: selection.to,
          text: selection.empty ? "" : doc.textBetween(selection.from, selection.to, " ").trim(),
        };
      } catch (error) { /* 编辑器尚未就绪时忽略 */ }
      return handle;
    },
    getCapturedSelectionText: () => String(savedSelection?.text || ""),
    getCurrentBlockStyle: () => {
      if (gone || !live) return null;
      let result = null;
      try {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          const info = capturedMenuBlockInfo(view) || presentationBlockInfo(view) || currentBlockInfo(view);
          if (!info?.dom) return;
          // Resolve the exact block signature captured by the host menu
          // before reading its state.  The floating handle can retain a
          // stale ProseMirror selection while the menu is open, which made
          // the highlight describe the previous row instead of this one.
          let dom = info.dom;
          const signature = String(root.dataset?.runteamsMenuTargetSignature || "");
          if (signature) {
            const divider = signature.indexOf("|");
            const tag = signature.slice(0, divider);
            const text = signature.slice(divider + 1);
            const exactCandidates = [...root.querySelectorAll?.(".ProseMirror p,.ProseMirror h1,.ProseMirror h2,.ProseMirror h3,.ProseMirror h4,.ProseMirror h5,.ProseMirror h6,.ProseMirror blockquote,.ProseMirror pre,.ProseMirror .milkdown-list-item-block") || []]
              .filter(node => node.tagName === tag && String(node.textContent || "").trim().slice(0, 500) === text && isVisibleEditorNode(node));
            const exact = exactCandidates.find(node => node.classList?.contains("runteams-menu-active-row")) || exactCandidates[0];
            if (exact) dom = exact;
          }
          const computed = dom.ownerDocument?.defaultView?.getComputedStyle?.(dom);
          const saved = signature ? blockStyleMemory[`sig:${signature}`] : null;
          const rawAlign = dom.style.textAlign || computed?.textAlign || saved?.align || "left";
          const align = rawAlign === "right" || rawAlign === "center" ? rawAlign : "left";
          result = {
            ...info,
            dom,
            align,
            indent: Number(dom.dataset.runteamsIndent || 0),
            color: dom.style.color || "",
            background: dom.style.backgroundColor || "",
          };
        });
      } catch (error) { /* ignore transient editor state */ }
      return result;
    },
    setBlockAlignment: (align, signature = "") => {
      return applyDomBlockStyle({ align, signature });
    },
    // All block formatting commands go through the editor controller. The
    // host may provide a stable signature for a block-menu target, but it
    // must not mutate editor DOM or maintain a second formatting state.
    applyBlockStyle: (style = {}) => applyDomBlockStyle(style),
    setBlockIndent: (indent) => applyDomBlockStyle({ indent }),
    setBlockColor: (color, signature = "") => applyDomBlockStyle({ color, signature }),
    setBlockBackground: (background, signature = "") => applyDomBlockStyle({ background, signature }),
    hydrateBlockStyles: (styles = {}) => {
      if (gone) return handle;
      const area = root.querySelector?.(".ProseMirror");
      if (!area) return handle;
      // Hydrate through the ProseMirror decoration plugin. Walking
      // `area.children` counts Milkdown widgets (code-block chrome, upload
      // controls, handles) as document blocks and shifts styles onto the next
      // row. The plugin walks the ProseMirror document itself, so its anchors
      // stay aligned with the actual nodes.
      Object.assign(blockStyleMemory, styles || {});
      try {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          view.dispatch(view.state.tr.setMeta(blockStylePluginKey, true));
        });
      } catch (error) { /* editor may still be mounting */ }
      return handle;
    },
    getCurrentBlockAnchor: () => {
      let info = null;
      try { crepe.editor.action((ctx) => { info = currentBlockInfo(ctx.get(editorViewCtx)); }); } catch (error) { /* ignore */ }
      return info?.anchor || "";
    },
    insertLink: ({ href, label, title = null } = {}) => {
      if (gone || !live) return false;
      const url = String(href || "").trim();
      const text = String(label || "").trim();
      if (!url || !text) return false;
      let changed = false;
      try {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          const state = view.state;
          const markType = linkSchema.type(ctx);
          const selection = savedSelection
            ? TextSelection.create(state.doc, savedSelection.from, savedSelection.to)
            : state.selection;
          const mark = markType.create({ href: url, title: title ? String(title) : null });
          let tr = state.tr.setSelection(selection);
          if (selection.empty) {
            tr = tr.insertText(text, selection.from, selection.to, [mark]);
          } else {
            tr = tr.addMark(selection.from, selection.to, mark);
          }
          view.dispatch(tr.scrollIntoView());
          view.focus();
          savedSelection = null;
          changed = true;
        });
      } catch (error) {
        savedSelection = null;
        return false;
      }
      return changed;
    },
    destroy: () => {
      if (gone) return;
      gone = true;
      if (pointerSelectionFrame) cancelAnimationFrame(pointerSelectionFrame);
      pointerSelectionFrame = 0;
      root.removeEventListener("pointerdown", captureEarlyPointer, true);
      root.removeEventListener("mousedown", captureEarlyPointer, true);
      root.removeEventListener("pointerdown", ensurePointerSelection, true);
      root.removeEventListener("mouseup", rememberEditorSelectionRange, true);
      root.removeEventListener("keyup", rememberEditorSelectionRange, true);
      document.removeEventListener("selectionchange", rememberEditorSelectionRange, true);
      selectionToolbarCleanup();
      root.removeEventListener("focusin", restorePointerSelection, true);
      unbindBlockMenuHover();
      savedSelection = null;
      if (linkPrepTimer) clearTimeout(linkPrepTimer);
      try { crepe.destroy(); } catch (error) { /* 已经卸载过就算了 */ }
    },
  };
  // Crepe's shared menu actions clear the current block first because they
  // are primarily designed for slash-command insertion.  The same actions
  // are also used by our block handle menu, where clearing would make a
  // heading/list conversion destructive and prevent both formats from being
  // composed on the same row.  Keep the slash-command behavior unchanged and
  // skip that preparatory delete only while the anchored block menu is open.
  const installComposableBlockMenuCommands = () => {
    try {
      crepe.editor.action((ctx) => {
        const commands = ctx.get(commandsCtx);
        if (commands.__runteamsComposableBlockMenu) return;
        const call = commands.call.bind(commands);
        commands.call = (slice, payload) => {
          const menu = root.querySelector?.(".milkdown-slash-menu");
          const blockMenuOpen = menu?.dataset?.runteamsForceOpen === "true";
          if (blockMenuOpen && slice === clearTextInCurrentBlockCommand.key) return true;
          const view = ctx.get(editorViewCtx);
          const { $from } = view.state.selection;
          const ancestorName = (names) => {
            for (let depth = $from.depth; depth > 0; depth -= 1) {
              const name = $from.node(depth).type.name;
              if (names.includes(name)) return name;
            }
            return "";
          };
          const ancestorDepth = (names) => {
            for (let depth = $from.depth; depth > 0; depth -= 1) {
              if (names.includes($from.node(depth).type.name)) return depth;
            }
            return 0;
          };
          const quoteAncestor = ancestorName(["blockquote"]);
          const listItemDepth = ancestorDepth(["list_item"]);
          const currentListItem = listItemDepth ? $from.node(listItemDepth) : null;
          const currentListIsTask = !!currentListItem && currentListItem.attrs?.checked != null;
          // Quote is an outer wrapper in ProseMirror. Reapplying it to an
          // already quoted row must lift the row out instead of nesting a
          // second blockquote.
          if (blockMenuOpen && slice === wrapInBlockTypeCommand.key
            && payload?.nodeType?.name === "blockquote" && quoteAncestor) {
            return commands.inline(lift);
          }
          // Lists are only composable with plain text and headings. Before a
          // standalone block style is applied, lift the current list item so
          // code, quote, divider, image, and table cannot remain nested in a
          // list. The selected text is preserved by normalizing code to a
          // paragraph first.
          if (blockMenuOpen && slice === wrapInBlockTypeCommand.key
            && payload?.nodeType?.name === "blockquote" && listItemDepth) {
            if (ancestorName(["code_block"])) {
              const paragraph = view.state.schema.nodes.paragraph;
              if (paragraph) call(setBlockTypeCommand.key, { nodeType: paragraph });
            }
            call(liftListItemCommand.key);
          }
          // Applying quote to a heading or code block should replace that
          // block style, not create `> ## ...` or a quoted code block from the
          // one-row format menu. Normalize the inner block to paragraph first,
          // then let the original wrap command add the quote container.
          if (blockMenuOpen && slice === wrapInBlockTypeCommand.key
            && payload?.nodeType?.name === "blockquote"
            && ancestorName(["heading", "code_block"])) {
            const paragraph = view.state.schema.nodes.paragraph;
            if (paragraph) call(setBlockTypeCommand.key, { nodeType: paragraph });
          }
          // Heading/text/code are mutually exclusive with quote in this
          // single-row menu. Before changing the inner textblock, unwrap an
          // existing quote so the new style replaces it at the same level.
          if (blockMenuOpen && slice === setBlockTypeCommand.key
            && ["paragraph", "heading", "code_block"].includes(payload?.nodeType?.name)
            && quoteAncestor) {
            commands.inline(lift);
          }
          // A code block is a standalone style. Converting a checklist/list
          // item to code first removes the list wrapper, while converting code
          // to a list first restores a paragraph so only text/headings remain
          // inside the list container.
          if (blockMenuOpen && slice === setBlockTypeCommand.key
            && payload?.nodeType?.name === "code_block" && listItemDepth) {
            const paragraph = view.state.schema.nodes.paragraph;
            if (paragraph) call(setBlockTypeCommand.key, { nodeType: paragraph });
            call(liftListItemCommand.key);
          }
          if (blockMenuOpen && slice === wrapInBlockTypeCommand.key
            && ["bullet_list", "ordered_list", "list_item"].includes(payload?.nodeType?.name)
            && ancestorName(["code_block"])) {
            const paragraph = view.state.schema.nodes.paragraph;
            if (paragraph) call(setBlockTypeCommand.key, { nodeType: paragraph });
          }
          // A list cannot be nested in a quote under the simplified block
          // model. Lift the quote first, then let the list conversion below
          // operate on the standalone list/text block.
          if (blockMenuOpen && slice === wrapInBlockTypeCommand.key
            && ["bullet_list", "ordered_list", "list_item"].includes(payload?.nodeType?.name)
            && quoteAncestor) {
            commands.inline(lift);
          }
          // Task list is represented by a list_item with a checked attribute,
          // so it needs the same explicit toggle guard as bullet/ordered
          // lists. Otherwise the stock wrapper nests another list item.
          if (blockMenuOpen && slice === wrapInBlockTypeCommand.key
            && payload?.nodeType?.name === "list_item" && currentListIsTask) {
            return call(liftListItemCommand.key);
          }
          // Image/table/divider (and the optional math-code insertion) are
          // standalone blocks. The stock AddBlockType command replaces only
          // the current selection, which can leave an atom inside a paragraph
          // or heading when the caret is collapsed. Replace the whole visual
          // block instead, after removing any list/quote container above it.
          if (blockMenuOpen && slice === addBlockTypeCommand.key) {
            const nodeTypeName = payload?.nodeType?.type?.name || payload?.nodeType?.name || "";
            const standaloneNames = new Set(["image-block", "table", "horizontal_rule", "code_block"]);
            if (standaloneNames.has(nodeTypeName)) {
              if (quoteAncestor) commands.inline(lift);
              if (listItemDepth) call(liftListItemCommand.key);
              try {
                const currentView = ctx.get(editorViewCtx);
                const { $from } = currentView.state.selection;
                let blockDepth = $from.depth;
                while (blockDepth > 0 && !$from.node(blockDepth).isBlock) blockDepth -= 1;
                if (blockDepth <= 0) return false;
                const node = payload?.nodeType?.type
                  ? payload.nodeType
                  : payload?.nodeType?.createAndFill?.(payload.attrs || null);
                if (!node) return false;
                const from = $from.before(blockDepth);
                const to = $from.after(blockDepth);
                currentView.dispatch(currentView.state.tr.replaceWith(from, to, node).scrollIntoView());
                currentView.focus();
                return true;
              } catch (error) {
                // Let Milkdown's insertion command handle an unsupported
                // custom node rather than breaking the format menu.
              }
            }
          }
          // The stock block menu always calls wrapInBlockTypeCommand for a
          // list action. Never let that command create a second list: convert
          // the existing list in place, or lift the current item to toggle
          // the active list off. Task lists are represented by checked attrs
          // on list items, so they are normalized together with the parent
          // list instead of being nested as a second list_item node.
          if (blockMenuOpen && slice === wrapInBlockTypeCommand.key) {
            const targetListName = payload?.nodeType?.name;
            if (["bullet_list", "ordered_list", "list_item"].includes(targetListName)) {
              const currentDepth = ancestorDepth(["bullet_list", "ordered_list"]);
              if (currentDepth) {
                const currentList = $from.node(currentDepth);
                const currentItemDepth = ancestorDepth(["list_item"]);
                const currentItem = currentItemDepth ? $from.node(currentItemDepth) : null;
                const currentTask = !!currentItem && currentItem.attrs?.checked != null;
                const targetTask = targetListName === "list_item";
                // Reapplying the active list type toggles only the current
                // item out, while a task-list click on an already-task item
                // follows the same cancel behavior.
                if ((targetTask && currentTask)
                  || (!targetTask && !currentTask && currentList.type.name === targetListName)) {
                  return call(liftListItemCommand.key);
                }
                const listPos = $from.before(currentDepth);
                const targetListTypeName = targetTask ? "bullet_list" : targetListName;
                const targetListType = view.state.schema.nodes[targetListTypeName];
                if (!targetListType) return false;
                const tr = view.state.tr;
                // Remove task metadata when converting to a regular list, or
                // add it to every item when converting the list to Checklist.
                currentList.descendants((node, pos) => {
                  if (node.type.name !== "list_item") return;
                  const hasChecked = node.attrs?.checked != null;
                  if (targetTask && !hasChecked) {
                    tr.setNodeMarkup(listPos + 1 + pos, null, { ...node.attrs, checked: false });
                  } else if (!targetTask && hasChecked) {
                    const attrs = { ...node.attrs };
                    delete attrs.checked;
                    tr.setNodeMarkup(listPos + 1 + pos, null, attrs);
                  }
                });
                if (currentList.type !== targetListType) {
                  tr.setNodeMarkup(listPos, targetListType, currentList.attrs);
                }
                view.dispatch(tr.scrollIntoView());
                return true;
              }
            }
          }
          return call(slice, payload);
        };
        commands.__runteamsComposableBlockMenu = true;
      });
    } catch (error) {
      // The command manager is available after create(); leave the stock
      // behavior in place if an editor is destroyed during initialization.
    }
  };
  handle.ready = crepe.create().then(() => {
    installComposableBlockMenuCommands();
    live = true;
    if (earlyPointerPosition && !gone) {
      const pointer = earlyPointerPosition;
      earlyPointerPosition = null;
      try {
        crepe.editor.action((ctx) => {
          const view = ctx.get(editorViewCtx);
          const hit = view.posAtCoords(pointer);
          if (!hit || typeof hit.pos !== "number") return;
          view.dispatch(view.state.tr.setSelection(TextSelection.near(view.state.doc.resolve(hit.pos))));
          view.focus();
        });
      } catch (error) { /* 编辑器已完成初始化但坐标失效时沿用默认选区 */ }
    }
    prepareEditorLinksUntilSettled();
    if (gone) handle.destroy();
    if (options.readonly) handle.setReadonly(true);
    return handle;
  });
  return handle;
}
