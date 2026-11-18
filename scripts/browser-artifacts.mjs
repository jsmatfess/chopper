// Shared boundary between browser validation assets and the deployable bundle.
export const testAssets = ['tests.html','browser-tests.js','benchmark.html','benchmark.js','benchmark.csv',
  'engine-resource-tests.wasm','engine-resource-tests-shuffle-partition.wasm','resource-contract-tests.html','resource-contract-tests.js','resource-contract-worker.js'];

export function assertProductionWasm(bytes) {
  const module = new WebAssembly.Module(bytes);
  if (WebAssembly.Module.exports(module).some(entry => entry.name === 'chopper_resource_contracts')) {
    throw new Error('Test resource-contract engine cannot be shipped. Rebuild with node scripts/build-browser.mjs without test features.');
  }
}

// Cargo accepts repeated feature switches, comma/space lists and qualified names.
// Inspect only feature values: unrelated arguments must not select a reactor.
export function browserEngineAsset(args) {
  if (!args.includes('--resource-contracts')) return 'engine.wasm';
  const features = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--all-features') return 'engine-resource-tests-shuffle-partition.wasm';
    if (args[i].startsWith('--features=')) features.push(args[i].slice('--features='.length));
    else if (args[i] === '--features' || args[i] === '-F') {
      while (i + 1 < args.length && !args[i + 1].startsWith('-')) features.push(args[++i]);
    } else if (args[i].startsWith('-F') && args[i].length > 2) features.push(args[i].slice(2).replace(/^=/, ''));
  }
  const partition = features.flatMap(value => value.split(/[,\s]+/)).some(value =>
    value === 'experimental-shuffle-partition' || value === 'chopper-browser/experimental-shuffle-partition' || value === 'chopper/experimental-shuffle-partition');
  return partition ? 'engine-resource-tests-shuffle-partition.wasm' : 'engine-resource-tests.wasm';
}
