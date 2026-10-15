// Reference approval service for botanical-image verification.
// Cloudflare Worker + KV. NOT deployed by this repo: see docs/BOTANICAL_VERIFICATION.md.
//
// Bindings: APPROVALS (KV namespace), APPROVER_KEY (secret), BASELINE_URL (var),
//           ALLOW_ORIGIN (var, e.g. https://fredericfourier.github.io)
//
// GET  /approvals            -> { approvals: { id: { imageSha256, approvedAt } } }   (public)
// POST /approve  {plantId,imageSha256}  + Authorization: Bearer <APPROVER_KEY>
//      accepted only if imageSha256 equals the published baseline hash for that plant.

const json = (o, status, env) => new Response(status === 204 ? null : JSON.stringify(o), {
  status: status || 200,
  headers: {
    'content-type': 'application/json',
    'access-control-allow-origin': (env && env.ALLOW_ORIGIN) || '*',
    'access-control-allow-headers': 'content-type, authorization',
    'access-control-allow-methods': 'GET, POST, OPTIONS',
    'cache-control': 'no-store'
  }
});

export async function handle(request, env, fetchImpl) {
  const f = fetchImpl || fetch;
  const url = new URL(request.url);
  if (request.method === 'OPTIONS') return json({}, 204, env);
  if (url.pathname.endsWith('/approvals') && request.method === 'GET') {
    const raw = await env.APPROVALS.get('approvals');
    return json({ approvals: raw ? JSON.parse(raw) : {} }, 200, env);
  }
  if (url.pathname.endsWith('/approve') && request.method === 'POST') {
    const auth = request.headers.get('authorization') || '';
    if (!env.APPROVER_KEY || auth !== 'Bearer ' + env.APPROVER_KEY) return json({ ok: false, error: 'unauthorised' }, 401, env);
    let body;
    try { body = await request.json(); } catch (e) { return json({ ok: false, error: 'bad json' }, 400, env); }
    const { plantId, imageSha256 } = body || {};
    if (typeof plantId !== 'string' || !/^[a-f0-9]{64}$/.test(imageSha256 || '')) return json({ ok: false, error: 'bad request' }, 400, env);
    const base = await (await f(env.BASELINE_URL, { cache: 'no-store' })).json();
    const rec = base.plants && base.plants[plantId];
    if (!rec) return json({ ok: false, error: 'unknown plant' }, 404, env);
    if (rec.imageSha256 !== imageSha256) return json({ ok: false, error: 'image changed; reload and re-review' }, 409, env);
    const raw = await env.APPROVALS.get('approvals');
    const all = raw ? JSON.parse(raw) : {};
    all[plantId] = { imageSha256, approvedAt: new Date().toISOString() };
    await env.APPROVALS.put('approvals', JSON.stringify(all));
    return json({ ok: true, approval: all[plantId] }, 200, env);
  }
  return json({ ok: false, error: 'not found' }, 404, env);
}

export default { fetch: (req, env) => handle(req, env) };
