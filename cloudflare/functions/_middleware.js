// Protege o painel inteiro com senha (Basic Auth), igual ao editor do Market Picks.
// A senha fica no Cloudflare como segredo PAINEL_SENHA (nunca no código).
export async function onRequest({ request, env, next }) {
  const expected = (env.PAINEL_SENHA || "").trim();
  const header = request.headers.get("Authorization") || "";
  let pass = null;
  if (header.startsWith("Basic ")) {
    try {
      const decoded = atob(header.slice(6));
      const idx = decoded.indexOf(":");
      pass = (idx >= 0 ? decoded.slice(idx + 1) : decoded).trim();
    } catch (e) { pass = null; }
  }
  if (!expected || pass !== expected) {
    return new Response("Autenticação necessária.", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="Monitor de Voos"', "Cache-Control": "no-store" }
    });
  }
  const res = await next();
  const out = new Response(res.body, res);
  out.headers.set("Cache-Control", "no-store");
  out.headers.set("X-Robots-Tag", "noindex");
  return out;
}
