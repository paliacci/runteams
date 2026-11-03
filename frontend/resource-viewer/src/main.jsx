import React, { useEffect, useMemo, useRef, useState, useId } from "react";
import { createRoot } from "react-dom/client";
import {
  SandpackCodeEditor,
  SandpackFileExplorer,
  SandpackLayout,
  SandpackProvider,
  useSandpack,
} from "@codesandbox/sandpack-react";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { yaml } from "@codemirror/legacy-modes/mode/yaml";
import { tags } from "@lezer/highlight";
import { EditorState } from "@codemirror/state";
import { EditorView, lineNumbers } from "@codemirror/view";
import "./resource-viewer.css";
import { formatJsonForDisplay, isJsonPath } from "./json-display.mjs";

const roots = new WeakMap();

const additionalLanguages = [
  { name: "python", extensions: ["py", "pyw"], language: python() },
  { name: "markdown", extensions: ["md", "markdown"], language: markdown() },
  { name: "shell", extensions: ["sh", "bash", "zsh"], language: StreamLanguage.define(shell) },
  { name: "yaml", extensions: ["yaml", "yml"], language: StreamLanguage.define(yaml) },
  { name: "toml", extensions: ["toml"], language: StreamLanguage.define(toml) },
];

const readOnlyExtensions = [
  EditorState.readOnly.of(true),
  EditorView.editable.of(false),
];

function cssValue(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback || "";
}

function semanticColor(name) { return `var(${name})`; }

function runTeamsTheme() {
  return {
    colors: {
      surface1: semanticColor("--panel"),
      surface2: semanticColor("--rail"),
      surface3: semanticColor("--rail-active"),
      clickable: semanticColor("--sub"),
      base: semanticColor("--ink2"),
      disabled: semanticColor("--muted"),
      hover: semanticColor("--ink"),
      accent: semanticColor("--accent-ink"),
      error: semanticColor("--block"),
      errorSurface: semanticColor("--block-weak"),
    },
    syntax: {
      plain: semanticColor("--ink2"),
      comment: semanticColor("--text-muted"),
      keyword: semanticColor("--status-attention"),
      tag: semanticColor("--status-danger"),
      punctuation: semanticColor("--text-secondary"),
      definition: semanticColor("--action-primary"),
      property: semanticColor("--text-primary"),
      static: semanticColor("--status-attention"),
      string: semanticColor("--status-success"),
    },
    font: {
      body: cssValue("--sans", "-apple-system, BlinkMacSystemFont, sans-serif"),
      mono: cssValue("--mono", "SFMono-Regular, Consolas, monospace"),
      size: "var(--code-font-size,13px)",
      lineHeight: "1.6",
    },
  };
}

function cleanPath(value) {
  return String(value || "").replace(/^\/+/, "");
}

function isMarkdown(path) {
  return /\.(md|markdown)$/i.test(path);
}

function isRasterImage(path) {
  return /\.(png|jpe?g|webp|gif)$/i.test(path);
}

function folderPaths(paths) {
  const folders = new Set();
  paths.forEach((path) => {
    const parts = cleanPath(path).split("/").filter(Boolean);
    for (let depth = 1; depth < parts.length; depth += 1) {
      folders.add(`/${parts.slice(0, depth).join("/")}/`);
    }
  });
  return [...folders];
}

function markdownBody(source) {
  return String(source || "").replace(
    /^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/,
    ""
  );
}

function MarkdownPreview({ source, onOpenFile }) {
  const html = useMemo(() => {
    if (!window.marked || !window.DOMPurify) return "";
    return window.DOMPurify.sanitize(window.marked.parse(markdownBody(source)));
  }, [source]);
  if (!html) return <div className="rt-resource-empty">这个文档没有可预览的内容。</div>;
  return <article className="rt-resource-markdown" onClick={event=>{const link=event.target.closest("a[href]");if(link&&onOpenFile?.(link.getAttribute("href")))event.preventDefault();}} dangerouslySetInnerHTML={{ __html: html }} />;
}

