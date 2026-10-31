// JSON calls to the page's own server. A non-2xx answer throws an Error carrying the server's error body:
// `message`, plus `code` and `details` (one per problem, with `line`, `field`).
// A 401 (login on, no live session) sends the page to /login and back; that call never settles.

export async function api(path, options) {
  const res = await fetch(path, options);
  if (res.status === 401) {
    location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`);
    return new Promise(() => {});
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(body.message || res.statusText), { code: body.code, details: body.details || [] });
  return body;
}

// One line per problem of an error from `api`: "loại kiện A3, qty: …".
export function errorText(e) {
  const where = (d) => [d.line && `loại kiện ${d.line}`, d.container && `container ${d.container}`, d.field].filter(Boolean).join(', ');
  return [e.message, ...(e.details || []).map((d) => (where(d) ? `${where(d)}: ${d.message}` : d.message))].join('\n');
}

export const postJSON = (path, body) =>
  api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
