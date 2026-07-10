const params = new URLSearchParams(window.location.search);

export const sessionId = params.get("session") || "default";
export const apiRoot = `/api/session/${encodeURIComponent(sessionId)}`;

export async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
    ...options,
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { error: text };
    }
  }
  if (!response.ok) {
    const error = new Error(payload.error || `请求失败（HTTP ${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

export function fetchSession(signal) {
  return requestJson(apiRoot, signal ? { signal } : {});
}

export function createEdge(edge) {
  return requestJson(`${apiRoot}/edges`, { method: "POST", body: JSON.stringify(edge) });
}

export function patchEdge(edgeId, patch) {
  return requestJson(`${apiRoot}/edges/${encodeURIComponent(edgeId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function removeEdge(edgeId) {
  return requestJson(`${apiRoot}/edges/${encodeURIComponent(edgeId)}`, { method: "DELETE" });
}

export function saveLayout(positions) {
  return requestJson(`${apiRoot}/layout`, {
    method: "POST",
    body: JSON.stringify({ positions }),
  });
}

export function saveComposer(composerOrder, composerMode) {
  return requestJson(`${apiRoot}/composer`, {
    method: "POST",
    body: JSON.stringify({ composerOrder, composerMode }),
  });
}

export function saveView(viewState) {
  return requestJson(`${apiRoot}/view`, {
    method: "POST",
    body: JSON.stringify(viewState),
  });
}

export function resetCanvas() {
  return requestJson(`${apiRoot}/reset`, { method: "POST", body: "{}" });
}

export function restoreCanvas(snapshot) {
  return requestJson(`${apiRoot}/restore-canvas`, {
    method: "POST",
    body: JSON.stringify(snapshot),
  });
}

export function exportUrl() {
  return `${apiRoot}/export`;
}