// Uses the same themed artwork, disclosure and controls as the host pages.
function ReadFailure({ title, error, busy = false, onRetry }) {
  const readId = useId();
  const host = useRef(null);
  useEffect(() => {
    const button = host.current?.querySelector('[data-read-retry]');
    if (button) button.onclick = event => window.RunTeamsLoadFailure.retry(button, event, onRetry);
  }, [title, error, busy, onRetry]);
  return <div ref={host} className="rt-resource-read-failure" dangerouslySetInnerHTML={{ __html: window.RunTeamsLoadFailure.markup({ variant: 'modal', title, error, busy, retry: 'void 0', key: 'resource:' + readId }) }} />;
}

function ImagePreview({ source, path, scale, onRetry }) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => setFailed(false), [source]);
  if (failed) return <ReadFailure title="图片暂时无法加载" onRetry={() => { if (onRetry) return onRetry(); setAttempt(value => value + 1); setFailed(false); }} />;
  return (
    <div className={`rt-resource-image-stage ${scale}`}>
      <img key={attempt} src={source} alt={`${path} 预览`} onError={() => setFailed(true)} />
    </div>
  );
}

function ResourcePane({ loadFile, initialLoaded }) {
  const errorFile = useRef(null);
  const retryCompletion = useRef(null);
  const { sandpack } = useSandpack();
  const [mode, setMode] = useState("source");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [retry, setRetry] = useState(0);
  const [imageScale, setImageScale] = useState("fit");
  const [images, setImages] = useState({});
  const loaded = useRef(new Set(initialLoaded));
  const activeFile = sandpack.activeFile;
  const path = cleanPath(activeFile);
  const file = sandpack.files[activeFile];
  const markdownFile = isMarkdown(path);
  const imageFile = isRasterImage(path);
  const image = images[activeFile];

  useEffect(() => {
    setMode(markdownFile ? "preview" : "source");
    setImageScale("fit");
  }, [activeFile, markdownFile]);

  function retryFile() {
    if (loading) return;
    loaded.current.delete(activeFile);
    setLoading(true);
    return new Promise(resolve => {
      retryCompletion.current = resolve;
      setRetry(value => value + 1);
    });
  }

  useEffect(() => {
    let current = true;
    const completeRetry = retryCompletion.current;
    retryCompletion.current = null;
    if (!loadFile || loaded.current.has(activeFile)) {
      setLoading(false);
      setLoadError("");
      completeRetry?.();
      return () => { current = false; };
    }
    setLoading(true);
    if (errorFile.current !== activeFile) setLoadError("");
    Promise.resolve().then(() => loadFile(cleanPath(activeFile))).then((result) => {
      if (!current) return;
      if (result?.imageUrl) {
        setImages((value) => ({ ...value, [activeFile]: result.imageUrl }));
        sandpack.updateFile(activeFile, "", false);
      } else {
        sandpack.updateFile(activeFile, String(result?.code ?? result ?? ""), false);
      }
      setLoadError("");
      loaded.current.add(activeFile);
      setLoading(false);
    }).catch((error) => {
      if (!current) return;
      setLoading(false);
      errorFile.current = activeFile;
      setLoadError(error?.message || "文件没有加载成功");
    }).finally(() => completeRetry?.());
    return () => { current = false; completeRetry?.(); };
  }, [activeFile, loadFile, retry]);

  return (
    <section className="rt-resource-pane">
      <header className="rt-resource-pane-header">
        <div className="rt-resource-path" title={path}>
          {path.split("/").map((part, index) => (
            <React.Fragment key={`${part}-${index}`}>
              {index > 0 && <i>/</i>}
              <span>{part}</span>
            </React.Fragment>
          ))}
        </div>
        {markdownFile && (
          <nav className="rt-resource-modes" aria-label="文档显示方式">
            <button type="button" className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>预览</button>
            <button type="button" className={mode === "source" ? "active" : ""} onClick={() => setMode("source")}>源码</button>
          </nav>
        )}
        {imageFile && image && (
          <nav className="rt-resource-modes" aria-label="图片显示方式">
            <button type="button" className={imageScale === "fit" ? "active" : ""} onClick={() => setImageScale("fit")}>适应</button>
            <button type="button" className={imageScale === "actual" ? "active" : ""} onClick={() => setImageScale("actual")}>原始</button>
          </nav>
        )}
      </header>
      <div className="rt-resource-pane-body" tabIndex={0} aria-label="文件预览内容">
        {loadError && errorFile.current === activeFile ? (
          <ReadFailure title="文件暂时无法加载" error={loadError} busy={loading} onRetry={retryFile} />
        ) : loading ? (
          <div className="rt-resource-loading"><span></span><b>正在读取文件…</b></div>
        ) : imageFile && image ? (
          <ImagePreview source={image} path={path} scale={imageScale} onRetry={loadFile ? retryFile : undefined} />
        ) : mode === "preview" && markdownFile ? (
          <MarkdownPreview source={file?.code || ""} onOpenFile={href=>{
            if(/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href||""))return false;
            let relative;try{relative=decodeURIComponent(String(href||"").split(/[?#]/)[0]);}catch{return false;}
            if(!relative)return false;
            const parts=relative.startsWith("/")?[]:path.split("/").slice(0,-1);
            for(const part of relative.split("/")){if(!part||part===".")continue;if(part===".."){if(!parts.length)return false;parts.pop();}else parts.push(part);}
            const target="/"+parts.join("/");if(!sandpack.files[target])return false;sandpack.openFile(target);return true;
          }} />
        ) : isJsonPath(path) ? (
          <CodePreview path={path} code={file?.code || ""} />
        ) : (
          <SandpackCodeEditor
            additionalLanguages={additionalLanguages}
            extensions={readOnlyExtensions}
            readOnly={false}
            showLineNumbers
            showReadOnly={false}
            showRunButton={false}
            showTabs={false}
            wrapContent={false}
          />
        )}
      </div>
    </section>
  );
}

function ResourceViewer({ files, activeFile, loadFile }) {
  const paths = Object.keys(files);
  const firstFile = activeFile && files[activeFile] ? activeFile : paths[0];
  const initialLoaded = useMemo(() => paths.filter((path) => files[path]?.loaded !== false), [files]);
  const sandpackFiles = useMemo(() => Object.fromEntries(paths.map((path) => [path, {
    code: String(files[path]?.code || ""),
  }])), [files]);
  if (!firstFile) return <div className="rt-resource-empty">这个扩展没有可浏览的文件。</div>;
  return (
    <SandpackProvider
      customSetup={{ entry: firstFile }}
      files={sandpackFiles}
      options={{ activeFile: firstFile, autorun: false, visibleFiles: paths }}
      template="vanilla"
      theme={runTeamsTheme()}
    >
      <div className="rt-resource-viewer">
        <SandpackLayout className="rt-resource-layout">
          <aside className="rt-resource-explorer">
            <div className="rt-resource-explorer-title">资源</div>
            <SandpackFileExplorer
              autoHiddenFiles
              initialCollapsedFolder={folderPaths(paths)}
            />
          </aside>
          <ResourcePane loadFile={loadFile} initialLoaded={initialLoaded} />
        </SandpackLayout>
      </div>
    </SandpackProvider>
  );
}

function CodePreview({ path, code }) {
  const host = useRef(null);
  useEffect(() => {
    if (!host.current) return undefined;
    const extension = String(path || "").split(".").pop().toLowerCase();
    const language = ({
      js: () => javascript(), jsx: () => javascript({ jsx: true }),
      ts: () => javascript({ typescript: true }), tsx: () => javascript({ typescript: true, jsx: true }),
      json: () => javascript({ json: true }), css: () => css(),
      html: () => html(), htm: () => html(), xml: () => html(),
      py: () => python(), pyw: () => python(),
      sh: () => StreamLanguage.define(shell), bash: () => StreamLanguage.define(shell), zsh: () => StreamLanguage.define(shell),
      yaml: () => StreamLanguage.define(yaml), yml: () => StreamLanguage.define(yaml),
      toml: () => StreamLanguage.define(toml),
    })[extension]?.();
    const colors = runTeamsTheme().syntax;
    const style = HighlightStyle.define([
      { tag: tags.comment, color: colors.comment },
      { tag: tags.keyword, color: colors.keyword },
      { tag: [tags.tagName, tags.angleBracket], color: colors.tag },
      { tag: tags.punctuation, color: colors.punctuation },
      { tag: [tags.function(tags.variableName), tags.definition(tags.variableName)], color: colors.definition },
      { tag: tags.propertyName, color: colors.property },
      { tag: [tags.number, tags.bool, tags.null], color: colors.static },
      { tag: [tags.string, tags.special(tags.string)], color: colors.string },
    ]);
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: formatJsonForDisplay(path, code),
        extensions: [lineNumbers(), EditorState.readOnly.of(true), EditorView.editable.of(false), syntaxHighlighting(style), ...(language ? [language] : [])],
      }),
    });
    return () => view.destroy();
  }, [path, code]);
  return <div ref={host} className="rt-code-preview" aria-label={`${cleanPath(path)} 代码预览`} />;
}

