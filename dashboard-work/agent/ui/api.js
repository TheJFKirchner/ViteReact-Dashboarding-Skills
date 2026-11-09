// Calls to agent/server.py through the Vite proxy (/agent/*).
async function call(method, name, body) {
  const res = await fetch(`/agent/${name}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || `agent server returned ${res.status}`);
  return json;
}

export const agentApi = {
  get: (name) => call('GET', name),
  post: (name, body = {}) => call('POST', name, body),
};
