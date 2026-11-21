/* Runtime theme selection for the active product window. */
(function (global) {
  'use strict';

  const preview = ['127.0.0.1', 'localhost', '[::1]'].includes(global.location.hostname)
    && new URLSearchParams(global.location.search).get('workspace-theme') === 'mist-lake';
  let previewWindow = null;
  let activeShell, activeWindow, activeEligible, activeBackground, activeColor;
  let photoUrl = '';
  let contrastPhoto;
  let contrastObserver;
  let contrastRegions = [];
  let contrastLayout = '';
  let preparedPhoto;
  let previewReady = false;
  const imageSource = /^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/;
  const maxImageSourceLength = Math.ceil(5 * 1024 * 1024 / 3) * 4 + 'data:image/jpeg;base64,'.length;
  const paletteTint = 0.42;
  const paletteProperties = ['--workspace-palette-tint', '--workspace-palette-seed', '--workspace-palette-ink',
    '--workspace-palette-paper', '--workspace-palette-scrim'];
  const contrastSelectors = [
    ':is(#rgPipelineHead, .conversation-main) .conversation-panel-header',
    '#rgDrawer > .right-detail-drawer',
    '.conversation-main .conversation-scroll-shell:has(#conversation_scroll)',
  ];
  const regionalProperties = ['--workspace-local-ink', '--workspace-local-base', '--workspace-local-wash'];
  const readingProperties = ['--workspace-reading-wash', '--workspace-reading-start', '--workspace-reading-end', '--workspace-reading-top'];
  const black = [0, 0, 0];
  const white = [255, 255, 255];
  const rgb = (channels, alpha = 1) => `rgb(${channels.map(Math.round).join(' ')} / ${alpha})`;

  function mix(first, second, amount) {
    return first.map((channel, index) => channel + (second[index] - channel) * amount);
  }

  function luminance(color) {
    const channels = color.map(channel => {
      const value = channel / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  }

  function paletteForWorkspace(color) {
    if (typeof color !== 'string' || !/^\d{1,3},\d{1,3},\d{1,3}$/.test(color)) return null;
    const seed = color.split(',').map(Number);
    if (seed.some(channel => channel > 255)) return null;
    const tone = (ink, background) => {
      const paper = mix(background, seed, 0.12);
      // Bound contrast even over pure black or white under the translucent surfaces.
      const weakestBackdrop = mix(ink, seed, paletteTint);
      const muted = luminance(mix(ink, seed, 0.36));
      let low = 0;
      let high = 1;
      for (let step = 0; step < 10; step++) {
        const opacity = (low + high) / 2;
        const surface = luminance(mix(weakestBackdrop, paper, opacity));
        const contrast = (Math.max(muted, surface) + 0.05) / (Math.min(muted, surface) + 0.05);
        if (contrast >= 4.6) high = opacity;
        else low = opacity;
      }
      return {ink, paper, opacity: Math.ceil(high * 100) / 100};
    };
    const darkInk = tone(black, white);
    const lightInk = tone(white, black);
    const {ink, paper, opacity} = darkInk.opacity <= lightInk.opacity ? darkInk : lightInk;
    return [rgb(seed, paletteTint), rgb(seed), rgb(ink), rgb(paper), rgb(paper, opacity)];
  }

  function regionTone(pixels, seed) {
    const assess = (ink, base) => {
      const text = luminance(mix(ink, seed, 0.14));
      const wash = mix(base, seed, 0.06);
      const contrast = (pixel, opacity) => {
        const back = luminance(mix(pixel, wash, opacity));
        return ink === black ? (back + 0.05) / (text + 0.05) : (text + 0.05) / (back + 0.05);
      };
      // Include thin highlights and shadows. The canvas already averages nearby pixels.
      const readable = opacity => pixels.every(pixel => contrast(pixel, opacity) >= 4.6);
      let low = 0, high = 1;
      if (readable(0)) high = 0;
      else for (let step = 0; step < 8; step++) {
        const opacity = (low + high) / 2;
        if (readable(opacity)) high = opacity;
        else low = opacity;
      }
      return {ink, base, wash, opacity: Math.ceil(high * 100) / 100};
    };
    const darkInk = assess(black, white);
    const lightInk = assess(white, black);
    return darkInk.opacity <= lightInk.opacity ? darkInk : lightInk;
  }

  async function loadContrastPhoto(url) {
    const image = new Image();
    image.src = url;
    await image.decode();
    const scaled = Math.min(1, 512 / Math.max(image.naturalWidth, image.naturalHeight));
    const photo = global.document.createElement('canvas');
    photo.width = Math.max(1, Math.round(image.naturalWidth * scaled));
    photo.height = Math.max(1, Math.round(image.naturalHeight * scaled));
    const context = photo.getContext('2d');
    if (!context) return null;
    context.drawImage(image, 0, 0, photo.width, photo.height);
    return photo;
  }

  function contrastPixels(context, photo, shell, box, dark) {
    const scale = Math.max(shell.width / photo.width, shell.height / photo.height);
    const x = (box.left - shell.left + (photo.width * scale - shell.width) / 2) / scale;
    const y = (box.top - shell.top + (photo.height * scale - shell.height) / 2) / scale;
    const {width, height} = context.canvas;
    context.drawImage(photo, x, y, box.width / scale, box.height / scale, 0, 0, width, height);
    const {data} = context.getImageData(0, 0, width, height);
    const paper = dark ? [12, 17, 20] : white;
    const pixels = [];
    for (let i = 0; i < data.length; i += 4) {
      const photoOpacity = data[i + 3] / 255 * (dark ? 0.23 : 1);
      pixels.push(mix(paper, [data[i], data[i + 1], data[i + 2]], photoOpacity));
    }
    return pixels;
  }

  function readingSurface(region) {
    if (!region.matches('.conversation-scroll-shell')) return null;
    return region.closest('.source-pipeline-conversation-layer') || region.closest('.conversation-workspace-main');
  }

  function clearRegion(region) {
    delete region.dataset.workspaceContrast;
    for (const name of regionalProperties) region.style.removeProperty(name);
    const surface = readingSurface(region);
    if (surface) for (const name of readingProperties) surface.style.removeProperty(name);
  }

  function paintRegionalContrast() {
    if (!contrastPhoto || !contrastRegions.length) return;
    const shell = activeShell.getBoundingClientRect();
    if (!shell.width || !shell.height) return;
    const dark = getComputedStyle(activeShell).colorScheme === 'dark';
    const readingSurfaces = contrastRegions.map(readingSurface);
    const boxes = contrastRegions.map((region, index) => {
      const bounds = region.getBoundingClientRect();
      const surface = readingSurfaces[index]?.getBoundingClientRect() || bounds;
      const messages = region.querySelector('.conversation-messages')?.getBoundingClientRect();
      const left = Math.max(shell.left, bounds.left, messages?.width ? messages.left - 4 : bounds.left);
      const right = Math.min(shell.right, bounds.right, messages?.width ? messages.right + 4 : bounds.right);
      const top = Math.max(shell.top, bounds.top);
      const bottom = Math.min(shell.bottom, bounds.bottom);
      return {left, top, width: right - left, height: bottom - top, start: left - surface.left,
        end: right - surface.left, inset: Math.max(0, top - surface.top)};
    });
    const layout = JSON.stringify([shell.width, shell.height, shell.left, shell.top, dark, activeColor, boxes]);
    if (layout === contrastLayout) return;
    contrastLayout = layout;
    const sample = global.document.createElement('canvas');
    sample.width = 88;
    sample.height = 64;
    const context = sample.getContext('2d', {willReadFrequently: true});
    if (!context) return;
    const seed = activeColor.split(',').map(Number);
    contrastRegions.forEach((region, index) => {
      const box = boxes[index];
      if (box.width <= 0 || box.height <= 0) { clearRegion(region); return; }
      context.clearRect(0, 0, sample.width, sample.height);
      const pixels = contrastPixels(context, contrastPhoto, shell, box, dark);
      const {ink, base, wash, opacity} = regionTone(pixels, seed);
      const washColor = rgb(wash, opacity);
      region.style.setProperty('--workspace-local-ink', rgb(ink));
      region.style.setProperty('--workspace-local-base', rgb(base));
      region.style.setProperty('--workspace-local-wash', washColor);
      const surface = readingSurfaces[index];
      if (surface) {
        surface.style.setProperty('--workspace-reading-wash', washColor);
        surface.style.setProperty('--workspace-reading-start', `${box.start}px`);
        surface.style.setProperty('--workspace-reading-end', `${box.end}px`);
        surface.style.setProperty('--workspace-reading-top', `${box.inset}px`);
      }
      region.dataset.workspaceContrast = ink === white ? 'light-text' : 'dark-text';
    });
  }

  function syncContrastRegions(shell) {
    const next = shell && contrastPhoto ? Array.from(shell.querySelectorAll(contrastSelectors.join(','))) : [];
    if (next.length !== contrastRegions.length || next.some((region, i) => region !== contrastRegions[i])) {
      contrastObserver?.disconnect();
      contrastRegions.filter(region => !next.includes(region)).forEach(clearRegion);
      contrastRegions = next;
      contrastLayout = '';
      if (next.length) {
        contrastObserver ||= new ResizeObserver(paintRegionalContrast);
        contrastObserver.observe(shell);
        for (const region of next) {
          contrastObserver.observe(region);
          const messages = region.querySelector('.conversation-messages');
          if (messages) contrastObserver.observe(messages);
        }
      }
    }
    paintRegionalContrast();
  }

  global.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paintRegionalContrast);

  function paintPalette(shell, palette) {
    shell.toggleAttribute('data-workspace-palette', !!palette);
    paletteProperties.forEach((property, index) => {
      if (palette) shell.style.setProperty(property, palette[index]);
      else shell.style.removeProperty(property);
    });
  }

  function themeOverlay(overlay, anchor = activeShell) {
    // A detached overlay keeps its originating window's palette.
    const owner = anchor?.closest?.('[data-workspace-overlay-palette], #rgBody[data-workspace-palette]');
    const seed = owner?.style.getPropertyValue('--workspace-palette-seed');
    if (!seed) return;
    overlay.style.setProperty('--workspace-palette-seed', seed);
    overlay.setAttribute('data-workspace-overlay-palette', '');
  }

  function imageUrl(source) {
    if (typeof source !== 'string' || source.length > maxImageSourceLength || !imageSource.test(source)) return '';
    const separator = source.indexOf(',');
    try {
      const text = atob(source.slice(separator + 1));
      const bytes = new Uint8Array(text.length);
      for (let index = 0; index < text.length; index++) bytes[index] = text.charCodeAt(index);
      const type = source.slice(5, source.indexOf(';'));
      return URL.createObjectURL(new Blob([bytes], {type}));
    } catch (error) {
      if (!(error instanceof DOMException)) throw error;
      return '';
    }
  }

  function preparePhoto(source, ready) {
    if (!source || (activeEligible && source === activeBackground)) return true;
    if (preparedPhoto?.source === source) return preparedPhoto.ready;
    if (preparedPhoto?.url) URL.revokeObjectURL(preparedPhoto.url);
    const photo = {source, url: imageUrl(source), ready: false};
    preparedPhoto = photo;
    if (!photo.url) {
      photo.ready = true;
      return true;
    }
    loadContrastPhoto(photo.url).then(contrast => { photo.contrast = contrast; }).catch(() => {
      URL.revokeObjectURL(photo.url);
      photo.url = '';
    }).then(() => {
      photo.ready = true;
      if (preparedPhoto === photo) ready();
    });
    return false;
  }

  if (preview) {
    const stylesheet = global.document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = '/ui/workspace-theme-preview.css?v=1';
    stylesheet.onload = () => {
      previewReady = true;
      sync(activeShell, activeWindow, activeEligible, activeBackground, activeColor);
    };
    global.document.head.appendChild(stylesheet);
  }

  function sync(shell, windowKey, eligible, background, color) {
    const samePhoto = activeEligible === eligible && activeBackground === background;
    const sameColor = activeColor === color;
    const alreadyApplied = activeShell === shell && samePhoto && shell?.dataset.workspaceTheme === 'asset';
    activeShell = shell;
    activeWindow = windowKey;
    activeEligible = eligible;
    activeBackground = background;
    activeColor = color;
    if (!shell) return;
    // The local preview is bound to the first eligible window for this page load.
    if (preview && eligible && windowKey && previewWindow === null) previewWindow = windowKey;
    if (!samePhoto) {
      contrastLayout = '';
      if (photoUrl) URL.revokeObjectURL(photoUrl);
      const photo = eligible && preparedPhoto?.ready && preparedPhoto.source === background ? preparedPhoto : null;
      photoUrl = photo?.url || '';
      contrastPhoto = photo?.contrast;
      if (photo) preparedPhoto = null;
    }
    if (photoUrl) {
      if (!alreadyApplied) shell.style.setProperty('--workspace-theme-photo', `url("${photoUrl}")`);
      if (!alreadyApplied || !sameColor) {
        paintPalette(shell, paletteForWorkspace(color));
      }
      shell.dataset.workspaceTheme = 'asset';
      syncContrastRegions(shell.hasAttribute('data-workspace-palette') ? shell : null);
      return;
    }
    syncContrastRegions(null);
    shell.style.removeProperty('--workspace-theme-photo');
    if (shell.hasAttribute('data-workspace-palette')) paintPalette(shell, null);
    if (previewReady && eligible && previewWindow !== null && previewWindow === windowKey) {
      shell.dataset.workspaceTheme = 'mist-lake';
    } else {
      delete shell.dataset.workspaceTheme;
    }
  }

  global.RunTeamsWorkspaceTheme = Object.freeze({sync, themeOverlay, preparePhoto});
})(window);
