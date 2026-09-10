import React, { useEffect, useMemo, useRef, useState } from "react";
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
import { StreamLanguage } from "@codemirror/language";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { yaml } from "@codemirror/legacy-modes/mode/yaml";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import "./resource-viewer.css";

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
  return value || fallback;
}

function runTeamsTheme() {
  return {
    colors: {
      surface1: cssValue("--panel", "#ffffff"),
      surface2: cssValue("--rail", "#f7f7f6"),
      surface3: cssValue("--rail-active", "#efefed"),
      clickable: cssValue("--sub", "#66645f"),
      base: cssValue("--ink2", "#35332f"),
      disabled: cssValue("--muted", "#aaa7a0"),
      hover: cssValue("--ink", "#24231f"),
      accent: cssValue("--accent-ink", "#735d36"),
      error: cssValue("--block", "#b34b42"),
      errorSurface: cssValue("--block-weak", "#fff0ee"),
    },
    syntax: {
      plain: cssValue("--ink2", "#35332f"),
      comment: "#8b918a",
      keyword: "#8b4f9e",
      tag: "#b4514d",
      punctuation: "#77746d",
      definition: "#315f9c",
      property: "#86611d",
      static: "#9a4d20",
      string: "#3d7953",
    },
    font: {
      body: cssValue("--sans", "-apple-system, BlinkMacSystemFont, sans-serif"),
      mono: cssValue("--mono", "SFMono-Regular, Consolas, monospace"),
      size: "13px",
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

function MarkdownPreview({ source }) {
  const html = useMemo(() => {
    if (!window.marked || !window.DOMPurify) return "";
    return window.DOMPurify.sanitize(window.marked.parse(markdownBody(source)));
  }, [source]);
  if (!html) return <div className="rt-resource-empty">这个文档没有可预览的内容。</div>;
  return <article className="rt-resource-markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}

function ImagePreview({ source, path, scale }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [source]);
  if (failed) return <div className="rt-resource-empty">这张图片无法预览。</div>;
  return (
    <div className={`rt-resource-image-stage ${scale}`}>
      <img src={source} alt={`${path} 预览`} onError={() => setFailed(true)} />
    </div>
  );
}

function ResourcePane({ loadFile, initialLoaded }) {
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

  useEffect(() => {
    let current = true;
    if (!loadFile || loaded.current.has(activeFile)) {
      setLoading(false);
      setLoadError("");
      return () => { current = false; };
    }
    setLoading(true);
    setLoadError("");
    Promise.resolve(loadFile(cleanPath(activeFile))).then((result) => {
      if (!current) return;
      if (result?.imageUrl) {
        setImages((value) => ({ ...value, [activeFile]: result.imageUrl }));
        sandpack.updateFile(activeFile, "", false);
      } else {
        sandpack.updateFile(activeFile, String(result?.code ?? result ?? ""), false);
      }
      loaded.current.add(activeFile);
      setLoading(false);
    }).catch((error) => {
      if (!current) return;
      setLoading(false);
      setLoadError(error?.message || "文件没有加载成功");
    });
    return () => { current = false; };
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
      <div className="rt-resource-pane-body">
        {loading ? (
          <div className="rt-resource-loading"><span></span><b>正在读取文件…</b></div>
        ) : loadError ? (
          <div className="rt-resource-load-error"><b>文件没有加载成功</b><span>{loadError}</span><button type="button" onClick={() => setRetry((value) => value + 1)}>重试</button></div>
        ) : imageFile && image ? (
          <ImagePreview source={image} path={path} scale={imageScale} />
        ) : mode === "preview" && markdownFile ? (
          <MarkdownPreview source={file?.code || ""} />
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

export function mount(element, props) {
  if (!element) throw new Error("Resource viewer mount element is required");
  const existing = roots.get(element);
  if (existing) existing.unmount();
  const root = createRoot(element);
  roots.set(element, root);
  root.render(<ResourceViewer {...props} />);
}

export function unmount(element) {
  const root = element && roots.get(element);
  if (!root) return;
  root.unmount();
  roots.delete(element);
}