export function mount(element, props) {
  if (!element) throw new Error("Resource viewer mount element is required");
  const existing = roots.get(element);
  if (existing) existing.unmount();
  const root = createRoot(element);
  roots.set(element, root);
  root.render(<ResourceViewer {...props} />);
}

export function mountCode(element, props) {
  if (!element) throw new Error("Code preview mount element is required");
  const existing = roots.get(element);
  if (existing) existing.unmount();
  const root = createRoot(element);
  roots.set(element, root);
  root.render(<CodePreview {...props} />);
}

export function unmount(element) {
  const root = element && roots.get(element);
  if (!root) return;
  root.unmount();
  roots.delete(element);
}

// Single-file surface: the caller owns the tree and active-file label.
function FileViewer({path, file, initialState={}, compact=false}) {
  const [mode,setMode] = useState(initialState.mode || "preview");
  const [scale,setScale] = useState(initialState.scale || "fit");
  const host=useRef(null);
  useEffect(()=>{
    const body=host.current?.querySelector(".cm-scroller") || host.current?.querySelector(".rt-file-body");
    if(body){body.scrollTop=initialState.scrollTop||0;body.scrollLeft=initialState.scrollLeft||0;}
  },[path,mode,scale]);
  const md=isMarkdown(path) && file?.kind==="text",image=file?.kind==="image";
  return <section ref={host} className={`rt-file-viewer${compact?" compact":""}`} data-mode={mode} data-scale={scale}>
    {(md||image)&&<nav className="rt-resource-modes" aria-label={md?"文档显示方式":"图片显示方式"}>
      {(md?["preview","source"]:["fit","actual"]).map(value=><button type="button" key={value} className={(md?mode:scale)===value?"active":""} onClick={()=>md?setMode(value):setScale(value)}>{({preview:"预览",source:"源码",fit:"适应",actual:"原始"})[value]}</button>)}
    </nav>}
    <div className="rt-file-body" tabIndex={0} aria-label="文件预览内容">{image?<ImagePreview source={file.data_url} path={path} scale={scale}/>:file?.kind!=="text"?<div className="rt-resource-empty">此文件暂不支持预览。</div>:md&&mode==="preview"?<MarkdownPreview source={file.content}/>:<CodePreview path={path} code={file.content}/>}</div>
  </section>;
}
export function mountFile(element,props){
  unmount(element);
  const root=createRoot(element);roots.set(element,root);root.render(<FileViewer {...props}/>);
}
export function captureFileState(element){
  const host=element?.querySelector('.rt-file-viewer');
  const body=host?.querySelector('.cm-scroller')||host?.querySelector('.rt-file-body');
  return {mode:host?.dataset.mode||'preview',scale:host?.dataset.scale||'fit',scrollTop:body?.scrollTop||0,scrollLeft:body?.scrollLeft||0};
}
