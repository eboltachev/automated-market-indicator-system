import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(process.env.FRONTEND_ROOT || join(__dirname, 'dist'));
const port = Number(process.env.PORT || 5004);
const host = process.env.HOST || '0.0.0.0';
const backendUrl = (process.env.BACKEND_URL || 'http://backend:5000').replace(/\/$/, '');

const mimeTypes = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.mjs', 'text/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.gif', 'image/gif'],
  ['.ico', 'image/x-icon'],
  ['.webp', 'image/webp'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
]);

const hopByHopHeaders = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  'host',
  'content-length',
]);

function sendText(res, status, text, contentType = 'text/plain; charset=utf-8') {
  res.writeHead(status, {
    'content-type': contentType,
    'content-length': Buffer.byteLength(text),
  });
  res.end(text);
}

function safePathFromUrl(url) {
  const pathname = decodeURIComponent(new URL(url, 'http://localhost').pathname);
  const normalized = normalize(pathname).replace(/^([/\\])+/, '');
  const candidate = resolve(root, normalized);
  return candidate === root || candidate.startsWith(`${root}/`) ? candidate : null;
}

async function readRequestBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

async function proxyToBackend(req, res) {
  const target = `${backendUrl}${req.url}`;
  const headers = new Headers();

  for (const [key, value] of Object.entries(req.headers)) {
    if (!value || hopByHopHeaders.has(key.toLowerCase())) continue;
    if (Array.isArray(value)) {
      for (const item of value) headers.append(key, item);
    } else {
      headers.set(key, value);
    }
  }

  const hasBody = !['GET', 'HEAD'].includes(req.method || 'GET');
  const body = hasBody ? await readRequestBody(req) : undefined;

  const backendResponse = await fetch(target, {
    method: req.method,
    headers,
    body,
    redirect: 'manual',
  });

  const responseHeaders = {};
  backendResponse.headers.forEach((value, key) => {
    if (!hopByHopHeaders.has(key.toLowerCase())) {
      responseHeaders[key] = value;
    }
  });

  res.writeHead(backendResponse.status, responseHeaders);

  if (req.method === 'HEAD' || !backendResponse.body) {
    res.end();
    return;
  }

  const reader = backendResponse.body.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      res.write(Buffer.from(value));
    }
  } finally {
    res.end();
  }
}

async function serveStatic(req, res) {
  if (req.url === '/__health') {
    sendText(res, 200, 'ok');
    return;
  }

  const url = new URL(req.url, 'http://localhost');

  if (url.pathname.startsWith('/api/') || url.pathname === '/health') {
    await proxyToBackend(req, res);
    return;
  }

  let filePath = safePathFromUrl(req.url);
  if (!filePath) {
    sendText(res, 400, 'Bad request');
    return;
  }

  if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
    filePath = join(root, 'index.html');
  }

  if (!existsSync(filePath)) {
    sendText(res, 404, 'Not found');
    return;
  }

  const stat = statSync(filePath);
  const ext = extname(filePath).toLowerCase();
  const isIndex = filePath.endsWith('index.html');
  const cacheControl = isIndex
    ? 'no-store'
    : 'public, max-age=31536000, immutable';

  res.writeHead(200, {
    'content-type': mimeTypes.get(ext) || 'application/octet-stream',
    'content-length': stat.size,
    'cache-control': cacheControl,
  });

  if (req.method === 'HEAD') {
    res.end();
    return;
  }

  createReadStream(filePath).pipe(res);
}

const server = createServer((req, res) => {
  serveStatic(req, res).catch((error) => {
    console.error(error);
    sendText(res, 502, 'Frontend server error');
  });
});

server.listen(port, host, () => {
  console.log(`Frontend server listening on http://${host}:${port}`);
  console.log(`Serving static files from ${root}`);
  console.log(`Proxying API requests to ${backendUrl}`);
});

process.on('SIGTERM', () => {
  server.close(() => process.exit(0));
});
