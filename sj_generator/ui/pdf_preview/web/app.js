const state = {
  bridge: null,
  pdfDoc: null,
  pdfPath: "",
  scale: 1.8,
  cropEnabled: false,
  selectionOutlineVisible: true,
  currentPageIndex: -1,
  selectionPayload: null,
  pageEntries: [],
  selectionSyncTimer: null,
};

const cropRatios = {
  left: 0.06,
  right: 0.06,
  top: 0.05,
  bottom: 0.08,
};

const elements = {
  pages: document.getElementById("pages"),
  scrollContainer: document.getElementById("scrollContainer"),
  statusText: document.getElementById("statusText"),
  pageText: document.getElementById("pageText"),
};

function setStatus(text) {
  if (elements.statusText) {
    elements.statusText.textContent = text;
  }
}

function setPageText(text) {
  if (elements.pageText) {
    elements.pageText.textContent = text;
  }
}

function setupPdfJs() {
  if (!window.pdfjsLib) {
    throw new Error("PDF.js 未加载");
  }
  pdfjsLib.GlobalWorkerOptions.workerSrc = "./vendor/pdfjs/pdf.worker.min.js";
}

function setupBridge() {
  return new Promise((resolve, reject) => {
    if (!window.qt || !window.qt.webChannelTransport || !window.QWebChannel) {
      state.bridge = null;
      resolve(null);
      return;
    }
    try {
      new QWebChannel(window.qt.webChannelTransport, (channel) => {
        state.bridge = channel.objects.bridge || null;
        resolve(state.bridge);
      });
    } catch (error) {
      reject(error);
    }
  });
}

function notifyBridge(method, ...args) {
  if (!state.bridge || typeof state.bridge[method] !== "function") {
    return;
  }
  state.bridge[method](...args);
}

function resetViewer() {
  elements.pages.innerHTML = "";
  state.pageEntries = [];
  state.currentPageIndex = -1;
  state.selectionPayload = null;
  setPageText("");
}

function round(value) {
  return Math.round(value * 1000) / 1000;
}

function mergeInlineRects(rects) {
  if (!rects.length) {
    return [];
  }
  
  // 1. 按照 y 坐标排序（从上到下），如果 y 差不多，按 x 排序（从左到右）
  const sorted = [...rects].sort((a, b) => {
    // 允许 3px 左右的误差认为是在同一行
    if (Math.abs(a.y - b.y) > 3) {
      return a.y - b.y;
    }
    return a.x - b.x;
  });

  const merged = [];
  let current = { ...sorted[0] };

  for (let i = 1; i < sorted.length; i++) {
    const next = sorted[i];
    
    // 判断是否在同一行：
    // y 轴差距很小（比如小于当前行高的 50%）
    const isSameLine = Math.abs(current.y - next.y) < current.height * 0.5;
    
    if (isSameLine) {
      // 在同一行，则合并：扩大右边界和底边界
      const newRight = Math.max(current.x + current.width, next.x + next.width);
      const newBottom = Math.max(current.y + current.height, next.y + next.height);
      const newTop = Math.min(current.y, next.y);
      
      current.x = Math.min(current.x, next.x);
      current.y = newTop;
      current.width = newRight - current.x;
      current.height = newBottom - current.y;
    } else {
      // 换行了，把当前行推入结果，开启新行
      merged.push({ ...current });
      current = { ...next };
    }
  }
  merged.push(current);

  return merged.map(rect => ({
    x: round(rect.x),
    y: round(rect.y),
    width: round(rect.width),
    height: round(rect.height),
  }));
}

function createPageEntry(pageNumber, viewport) {
  const pageElement = document.createElement("div");
  pageElement.className = "pdf-page";
  pageElement.dataset.pageNumber = String(pageNumber);
  pageElement.style.width = `${viewport.width}px`;
  pageElement.style.height = `${viewport.height}px`;

  const canvas = document.createElement("canvas");
  canvas.className = "pdf-canvas";
  
  // 强制拉高像素倍率，哪怕 dpr 只有 1 也要当成 2 或者 3 渲染，配合 CSS 缩小。
  const dpr = Math.max(window.devicePixelRatio || 1, 2);
  const outputScale = dpr * 1.5; // 额外增加 1.5 倍渲染缓冲
  
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;

  const textLayer = document.createElement("div");
  textLayer.className = "textLayer";

  const selectionLayer = document.createElement("div");
  selectionLayer.className = "selectionLayer";

  const cropLayer = document.createElement("div");
  cropLayer.className = "cropLayer";

  const masks = ["top", "bottom", "left", "right"].map((name) => {
    const mask = document.createElement("div");
    mask.className = "crop-mask";
    mask.dataset.mask = name;
    cropLayer.appendChild(mask);
    return mask;
  });

  pageElement.appendChild(canvas);
  pageElement.appendChild(textLayer);
  pageElement.appendChild(selectionLayer);
  pageElement.appendChild(cropLayer);
  elements.pages.appendChild(pageElement);

  return {
    pageNumber,
    pageElement,
    canvas,
    textLayer,
    selectionLayer,
    cropLayer,
    masks,
    width: viewport.width,
    height: viewport.height,
  };
}

