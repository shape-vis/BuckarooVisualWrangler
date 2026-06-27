import { addCustomEvent, record } from "rrweb";

const ENABLE_KEY = "buckarooDebugReplay";
const STORAGE_KEY = "buckarooDebugReplayEvents";
const MAX_EVENTS = 2000;
const MAX_ARRAY_ITEMS = 250;

let stopRecording = null;
let recordingStarted = false;
let events = [];
let apiAttached = false;
let debugContext = {};

function hasBrowserStorage() {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

function defaultEnabled() {
  return import.meta.env.DEV || import.meta.env.VITE_BUCKAROO_DEBUG_REPLAY === "true";
}

export function isInteractionLoggingEnabled() {
  if (typeof window === "undefined") return false;
  let override = null;
  try {
    override = window.localStorage?.getItem(ENABLE_KEY);
  } catch {
    override = null;
  }
  if (override === "1") return true;
  if (override === "0") return false;
  return defaultEnabled();
}

function loadStoredEvents() {
  if (!hasBrowserStorage()) return;
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    events = stored ? JSON.parse(stored) : [];
  } catch {
    events = [];
  }
}

function persistEvents() {
  if (!hasBrowserStorage()) return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(events));
  } catch {
    events = events.slice(-Math.floor(MAX_EVENTS / 2));
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(events));
    } catch {
      // Keep the in-memory events even if browser storage is full.
    }
  }
}

function summarizeArray(value) {
  return {
    count: value.length,
    sample: value.slice(0, MAX_ARRAY_ITEMS).map(item => sanitizePayload(item)),
    truncated: value.length > MAX_ARRAY_ITEMS,
  };
}

function sanitizePayload(value) {
  if (Array.isArray(value)) return summarizeArray(value);
  if (!value || typeof value !== "object") return value;

  const result = {};
  Object.entries(value).forEach(([key, child]) => {
    if (key.toLowerCase().includes("password")) {
      result[key] = "[redacted]";
      return;
    }
    result[key] = sanitizePayload(child);
  });
  return result;
}

function rememberEvent(entry) {
  events.push(entry);
  if (events.length > MAX_EVENTS) {
    events = events.slice(-MAX_EVENTS);
  }
  persistEvents();
}

export function logInteractionEvent(type, payload = {}) {
  if (!isInteractionLoggingEnabled()) return;

  const entry = {
    kind: "buckaroo",
    type,
    payload: sanitizePayload(payload),
    timestamp: Date.now(),
    path: typeof window !== "undefined" ? window.location.pathname : "",
  };

  rememberEvent(entry);
  if (recordingStarted) {
    addCustomEvent(type, entry);
  }
}

function browserSnapshot() {
  if (typeof window === "undefined") return {};
  const nav = window.navigator || {};
  return {
    userAgent: nav.userAgent || "",
    language: nav.language || "",
    platform: nav.platform || "",
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
    url: window.location?.href || "",
    path: window.location?.pathname || "",
  };
}

export function setInteractionDebugContext(context = {}) {
  debugContext = sanitizePayload({
    ...debugContext,
    ...context,
  });
}

export function exportInteractionRecording() {
  return {
    generatedAt: new Date().toISOString(),
    enabled: isInteractionLoggingEnabled(),
    recordingStarted,
    eventCount: events.length,
    browser: browserSnapshot(),
    appContext: debugContext,
    events,
  };
}

export function summarizeInteractionRecording(limit = 20) {
  const buckarooEvents = events
    .filter(entry => entry.kind === "buckaroo")
    .slice(-limit)
    .map(entry => ({
      type: entry.type,
      time: new Date(entry.timestamp).toLocaleTimeString(),
      payload: entry.payload,
    }));

  return {
    generatedAt: new Date().toISOString(),
    enabled: isInteractionLoggingEnabled(),
    recordingStarted,
    totalEventCount: events.length,
    buckarooEventCount: events.filter(entry => entry.kind === "buckaroo").length,
    rrwebEventCount: events.filter(entry => entry.kind === "rrweb").length,
    browser: browserSnapshot(),
    appContext: debugContext,
    recentBuckarooActions: buckarooEvents,
    note: "Use window.buckarooDebugReplay.download() for the full replay JSON.",
  };
}

export function downloadInteractionRecording() {
  if (typeof document === "undefined") return;
  const blob = new Blob([JSON.stringify(exportInteractionRecording(), null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `buckaroo-debug-replay-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function clearInteractionRecording() {
  events = [];
  if (hasBrowserStorage()) {
    window.sessionStorage.removeItem(STORAGE_KEY);
  }
}

export function stopInteractionRecording() {
  if (stopRecording) {
    stopRecording();
    stopRecording = null;
  }
  recordingStarted = false;
}

export function setInteractionLoggingEnabled(enabled) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ENABLE_KEY, enabled ? "1" : "0");
  } catch {
    // If localStorage is unavailable, still allow this runtime session to start/stop.
  }
  if (enabled) {
    startInteractionRecording();
  } else {
    stopInteractionRecording();
  }
}

function attachDebugApi() {
  if (apiAttached || typeof window === "undefined") return;
  apiAttached = true;
  window.buckarooDebugReplay = {
    start: startInteractionRecording,
    stop: stopInteractionRecording,
    enable: () => setInteractionLoggingEnabled(true),
    disable: () => setInteractionLoggingEnabled(false),
    clear: clearInteractionRecording,
    export: exportInteractionRecording,
    summary: summarizeInteractionRecording,
    download: downloadInteractionRecording,
    context: () => debugContext,
    isEnabled: isInteractionLoggingEnabled,
  };
}

export function startInteractionRecording() {
  attachDebugApi();
  loadStoredEvents();

  if (!isInteractionLoggingEnabled() || recordingStarted) return;

  stopRecording = record({
    emit(event, isCheckout) {
      rememberEvent({
        kind: "rrweb",
        event,
        isCheckout: Boolean(isCheckout),
      });
    },
    blockClass: "rr-block",
    ignoreClass: "rr-ignore",
    maskTextClass: "rr-mask",
    maskAllInputs: true,
    checkoutEveryNth: 200,
    mousemoveWait: 80,
  });

  recordingStarted = Boolean(stopRecording);
  logInteractionEvent("debug_replay_started", {
    mode: import.meta.env.MODE,
    maxEvents: MAX_EVENTS,
  });
  if (recordingStarted) {
    console.info(
      "[Buckaroo Debug Replay] Recording enabled. Use window.buckarooDebugReplay.download() to export a repro log."
    );
  }
}
