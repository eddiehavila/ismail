// bundle.js for the stage: main.js and everything it imports, three.js and its addons included, one ES module.
// ESBUILD=<path to the esbuild package> BUNDLE_OUT=<file> node build_bundle.mjs   (the stage server runs it when a
// page module is newer than the bundle; without esbuild the page loads its modules one by one instead).
import { createRequire } from 'module';
import path from 'path';
import { fileURLToPath } from 'url';
const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const esbuild = require(process.env.ESBUILD || 'esbuild');
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
  outfile: process.env.BUNDLE_OUT || path.join(here, 'bundle.js'), plugins: [threePaths], logLevel: 'warning', legalComments: 'none' });
console.log('bundle.js built in', Date.now() - t0, 'ms');