function applyCropMasks() {
  // 如果开启裁边，放大 PDF（比如放大到 1.15 倍）来抵消被裁掉的白边，让文字看起来更大
  const displayScale = state.cropEnabled ? 1.15 : 1.0;
  
  for (const entry of state.pageEntries) {
    entry.pageElement.classList.toggle("crop-enabled", state.cropEnabled);
    
    // 通过 CSS transform 进行整体缩放
    entry.pageElement.style.transform = `scale(${displayScale})`;
    entry.pageElement.style.transformOrigin = "top center";
    
    // 为了防止缩放后重叠或间距不对，我们要调整它在容器里占据的实际 margin
    const extraHeight = entry.height * (displayScale - 1);
    
    if (state.cropEnabled) {
      const topCrop = entry.height * cropRatios.top * displayScale;
      const bottomCrop = entry.height * cropRatios.bottom * displayScale;
      const leftCrop = entry.width * cropRatios.left;
      const rightCrop = entry.width * cropRatios.right;
      
      // 用负 margin 吃掉被裁切的高度，这样页面之间的垂直间距会变紧凑
      // marginTop 吃掉顶部的裁切
      entry.pageElement.style.marginTop = `-${topCrop}px`;
      // marginBottom 吃掉底部的裁切，同时补偿 scale 带来的额外高度 (extraHeight)
      entry.pageElement.style.marginBottom = `${extraHeight - bottomCrop}px`;
      
      // 动态修改 clip-path 裁掉白边（因为使用了 transform scale，这里 clip-path 需要用原比例数值）
      entry.pageElement.style.clipPath = `inset(${cropRatios.top * 100}% ${cropRatios.right * 100}% ${cropRatios.bottom * 100}% ${cropRatios.left * 100}%)`;
    } else {
      entry.pageElement.style.marginTop = "0px";
      entry.pageElement.style.marginBottom = "0px";
      entry.pageElement.style.clipPath = "none";
    }

    // 更新旧的遮罩层坐标（虽然现在它们在 CSS 里 display: none 了，但保留计算以免抛错）
    const leftWidth = entry.width * cropRatios.left;
    const rightWidth = entry.width * cropRatios.right;
    const topHeight = entry.height * cropRatios.top;
    const bottomHeight = entry.height * cropRatios.bottom;
    
    const [topMask, bottomMask, leftMask, rightMask] = entry.masks;
    topMask.style.left = "0";
    topMask.style.top = "0";
    topMask.style.width = `${entry.width}px`;
    topMask.style.height = `${topHeight}px`;

    bottomMask.style.left = "0";
    bottomMask.style.top = `${entry.height - bottomHeight}px`;
    bottomMask.style.width = `${entry.width}px`;
    bottomMask.style.height = `${bottomHeight}px`;

    leftMask.style.left = "0";
    leftMask.style.top = `${topHeight}px`;
    leftMask.style.width = `${leftWidth}px`;
    leftMask.style.height = `${Math.max(0, entry.height - topHeight - bottomHeight)}px`;

    rightMask.style.left = `${entry.width - rightWidth}px`;
    rightMask.style.top = `${topHeight}px`;
    rightMask.style.width = `${rightWidth}px`;
    rightMask.style.height = `${Math.max(0, entry.height - topHeight - bottomHeight)}px`;
  }
}

function renderStoredSelection() {
  for (const entry of state.pageEntries) {
    entry.selectionLayer.innerHTML = "";
  }
  if (!state.selectionOutlineVisible || !state.selectionPayload) {
    return;
  }
  for (const fragment of state.selectionPayload.fragments || []) {
    const entry = state.pageEntries.find((item) => item.pageNumber === fragment.page_index + 1);
    if (!entry) {
      continue;
    }
    for (const rect of fragment.rects || []) {
      const [x, y, width, height] = rect;
      if (width <= 0 || height <= 0) {
        continue;
      }
      const rectElement = document.createElement("div");
      rectElement.className = "selection-rect";
      rectElement.style.left = `${x}px`;
      rectElement.style.top = `${y}px`;
      rectElement.style.width = `${width}px`;
      rectElement.style.height = `${height}px`;
      entry.selectionLayer.appendChild(rectElement);
    }
  }
}

