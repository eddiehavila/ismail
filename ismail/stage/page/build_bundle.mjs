// bundle.js for the stage: main.js and everything it imports, three.js and its addons included, one ES module.
// node build_bundle.mjs  (server.py runs it when a source is newer than bundle.js). esbuild comes from D:/cole.
import { createRequire } from 'module';
import path from 'path';
import { fileURLToPath } from 'url';
const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const esbuild = require(process.env.ESBUILD || 'D:/cole/node_modules/esbuild');
const vendor = path.join(here, 'vendor', 'three');
const threePaths = {
  name: 'three-vendor',
  setup(b) {
    b.onResolve({ filter: /^three$/ }, () => ({ path: path.join(vendor, 'build', 'three.module.js') }));
    b.onResolve({ filter: /^three\/addons\// }, (a) => ({ path: path.join(vendor, 'examples', 'jsm', a.path.slice('three/addons/'.length)) }));
  },
};
const t0 = Date.now();
await esbuild.build({ entryPoints: [path.join(here, 'main.js')], bundle: true, format: 'esm', target: 'es2022',
  outfile: path.join(here, 'bundle.js'), plugins: [threePaths], logLevel: 'warning', legalComments: 'none' });
console.log('bundle.js built in', Date.now() - t0, 'ms');
