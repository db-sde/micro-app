import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogRequest, settingsBody, syncLabel } from '../src/components/catalogApi.mjs';

test('catalog HTTP failure remains an actionable error', async () => {
  await assert.rejects(catalogRequest('/uploads/1/retry', { method: 'POST' }, async () => ({
    ok: false, status: 400, json: async () => ({ detail: 'Resolve linked_university and reconcile.' }),
  })), /Resolve linked_university and reconcile/);
});

test('malformed error responses receive a safe fallback', async () => {
  await assert.rejects(catalogRequest('/uploads/1', {}, async () => ({
    ok: false, status: 503, json: async () => { throw new Error('invalid body'); },
  })), /Catalog request failed \(503\)/);
});

test('WordPress success and catalog failure are independent', async () => {
  const publication = { wp_status: 'publish', catalog_sync: { status: 'failed', last_error: 'Chatbot unavailable' } };
  assert.equal(syncLabel(publication.catalog_sync), 'Chatbot: failed');
  assert.equal(publication.wp_status, 'publish');
  const status = await catalogRequest('/uploads/1', {}, async () => ({ ok: true, json: async () => publication.catalog_sync }));
  assert.equal(status.last_error, 'Chatbot unavailable');
});

test('reviewed mapping and explicit removal approval are serialized without credentials', () => {
  assert.deepEqual(JSON.parse(settingsBody(' nmims ', ' faqs, about_content, ', true)), {
    catalog_slug: 'nmims', clear_fields: ['faqs', 'about_content'], removals_approved: true,
  });
  assert.deepEqual(JSON.parse(settingsBody('', '', false)), { catalog_slug: null, clear_fields: [], removals_approved: false });
});

// Exercise the actual JSX presentation too, using Vite's installed transformer
// and React's server renderer; effects do not make network requests in this test.
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';
const require = createRequire(import.meta.url);
const componentPath = new URL('../src/components/CatalogSync.jsx', import.meta.url);
const source = (await readFile(componentPath, 'utf8'))
  .replace("'react'", JSON.stringify(pathToFileURL(require.resolve('react')).href))
  .replace("'./catalogApi.mjs'", JSON.stringify(new URL('../src/components/catalogApi.mjs', import.meta.url).href));
const compiled = await transformWithEsbuild(source, 'CatalogSync.jsx', { loader: 'jsx' });
const { default: CatalogSync } = await import(`data:text/javascript;base64,${Buffer.from(compiled.code).toString('base64')}`);

test('actual catalog panel renders actionable failure and retry alongside separate publication state', () => {
  const markup = renderToStaticMarkup(React.createElement(CatalogSync, {
    uploadId: 1, initialSync: { status: 'failed', last_error: 'Resolve linked_university and reconcile.' },
  }));
  assert.match(markup, /Chatbot: failed/);
  assert.match(markup, /role="alert"/);
  assert.match(markup, /Resolve linked_university and reconcile/);
  assert.match(markup, /Retry catalog sync/);
  assert.doesNotMatch(markup, /WordPress publish failed/);
});

test('actual synced panel shows receiver warnings and omits retry', () => {
  const markup = renderToStaticMarkup(React.createElement(CatalogSync, {
    uploadId: 1, initialSync: { status: 'synced', version: 3, entity_slug: 'nmims', warnings: ['Fee range was preserved without numeric conversion.'] },
  }));
  assert.match(markup, /Chatbot: synced/);
  assert.match(markup, /Fee range was preserved/);
  assert.match(markup, /nmims/);
  assert.doesNotMatch(markup, /Retry catalog sync/);
});
