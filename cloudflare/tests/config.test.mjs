import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('deployment keeps one container, the full parent image context and a private R2 binding', async () => {
  const config = JSON.parse(await readFile(new URL('../wrangler.jsonc', import.meta.url), 'utf8'));
  assert.equal(config.name, 'draincheck');
  assert.equal(config.account_id, 'abeef81bb3a4248c72956a9246527d8b');
  assert.equal(config.assets.directory, '../dist');
  assert.deepEqual(config.assets.run_worker_first, ['/api', '/api/*']);
  assert.equal(config.containers.length, 1);
  assert.equal(config.containers[0].instance_type, 'standard-2');
  assert.equal(config.containers[0].max_instances, 1);
  assert.equal(config.containers[0].image, '../Dockerfile');
  assert.equal(config.containers[0].image_build_context, '..');
  assert.deepEqual(config.r2_buckets, [{ binding: 'DRAINCHECK_STATE', bucket_name: 'draincheck-state' }]);
  assert.equal(config.durable_objects.bindings[0].class_name, config.containers[0].class_name);
  assert.deepEqual(config.migrations[0].new_sqlite_classes, [config.containers[0].class_name]);
});