function buildSelectionPayload() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return null;
  }
  const copiedText = selection.toString().trim();
  if (!copiedText) {
    return null;
  }
  const range = selection.getRangeAt(0);
  const rawRects = Array.from(range.getClientRects()).filter(
    (rect) => rect.width > 0 && rect.height > 0,
  );
  if (!rawRects.length) {
    return null;
  }
  
  const displayScale = state.cropEnabled ? 1.15 : 1.0;
  
  const fragmentsByPage = new Map();
  for (const rect of rawRects) {
    const x = rect.left + Math.min(rect.width / 2, Math.max(rect.width - 1, 0));
    const y = rect.top + Math.min(rect.height / 2, Math.max(rect.height - 1, 0));
    const element = document.elementFromPoint(x, y);
    const pageElement = element ? element.closest(".pdf-page") : null;
    if (!pageElement) {
      continue;
    }
    const pageRect = pageElement.getBoundingClientRect();
    const pageIndex = Number(pageElement.dataset.pageNumber) - 1;
    if (!fragmentsByPage.has(pageIndex)) {
      fragmentsByPage.set(pageIndex, []);
    }
    fragmentsByPage.get(pageIndex).push({
      x: round((rect.left - pageRect.left) / displayScale),
      y: round((rect.top - pageRect.top) / displayScale),
      width: round(rect.width / displayScale),
      height: round(rect.height / displayScale),
    });
  }
  if (!fragmentsByPage.size) {
    return null;
  }
  const fragments = Array.from(fragmentsByPage.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([pageIndex, rects]) => ({
      page_index: pageIndex,
      copied_text: copiedText,
      rects: mergeInlineRects(rects).map((rect) => [rect.x, rect.y, rect.width, rect.height]),
    }))
    .filter((fragment) => fragment.rects.length > 0);
  if (!fragments.length) {
    return null;
  }
  return {
    pdf_path: state.pdfPath,
    copied_text: copiedText,
    fragments,
  };
}

function syncSelectionFromDom() {
  const payload = buildSelectionPayload();
  if (!payload) {
    return;
  }
  
  // 允许多次框选累加，而不是覆盖
  if (!state.selectionPayload) {
    state.selectionPayload = payload;
  } else {
    // 累加 copied_text
    const newText = state.selectionPayload.copied_text 
      ? state.selectionPayload.copied_text + "\n" + payload.copied_text
      : payload.copied_text;
      
    // 累加 fragments（按页合并 rects）
    const mergedFragments = [...state.selectionPayload.fragments];
    for (const newFragment of payload.fragments) {
      const existing = mergedFragments.find(f => f.page_index === newFragment.page_index);
      if (existing) {
        existing.rects.push(...newFragment.rects);
      } else {
        mergedFragments.push(newFragment);
      }
    }
    
    // 更新 payload
    state.selectionPayload = {
      pdf_path: payload.pdf_path,
      copied_text: newText,
      fragments: mergedFragments
    };
  }

  // 框选完后，清除原生蓝底选区，避免下次误触引发重复累加
  const selection = window.getSelection();
  if (selection) {
    selection.removeAllRanges();
  }

  renderStoredSelection();
  notifyBridge("reportSelection", JSON.stringify(state.selectionPayload));
}

function scheduleSelectionSync() {
  if (state.selectionSyncTimer !== null) {
    window.clearTimeout(state.selectionSyncTimer);
  }
  state.selectionSyncTimer = window.setTimeout(() => {
    state.selectionSyncTimer = null;
    
    // 如果用户只是点击了空白处导致选区坍缩，我们不应该覆盖掉之前的红色高亮选区，
    // 除非他们显式调用了 clearSelectionVisual
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return;
    }
    
    syncSelectionFromDom();
  }, 30);
}

function clearSelectionVisual(notify = true) {
  const selection = window.getSelection();
  if (selection) {
    selection.removeAllRanges();
  }
  state.selectionPayload = null;
  renderStoredSelection();
  if (notify) {
    notifyBridge("reportSelection", "");
  }
}

function updateCurrentPage() {
  if (!state.pageEntries.length) {
    state.currentPageIndex = -1;
    setPageText("");
    return;
  }
  const containerRect = elements.scrollContainer.getBoundingClientRect();
  let bestEntry = state.pageEntries[0];
  let bestVisible = -1;
  for (const entry of state.pageEntries) {
    const rect = entry.pageElement.getBoundingClientRect();
    const visible =
      Math.min(rect.bottom, containerRect.bottom) - Math.max(rect.top, containerRect.top);
    if (visible > bestVisible) {
      bestVisible = visible;
      bestEntry = entry;
    }
  }
  const pageIndex = bestEntry.pageNumber - 1;
  if (state.currentPageIndex !== pageIndex) {
    state.currentPageIndex = pageIndex;
    notifyBridge("reportCurrentPage", pageIndex);
  }
  setPageText(`第 ${pageIndex + 1} / ${state.pageEntries.length} 页`);
}

