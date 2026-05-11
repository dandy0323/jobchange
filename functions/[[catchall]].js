/**
 * Cloudflare Pages Function: catch-all proxy
 *
 * Routes:
 *   POST /jobs            → Railway FastAPI
 *   GET  /jobs/*          → Railway FastAPI
 *   GET  /outputs/*       → Railway FastAPI  (generated reports served directly)
 *   GET  /api/railway-status → health-check endpoint (used by wake-up UI)
 *   *                     → next() (Cloudflare Pages static assets)
 *
 * Required env var (set in Cloudflare Pages → Settings → Environment variables):
 *   RAILWAY_URL  e.g. https://jobchange-production.up.railway.app
 */

const PROXY_PREFIXES = ["/jobs", "/outputs"];
const HEALTH_TIMEOUT_MS = 8000;   // first-touch probe timeout
const WAKE_POLL_INTERVAL_MS = 4000;

/**
 * Main handler
 */
export async function onRequest(context) {
  const { request, env, next } = context;
  const url = new URL(request.url);
  const railwayUrl = (env.RAILWAY_URL || "").replace(/\/$/, "");

  // ── /api/railway-status ──────────────────────────────────────────
  if (url.pathname === "/api/railway-status") {
    if (!railwayUrl) {
      return json({ ok: false, reason: "RAILWAY_URL not configured" }, 503);
    }
    try {
      const probe = await fetch(`${railwayUrl}/`, {
        signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      });
      return json({ ok: probe.ok, status: probe.status });
    } catch (e) {
      return json({ ok: false, reason: e.message }, 503);
    }
  }

  // ── Decide whether to proxy ───────────────────────────────────────
  const shouldProxy = PROXY_PREFIXES.some((p) => url.pathname.startsWith(p));
  if (!shouldProxy) return next();

  // ── No RAILWAY_URL → show config error ───────────────────────────
  if (!railwayUrl) {
    return htmlPage(
      "設定エラー",
      `<p style="color:#ef4444">環境変数 <code>RAILWAY_URL</code> が設定されていません。<br>
       Cloudflare Pages の Settings → Environment variables で設定してください。</p>`
    );
  }

  // ── Probe Railway (cold-start detection) ─────────────────────────
  // Only probe on GET navigation requests (not XHR/fetch sub-resources)
  const acceptHeader = request.headers.get("accept") || "";
  const isNavigation =
    request.method === "GET" && acceptHeader.includes("text/html");

  if (isNavigation) {
    let railwayOk = false;
    try {
      const probe = await fetch(`${railwayUrl}/`, {
        signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      });
      railwayOk = probe.ok;
    } catch (_) {
      railwayOk = false;
    }

    if (!railwayOk) {
      // Return wake-up waiting page with auto-retry
      return wakingPage(url.pathname + url.search);
    }
  }

  // ── Proxy the request to Railway ─────────────────────────────────
  const target = new URL(url.pathname + url.search, railwayUrl);
  const proxyReq = new Request(target.toString(), {
    method: request.method,
    headers: request.headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    redirect: "follow",
  });

  try {
    return await fetch(proxyReq);
  } catch (e) {
    return htmlPage(
      "接続エラー",
      `<p style="color:#ef4444">Railway サーバーへの接続に失敗しました。<br>
       しばらくしてからもう一度お試しください。</p>
       <p style="color:#94a3b8;font-size:.85rem">${e.message}</p>
       <br><a href="javascript:location.reload()" class="btn">再試行</a>`
    );
  }
}

// ─── helpers ────────────────────────────────────────────────────────────────

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function htmlPage(title, bodyContent) {
  return new Response(
    `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${title} — 企業調査</title>
<style>
  :root{--bg:#0f172a;--surface:#1e293b;--text:#f1f5f9;--text2:#94a3b8;--accent:#38bdf8;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);
       min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem;}
  .box{background:var(--surface);border-radius:14px;padding:2.5rem;max-width:480px;width:100%;text-align:center;}
  h1{font-size:1.3rem;margin-bottom:1.2rem;}
  .btn{display:inline-block;margin-top:1rem;padding:.6rem 1.4rem;background:var(--accent);
       color:#000;border-radius:8px;font-weight:700;text-decoration:none;cursor:pointer;border:none;font-size:1rem;}
</style>
</head>
<body>
<div class="box"><h1>${title}</h1>${bodyContent}</div>
</body></html>`,
    { status: 200, headers: { "content-type": "text/html;charset=utf-8" } }
  );
}

function wakingPage(returnPath) {
  const escaped = returnPath.replace(/"/g, "&quot;");
  return new Response(
    `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>サーバー起動中 — 企業調査</title>
<style>
  :root{--bg:#0f172a;--surface:#1e293b;--text:#f1f5f9;--text2:#94a3b8;--accent:#38bdf8;--green:#10b981;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);
       min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem;}
  .box{background:var(--surface);border-radius:14px;padding:2.5rem;max-width:480px;width:100%;text-align:center;}
  .spinner{width:48px;height:48px;border:4px solid #334155;border-top-color:var(--accent);
           border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 1.5rem;}
  @keyframes spin{to{transform:rotate(360deg)}}
  h1{font-size:1.25rem;margin-bottom:.6rem;}
  p{color:var(--text2);font-size:.9rem;line-height:1.6;}
  .status{margin-top:1.2rem;font-size:.82rem;color:var(--text2);}
  .dots::after{content:'';animation:dots 1.5s steps(4,end) infinite;}
  @keyframes dots{0%{content:'';}25%{content:'.';}50%{content:'..';}75%{content:'...';}100%{content:'';}}
  .ok{color:var(--green);font-weight:700;}
</style>
</head>
<body>
<div class="box">
  <div class="spinner"></div>
  <h1>サーバーを起動しています</h1>
  <p>Railway のサーバーがスリープ状態のため起動中です。<br>通常 30〜60 秒で完了します。</p>
  <p class="status">確認中<span class="dots"></span></p>
</div>
<script>
(async function() {
  const returnPath = "${escaped}";
  const interval = ${WAKE_POLL_INTERVAL_MS};
  const statusEl = document.querySelector('.status');
  let attempt = 0;

  async function checkReady() {
    attempt++;
    statusEl.textContent = '確認中 (' + attempt + '回目)';
    try {
      const res = await fetch('/api/railway-status');
      const data = await res.json();
      if (data.ok) {
        statusEl.innerHTML = '<span class="ok">✓ 起動完了！リダイレクト中...</span>';
        window.location.href = returnPath;
        return;
      }
    } catch (_) {}
    setTimeout(checkReady, interval);
  }

  // Start polling after a short delay to let Railway begin waking
  setTimeout(checkReady, 2000);
})();
</script>
</body></html>`,
    { status: 200, headers: { "content-type": "text/html;charset=utf-8" } }
  );
}