// 全局监听窗口大小变化以重新渲染自适应宽度
let resizeTimer = null;
window.addEventListener("resize", () => {
  if (resizeTimer) clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.pdfDoc) {
      renderDocument();
    }
  }, 300);
});

async function renderPage(pageNumber) {
  const page = await state.pdfDoc.getPage(pageNumber);
  
  // 计算自适应宽度对应的缩放比例
  // 直接使用容器宽度，让文档贴合容器显示
  // 为了防止初始化时 scrollContainer.clientWidth 是 0，取 window.innerWidth 兜底
  const containerWidth = elements.scrollContainer.clientWidth || window.innerWidth;
  const targetWidth = Math.max(containerWidth, 400); // 至少 400px
  
  // 先用 scale=1.0 获取原始宽度，再算出我们需要的真实逻辑 scale
  const unscaledViewport = page.getViewport({ scale: 1.0 });
  state.scale = targetWidth / unscaledViewport.width;
  
  const viewport = page.getViewport({ scale: state.scale });
  const entry = createPageEntry(pageNumber, viewport);
  entry.pageElement.style.setProperty("--scale-factor", String(viewport.scale));
  entry.textLayer.style.setProperty("--scale-factor", String(viewport.scale));
  
  const dpr = Math.max(window.devicePixelRatio || 1, 2);
  const outputScale = dpr * 1.5;
  
  const renderContext = {
    canvasContext: entry.canvas.getContext("2d", { alpha: false, willReadFrequently: false }),
    viewport: page.getViewport({ scale: state.scale * outputScale }),
  };
  await page.render(renderContext).promise;
  const textContent = await page.getTextContent();
  const textLayerTask = pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container: entry.textLayer,
    viewport,
    textDivs: [],
  });
  if (textLayerTask && textLayerTask.promise) {
    await textLayerTask.promise;
  } else if (textLayerTask && typeof textLayerTask.then === "function") {
    await textLayerTask;
  }
  state.pageEntries.push(entry);
}

async function renderDocument() {
  resetViewer();
  if (!state.pdfDoc) {
    setStatus("未加载 PDF");
    return;
  }
  setStatus("正在渲染 PDF…");
  for (let pageNumber = 1; pageNumber <= state.pdfDoc.numPages; pageNumber += 1) {
    await renderPage(pageNumber);
  }
  applyCropMasks();
  renderStoredSelection();
  updateCurrentPage();
  setStatus(`已加载 ${state.pdfDoc.numPages} 页`);
}

async function loadPdf(fileUrl) {
  try {
    clearSelectionVisual(false);
    resetViewer();
    state.pdfPath = fileUrl;
    setStatus("正在加载 PDF…");
    const loadingTask = pdfjsLib.getDocument({
      url: fileUrl,
      disableRange: true,
      disableStream: true,
    });
    state.pdfDoc = await loadingTask.promise;
    await renderDocument();
  } catch (error) {
    state.pdfDoc = null;
    resetViewer();
    setStatus(`加载失败：${error.message || String(error)}`);
    notifyBridge("reportError", String(error.message || error));
  }
}

function jumpToPage(pageIndex) {
  const entry = state.pageEntries.find((item) => item.pageNumber === Number(pageIndex) + 1);
  if (!entry) {
    return;
  }
  entry.pageElement.scrollIntoView({ block: "start", behavior: "auto" });
  updateCurrentPage();
}

function setCropEnabled(enabled) {
  state.cropEnabled = Boolean(enabled);
  applyCropMasks();
}

function setSelectionOutlineVisible(enabled) {
  state.selectionOutlineVisible = Boolean(enabled);
  renderStoredSelection();
}

function installEvents() {
  elements.scrollContainer.addEventListener("scroll", () => {
    window.requestAnimationFrame(updateCurrentPage);
  });
  const preventCtrlWheelZoom = (event) => {
    if (!event.ctrlKey) {
      return;
    }
    event.preventDefault();
  };
  elements.scrollContainer.addEventListener("wheel", preventCtrlWheelZoom, { passive: false });
  document.addEventListener("wheel", preventCtrlWheelZoom, { passive: false });
  document.addEventListener("mouseup", scheduleSelectionSync);
  document.addEventListener("keyup", scheduleSelectionSync);
}

window.viewerApi = {
  loadPdf,
  jumpToPage,
  setCropEnabled,
  setSelectionOutlineVisible,
  clearSelectionVisual,
};

async function boot() {
  try {
    setupPdfJs();
  } catch (error) {
    setStatus(`初始化失败：${error.message || String(error)}`);
    console.error(error);
    return;
  }

  installEvents();

  try {
    await setupBridge();
  } catch (error) {
    setStatus(`桥接失败：${error.message || String(error)}`);
    console.error(error);
    return;
  }

  setStatus("查看器已就绪");
  notifyBridge("viewerReady");
}

window.addEventListener("DOMContentLoaded", boot);
